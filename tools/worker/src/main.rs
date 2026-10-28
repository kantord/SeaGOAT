//! One executable that boots a sandbox, runs the coding agent against it, and leaves a patch.
//!
//! DECISION (owner, 2026-10-28): ported from the owner's copy of this tool in another project
//! and cut down for SeaGOAT: one image layer, no pre-built cargo target to keep fresh. The
//! copies evolve apart; port a fix by hand when it applies.
//!
//! DECISION (owner, 2026-10-28): a permanent temporary tool. It stays in this repo until it
//! becomes its own open-source project or something else makes it redundant; everything it needs
//! is under tools/worker/, so removing it is deleting that directory.
//!
//! DECISION: the agent loop runs on the host and only tool calls go into the guest. The
//! API key never enters the sandbox, so there is no secret placeholder and no status
//! files to read back out of the guest.
//!
//! DECISION: an attempt ends when the model stops calling tools or runs out of turns; the
//! harness verifies, feeds the tail back, retries. No progress cutoff (an earlier version's
//! misfired on 46 of 54 runs).
//!
//! DECISION: this binary is the per-run part (boot, agent, patch out); the orchestrator is the
//! Claude session that writes the brief and reviews the result, which run.py leaves applied in a
//! worktree. Parallel runs are parallel invocations: each gets its own sandbox.
//! The contract is the exit code plus the files `--out` gets.
//!
//! DECISION (owner, 2026-10-28): test a change at the cheapest level that covers it, because a
//! full run (model plus the whole gate) takes minutes, more on a busy machine:
//!   harness code    `MSB_HOME=~/.cache/seagoat-worker/msb WORKER_TEST_IMAGE=seagoat-worker:latest
//!                   cargo test -- --ignored`, a real guest and no model, about 3 s
//!   prompt, config  run.py with a narrow `--verify-cmd`, e.g. one pytest file, a minute or two
//!   image           `podman run -it localhost/seagoat-worker:latest bash`, then rebuild once
//! A full run with the default gate is the last check, not the loop.

mod agent;
mod events;
mod guest;
mod out;

use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::time::{Duration, Instant};

use anyhow::{Context, Result, bail};
use clap::Parser;

#[derive(Parser)]
struct Args {
    /// Git repository to copy into the sandbox.
    #[arg(long)]
    repo: PathBuf,
    /// Commit the run starts from; the patch is relative to it.
    #[arg(long, default_value = "origin/main")]
    base: String,
    /// The brief.
    #[arg(long)]
    task: PathBuf,
    /// OCI image the sandbox boots from, as `msb image ls` shows it (tools/worker/image/build.sh).
    #[arg(long, default_value = "seagoat-worker:latest")]
    image: String,
    /// Receives patch, run.json, transcript.jsonl and events.jsonl.
    #[arg(long)]
    out: PathBuf,
    /// An OpenAI-style chat-completions endpoint (run.py reads it from its config file).
    #[arg(long)]
    api_url: String,
    #[arg(long)]
    model: String,
    /// A JSON object merged into every request body, for gateway-specific fields.
    #[arg(long, default_value = "{}")]
    extra_body: String,
    /// `git add -A` first: pre-commit only checks files git knows about.
    #[arg(long, default_value = "git add -A && bash tools/worker/verify.sh")]
    verify_cmd: String,
    #[arg(long, default_value_t = 50)]
    max_turns: usize,
    #[arg(long, default_value_t = 8192)]
    max_tokens: u32,
    #[arg(long, default_value_t = 2)]
    retry_cap: usize,
    /// Seconds for the whole run, verify passes included.
    #[arg(long, default_value_t = 5400)]
    budget: u64,
    #[arg(long, default_value_t = 4)]
    cpus: u8,
    #[arg(long, default_value_t = 8192)]
    memory_mib: u32,
    /// For orchestrating agents: JSON lines on stdout instead of the table, each turn carrying
    /// only these fields (comma-separated), plus one line per attempt and a final `done`.
    #[arg(long, value_delimiter = ',', num_args = 1.., value_name = "FIELDS")]
    json: Option<Vec<out::Field>>,
}

// Exit codes: 0 green, 1 red, 2 fatal (key, credit), 3 out of time, 4 sandbox or repo setup.
pub const EXIT_RED: u8 = 1;
pub const EXIT_FATAL: u8 = 2;
pub const EXIT_TIMEOUT: u8 = 3;
pub const EXIT_SETUP: u8 = 4;

