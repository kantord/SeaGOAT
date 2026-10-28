//! TERM: guest -- the booted sandbox one run works in, with the repo at /repo. Every tool call
//! and verify pass is a command or file operation on it. Avoid: VM, container, box.

use std::time::Duration;

use anyhow::{Context, Result, bail};
use microsandbox::setup::{InstallOptions, InstallSource, ensure_runtime};
use microsandbox::{MicrosandboxError, Sandbox};

pub const REPO: &str = "/repo";
// Sparse on the host. The image's own layers are read-only; a run writes its build output here.
// A model can fill it, and it lives on the host's disk, so it is sized to what a run needs.
const ROOT_DISK_MIB: u32 = 30 * 1024;

// rustup and uv live in ~/.cargo/bin. The cargo target and the virtualenv are outside /repo,
// which every run replaces, so what the image built for them stays (tools/worker/image).
// put_repo links /repo/.venv to the virtualenv, because pyright only looks there.
const ENV: &str = "export PATH=/root/.cargo/bin:$PATH CARGO_TARGET_DIR=/cache/target \
    UV_PROJECT_ENVIRONMENT=/cache/venv;";

pub struct Guest {
    sb: Sandbox,
    name: String,
}

#[derive(Clone, Copy, Default)]
pub struct Lines {
    pub added: u64,
    pub deleted: u64,
}

/// A finished command. `code` is None when it hit its timeout.
pub struct Output {
    pub code: Option<i32>,
    pub text: String,
}

impl Guest {
    /// A fresh sandbox from the OCI image `image` (loaded by image/build.sh); it is the run's
    /// throw-away child: its writes go to its own root disk and `remove` deletes it.
    pub async fn boot(image: &str, cpus: u8, memory_mib: u32) -> Result<Self> {
        let config = microsandbox::config::config()?;
        ensure_runtime(
            &config,
            InstallOptions {
                source: InstallSource::EmbeddedArchive,
                verify: true,
                ..Default::default()
            },
        )
        .await
        .context("installing the embedded msb runtime")?;
        let name = format!("seagoat-worker-{}", std::process::id());
        let sb = Sandbox::builder(&name)
            .image_with(|i| i.oci(image).root_disk(ROOT_DISK_MIB))
            .cpus(cpus)
            .memory(memory_mib)
            .create()
            .await
            .with_context(|| format!("creating a sandbox from image {image}"))?;
        Ok(Self { sb, name })
    }

    // DECISION: no mtime stamping against the image's build. The fresh tarball makes
    // seagoat-native rebuild once per run; its dependencies stay built in /cache/target, so that
    // takes seconds.
    pub async fn put_repo(&self, tarball: Vec<u8>) -> Result<()> {
        self.sb.fs().write("/root/repo.tgz", tarball).await?;
        let o = self
            .sh(
                "rm -rf /repo && mkdir /repo \
                 && tar --no-same-owner -xzf /root/repo.tgz -C /repo && rm /root/repo.tgz \
                 && ln -s /cache/venv /repo/.venv",
                Duration::from_secs(120),
            )
            .await?;
        if o.code != Some(0) {
            bail!("unpacking the repo: {}", o.text);
        }
        Ok(())
    }

    /// stdout and stderr interleaved as the model would see them in a terminal.
    /// Megabytes of output come back whole, unlike an earlier run_bash, which read its
    /// pipe only after exit and hung on >64 KB; tools_against_a_real_guest holds this.
    pub async fn sh(&self, script: &str, timeout: Duration) -> Result<Output> {
        let script = format!("{ENV} cd {REPO} 2>/dev/null; {{ {script}\n}} 2>&1");
        match self.sb.shell_with(script, |e| e.timeout(timeout)).await {
            Ok(o) => Ok(Output {
                code: Some(o.status().code),
                text: String::from_utf8_lossy(o.stdout_bytes()).into_owned(),
            }),
            Err(MicrosandboxError::ExecTimeout(_)) => Ok(Output {
                code: None,
                text: String::new(),
            }),
            Err(e) => Err(e.into()),
        }
    }