fn main() -> ExitCode {
    // DECISION: the runtime lives in a private MSB_HOME by default, never ~/.microsandbox, so
    // the worker's pinned SDK cannot change the msb that anything else on the host runs. The
    // image is loaded into that home by tools/worker/image/build.sh.
    if std::env::var_os("MSB_HOME").is_none() {
        let home = std::env::home_dir().expect("a home directory");
        // SAFETY: no other thread exists yet; the tokio runtime starts below.
        unsafe { std::env::set_var("MSB_HOME", home.join(".cache/seagoat-worker/msb")) };
    }
    // The key leaves the environment before anything starts, so git and tar never inherit it.
    let key = std::env::var("SEAGOAT_WORKER_API_KEY");
    // SAFETY: as above, no other thread exists yet.
    unsafe { std::env::remove_var("SEAGOAT_WORKER_API_KEY") };
    let args = Args::parse();
    let rt = tokio::runtime::Runtime::new().expect("tokio runtime");
    match rt.block_on(run(args, key)) {
        Ok(code) => ExitCode::from(code),
        Err(e) => {
            eprintln!("setup failed: {e:#}");
            ExitCode::from(EXIT_SETUP)
        }
    }
}

async fn run(args: Args, key: Result<String, std::env::VarError>) -> Result<u8> {
    let key = key.context("SEAGOAT_WORKER_API_KEY is not set")?;
    let extra_body: serde_json::Map<String, serde_json::Value> =
        serde_json::from_str(&args.extra_body).context("--extra-body is not a JSON object")?;
    let task = std::fs::read_to_string(&args.task).context("reading --task")?;
    std::fs::create_dir_all(&args.out)?;
    let start = Instant::now();
    let deadline = start + Duration::from_secs(args.budget);

    let ev = events::Events::new(args.out.join("events.jsonl"));
    let sigs = signals();
    let span = ev.begin("setup", "clone");
    let (base, tarball) = repo_tarball(&args.repo, &args.base, &args.out.join("clone"))?;
    ev.end(span, serde_json::json!({"tarball_bytes": tarball.len()}));
    let span = ev.begin("setup", "boot");
    let g = guest::Guest::boot(&args.image, args.cpus, args.memory_mib).await?;
    ev.end(
        span,
        serde_json::json!({"cpus": args.cpus, "memory_mib": args.memory_mib}),
    );
    // Whatever happens below, the sandbox goes away; a leaked VM is the expensive failure.
    // That includes Ctrl-C and SIGTERM (a caller may wrap runs in timeout(1)): the work
    // future is dropped at its next await and the guest is removed before exiting.
    let work = async {
        let span = ev.begin("setup", "put_repo");
        g.put_repo(tarball).await?;
        ev.end(span, serde_json::json!({}));
        let cfg = agent::Config {
            key,
            api_url: args.api_url.clone(),
            model: args.model.clone(),
            extra_body,
            verify_cmd: args.verify_cmd.clone(),
            base: base.clone(),
            max_turns: args.max_turns,
            max_tokens: args.max_tokens,
            retry_cap: args.retry_cap,
            start,
            deadline,
            transcript: args.out.join("transcript.jsonl"),
            events: ev.clone(),
            mode: args.json.clone().map_or(out::Mode::Table, out::Mode::Json),
        };
        let report = agent::run(&g, &cfg, &task).await;
        // A dead guest has no patch to give; the report still says why.
        let span = ev.begin("finish", "patch");
        let patch = g.patch(&base).await;
        ev.end(
            span,
            serde_json::json!({"patch_bytes": patch.as_ref().ok().map(String::len)}),
        );
        match patch {
            Ok(p) => std::fs::write(args.out.join("patch"), p)?,
            Err(e) => eprintln!("no patch: {e:#}"),
        }
        Ok::<_, anyhow::Error>(report)
    };
    let result = tokio::select! {
        r = work => r,
        sig = sigs => {
            eprintln!("{sig}: removing the sandbox");
            g.remove().await;
            return Ok(if sig == "SIGINT" { 130 } else { 143 });
        }
    };
    let span = ev.begin("finish", "remove");
    g.remove().await;
    ev.end(span, serde_json::json!({}));
    let report = result?;
    std::fs::write(
        args.out.join("run.json"),
        serde_json::to_string_pretty(&report.json())?,
    )?;
    if args.json.is_some() {
        out::Mode::Json(vec![]).done(report.status(), report.exit_code());
    }
    Ok(report.exit_code())
}

/// Resolves on the first Ctrl-C (or SIGTERM on Unix) and names it. The Unix handlers are
/// installed when this is called, not when the future is first polled, so a signal that lands
/// during boot is held until the guest exists and can be removed.
fn signals() -> impl Future<Output = &'static str> {
    #[cfg(unix)]
    {
        use tokio::signal::unix::{SignalKind, signal};
        let mut int = signal(SignalKind::interrupt()).expect("SIGINT handler");
        let mut term = signal(SignalKind::terminate()).expect("SIGTERM handler");
        async move {
            tokio::select! {
                _ = int.recv() => "SIGINT",
                _ = term.recv() => "SIGTERM",
            }
        }
    }
    #[cfg(not(unix))]
    async {
        let _ = tokio::signal::ctrl_c().await;
        "SIGINT"
    }
}

/// A fresh clone at `base`, tarred with its .git so the guest can diff and commit.
/// DECISION: copy in as one tarball through `fs().write`, because `Sandbox::restore` takes no
/// bind mounts (RestoreBuilder clears them).
/// `tmp` is under the run's own output folder, not a guessable name in a shared /tmp.
fn repo_tarball(repo: &Path, base: &str, tmp: &Path) -> Result<(String, Vec<u8>)> {
    let clone = tmp.join("repo");
    let _ = std::fs::remove_dir_all(tmp);
    let git = |args: &[&str]| -> Result<String> {
        let o = Command::new("git").args(args).output()?;
        if !o.status.success() {
            bail!(
                "git {}: {}",
                args.join(" "),
                String::from_utf8_lossy(&o.stderr)
            );
        }
        Ok(String::from_utf8_lossy(&o.stdout).trim().to_string())
    };
    let clone_s = clone.to_str().context("non-UTF-8 temp path")?;
    git(&[
        "clone",
        "--quiet",
        "--no-hardlinks",
        repo.to_str().context("non-UTF-8 repo path")?,
        clone_s,
    ])?;
    // The clone's origin is the local checkout, so origin/main there is the checkout's main.
    git(&["-C", clone_s, "checkout", "--quiet", "--detach", base])?;
    let sha = git(&["-C", clone_s, "rev-parse", "HEAD"])?;
    // DECISION: the guest gets the base commit and its history, nothing else. A clone carries
    // every local branch, unpushed work included, and the guest can reach the internet.
    git(&["-C", clone_s, "remote", "remove", "origin"])?;
    let refs = git(&["-C", clone_s, "for-each-ref", "--format=%(refname)"])?;
    for r in refs.lines() {
        git(&["-C", clone_s, "update-ref", "-d", r])?;
    }
    git(&["-C", clone_s, "reflog", "expire", "--expire=now", "--all"])?;
    git(&["-C", clone_s, "gc", "--quiet", "--prune=now"])?;
    let tar = Command::new("tar")
        .args(["-czf", "-", "-C", clone_s, "."])
        .output()?;
    std::fs::remove_dir_all(tmp)?;
    if !tar.status.success() {
        bail!("tar: {}", String::from_utf8_lossy(&tar.stderr));
    }
    Ok((sha, tar.stdout))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_tarball_holds_the_base_and_its_history_only() {
        let dir = std::env::temp_dir().join(format!("worker-tarball-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        let repo = dir.join("repo");
        std::fs::create_dir_all(&repo).unwrap();
        let sh = |cmd: &str| {
            let o = Command::new("sh")
                .args(["-c", cmd])
                .current_dir(&repo)
                .output()
                .unwrap();
            assert!(
                o.status.success(),
                "{cmd}: {}",
                String::from_utf8_lossy(&o.stderr)
            );
            String::from_utf8_lossy(&o.stdout).trim().to_string()
        };
        let c = "git -c user.name=t -c user.email=t@t commit -q --allow-empty -m";
        sh(&format!("git init -q -b main && {c} one && {c} two"));
        sh(&format!(
            "git checkout -q -b private && {c} secret && git tag t1 && git checkout -q main"
        ));
        let base = sh("git rev-parse main");

        let (sha, tarball) = repo_tarball(&repo, "main", &dir.join("tmp")).unwrap();
        assert_eq!(sha, base);
        let out = dir.join("out");
        std::fs::create_dir_all(&out).unwrap();
        std::fs::write(dir.join("t.tgz"), tarball).unwrap();
        sh(&format!("tar -xzf {0}/t.tgz -C {0}/out", dir.display()));
        let git = |cmd: &str| {
            let o = Command::new("sh")
                .args(["-c", cmd])
                .current_dir(&out)
                .output()
                .unwrap();
            String::from_utf8_lossy(&o.stdout).trim().to_string()
        };
        assert_eq!(git("git rev-parse HEAD"), base);
        assert_eq!(git("git log --format=%s"), "two\none");
        assert_eq!(git("git for-each-ref"), "");
        assert_eq!(git("git remote"), "");
        assert_eq!(
            git("git log --all --reflog --format=%s | grep -c secret"),
            "0"
        );
        // Two commits and the empty tree they share; the pruned branch's commit would be a fourth.
        assert_eq!(
            git("git count-objects -v | grep -E '^(count|in-pack):' | tr -d ' '"),
            "count:0\nin-pack:3"
        );
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