    /// Snapshots the working tree as a git tree object and counts lines added and deleted since
    /// `prev` (a tree from the last call) and since `base`, so commits the model makes still
    /// count. A private index file keeps the model's own `git status` untouched.
    /// Returns (tree, since prev, since base).
    pub async fn diff_stat(&self, prev: &str, base: &str) -> Result<(String, Lines, Lines)> {
        let o = self
            .sh(
                &format!(
                    "export GIT_INDEX_FILE=/tmp/.worker-index; cp .git/index $GIT_INDEX_FILE; \
                 git add -A >/dev/null && t=$(git write-tree) && echo $t && \
                 for from in {prev} {base}; do \
                   git diff --numstat $from $t | awk '{{a+=$1; d+=$2}} END {{print a+0, d+0}}'; \
                 done"
                ),
                Duration::from_secs(60),
            )
            .await?;
        let l: Vec<&str> = o.text.lines().collect();
        let parse = |line: &str| -> Option<Lines> {
            let (a, d) = line.split_once(' ')?;
            Some(Lines {
                added: a.parse().ok()?,
                deleted: d.parse().ok()?,
            })
        };
        match (o.code, l.as_slice()) {
            (Some(0), [tree, turn, total]) if tree.len() == 40 => {
                let lines = parse(turn)
                    .zip(parse(total))
                    .context("bad diff_stat counts")?;
                Ok((tree.to_string(), lines.0, lines.1))
            }
            _ => bail!("diff_stat: {}", o.text),
        }
    }

    /// The guest's CPU counters, for an event's guest_cpu_busy; None if they cannot be read.
    pub async fn cpu(&self) -> Option<crate::events::Cpu> {
        let o = self
            .sh("head -1 /proc/stat", Duration::from_secs(10))
            .await
            .ok()?;
        crate::events::Cpu::parse(&o.text)
    }

    pub async fn tree_of(&self, rev: &str) -> Result<String> {
        Ok(self
            .sh(
                &format!("git rev-parse {rev}^{{tree}}"),
                Duration::from_secs(30),
            )
            .await?
            .text
            .trim()
            .to_string())
    }

    /// Everything the run changed since `base`, committed or not, as one diff for `git apply`.
    /// No renames, so every path the patch touches is named plainly (run.py checks them).
    /// stderr goes to /dev/null inside the command, so `sh`'s 2>&1 cannot mix it into the diff.
    pub async fn patch(&self, base: &str) -> Result<String> {
        let o = self
            .sh(
                &format!("git add -A 2>/dev/null && git diff --cached --binary --no-renames {base} 2>/dev/null"),
                Duration::from_secs(60),
            )
            .await?;
        if o.code != Some(0) {
            bail!("git diff exited {:?}", o.code);
        }
        Ok(o.text)
    }

    /// Whether the tree differs from `base`, in the working tree or in commits the model made.
    /// A private index, as in diff_stat, keeps the model's own `git status` untouched.
    pub async fn changed_since(&self, base: &str) -> Result<bool> {
        let o = self
            .sh(
                &format!(
                    "export GIT_INDEX_FILE=/tmp/.worker-index; cp .git/index $GIT_INDEX_FILE; \
                     git add -A >/dev/null 2>&1 && git diff --cached --quiet {base}"
                ),
                Duration::from_secs(60),
            )
            .await?;
        match o.code {
            Some(0) => Ok(false),
            Some(1) => Ok(true),
            c => bail!("git diff --quiet exited {c:?}: {}", o.text),
        }
    }

    pub async fn remove(self) {
        if let Err(e) = self.sb.stop().await {
            eprintln!("stopping {}: {e}", self.name);
        }
        if let Err(e) = Sandbox::remove(&self.name).await {
            eprintln!("removing {} (left for manual cleanup): {e}", self.name);
        }
    }
}
