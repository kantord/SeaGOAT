//! The model loop.
//!
//! PROVISIONAL (owner, 2026-10-21: "first try how it does without replace"): bash is the only
//! tool. An earlier version had five (ranged read_file, grep, exact-once replace, write_file,
//! run_bash); the evidence for them was one task that got stuck six times before ranged reads
//! and replace, and went green first try after.
//! RISK: multi-line exact edits in large files through shell quoting. Kill: runs that go red on
//! edits rather than on the task. Cost: small, bringing back a replace tool.

use std::io::Write;
use std::path::PathBuf;
use std::time::{Duration, Instant};

use anyhow::{Result, anyhow};
use serde_json::{Map, Value, json};

use crate::events::{Cpu, Events};
use crate::guest::Guest;

const MAX_TOOL_OUTPUT: usize = 8000;
const MAX_CONVERSATION_CHARS: usize = 200_000;
const BASH_TIMEOUT: Duration = Duration::from_secs(300);
/// A model's command blocks until it ends, up to this (and the run's deadline), so the model
/// never polls a background job. *Because* a 5-minute cap made an earlier run spend six turns
/// on `sleep N && tail log` around a cold verify (2026-10-22).
const COMMAND_TIMEOUT: Duration = Duration::from_secs(1800);
const VERIFY_TIMEOUT: Duration = Duration::from_secs(1800);
// One HTTP 500 used to end a whole attempt (2026-10-19).
const API_RETRY_WAITS: [u64; 2] = [5, 20];

const SYSTEM_PROMPT: &str = "You are an autonomous coding agent working in /repo (a git checkout).
Your one tool is run_bash: a shell command in /repo, returning its exit code and
output. Use it for reading, searching, editing, building, testing and git.
Each command blocks until it finishes, up to 30 minutes (then it is killed and reported as
exit timeout). Run long builds and tests in the foreground; never background a command to poll
it with sleep. Never start a server or anything else that runs until it is stopped.
Read large files in ranges, and edit only the lines you mean to change rather than rewriting
a whole file.
The harness runs the verification command itself when you stop, and gives you its output
back if it fails. Do not run that whole gate yourself; run only the tests of what you changed:
`uv run pytest tests/test_<name>.py -k <test>` for Python (`uv run` rebuilds the Rust extension
in src/ when it changed), `cargo test <name>` for Rust.

When the task is done and the tests of what you changed pass, reply with no tool calls and a
message starting with \"DONE:\" that says what you changed and which tests you ran.
";

pub struct Config {
    pub key: String,
    /// An OpenAI-style chat-completions endpoint.
    pub api_url: String,
    pub model: String,
    /// Merged into every request body as-is: gateway-specific fields live in the caller's
    /// config, not here.
    pub extra_body: Map<String, Value>,
    pub verify_cmd: String,
    /// The commit the run started from: "changed" means differs from it.
    pub base: String,
    pub max_turns: usize,
    pub max_tokens: u32,
    pub retry_cap: usize,
    pub start: Instant,
    pub deadline: Instant,
    pub transcript: PathBuf,
    pub events: Events,
    pub mode: crate::out::Mode,
}

#[derive(Clone, Copy, PartialEq)]
pub enum Status {
    Green,
    Red,
    Fatal,
    Timeout,
    /// The guest broke under the model (2026-10-21: the host filled up, the guest's disk went
    /// read-only and the model spent its last ten turns diagnosing it). Not the model's fault,
    /// so it is reported like a failed boot.
    SetupFailed,
}

pub struct Report {
    pub status: Status,
    pub turns: usize,
    pub cost_usd: f64,
    pub reply_tokens: u64,
    /// The working tree as of the last reported turn, for the next turn's diff.
    tree: String,
    pub attempts: Vec<Value>,
    pub error: Option<String>,
}

impl Report {
    pub fn exit_code(&self) -> u8 {
        match self.status {
            Status::Green => 0,
            Status::Red => crate::EXIT_RED,
            Status::Fatal => crate::EXIT_FATAL,
            Status::Timeout => crate::EXIT_TIMEOUT,
            Status::SetupFailed => crate::EXIT_SETUP,
        }
    }

    pub fn status(&self) -> &'static str {
        match self.status {
            Status::Green => "GREEN",
            Status::Red => "RED",
            Status::Fatal => "FATAL",
            Status::Timeout => "TIMEOUT",
            Status::SetupFailed => "SETUP_FAILED",
        }
    }

    pub fn json(&self) -> Value {
        json!({"status": self.status(), "turns": self.turns, "cost_usd": self.cost_usd,
               "reply_tokens": self.reply_tokens, "attempts": self.attempts, "error": self.error})
    }
}

/// Who ended an attempt. An attempt is up to max_turns model calls; the harness verifies after
/// each one and feeds the failure tail into the next.
enum Ending {
    ModelDone,
    MaxTurns,
    ApiError(String),
}

pub async fn run(g: &Guest, cfg: &Config, task: &str) -> Report {
    let mut r = Report {
        status: Status::Red,
        turns: 0,
        cost_usd: 0.0,
        reply_tokens: 0,
        tree: String::new(),
        attempts: vec![],
        error: None,
    };
    let mut messages = vec![
        json!({"role": "system", "content": SYSTEM_PROMPT}),
        json!({"role": "user", "content": format!("TASK:\n{task}\n\nVerify with: `{}`", cfg.verify_cmd)}),
    ];
    record(cfg, &messages);
    for attempt in 1..=cfg.retry_cap + 1 {
        let ending = match turns(g, cfg, &mut messages, &mut r).await {
            Ok(e) => e,
            Err(Stop::Fatal(e)) => {
                r.status = Status::Fatal;
                r.error = Some(e);
                return r;
            }
            Err(Stop::OutOfTime) => {
                r.status = Status::Timeout;
                return r;
            }
            Err(Stop::GuestDead(e)) => {
                r.status = Status::SetupFailed;
                r.error = Some(e);
                return r;
            }
        };
        let remaining = cfg.deadline.saturating_duration_since(Instant::now());
        if remaining < Duration::from_secs(60) {
            r.status = Status::Timeout;
            return r;
        }
        // An untouched tree passing verify says nothing about the task, so it counts RED
        // without a verify. Compared with the base, not HEAD: committed work is still work.
        let span = cfg.events.begin("harness", "changed_since");
        let changed = g.changed_since(&cfg.base).await;
        cfg.events
            .end(span, json!({"changed": changed.as_ref().ok()}));
        let v = if let Ok(false) = changed {
            Ok(crate::guest::Output {
                code: Some(1),
                text: "(no changes, no verify run)".into(),
            })
        } else {
            let guest0 = g.cpu().await;
            let span = cfg.events.begin("verify", format!("attempt {attempt}"));
            let v = g.sh(&cfg.verify_cmd, remaining.min(VERIFY_TIMEOUT)).await;
            let guest_cpu_busy = Cpu::busy_between(guest0, g.cpu().await);
            let exit = v.as_ref().ok().map(|o| o.code);
            cfg.events.end(
                span,
                json!({"exit": exit, "guest_cpu_busy": guest_cpu_busy, "cmd": cfg.verify_cmd}),
            );
            v
        };
        let (ok, out) = match v {
            Ok(o) if o.code.is_none() => {
                r.status = Status::Timeout;
                return r;
            }
            Ok(o) => (o.code == Some(0), tail(&o.text, 6000)),
            // The exec itself failing means the guest is gone, not that the code is wrong.
            Err(e) => {
                r.status = Status::SetupFailed;
                r.error = Some(format!("verify could not run: {e:#}"));
                return r;
            }
        };
        if !ok && let Some(e) = dead(g, &out).await {
            r.status = Status::SetupFailed;
            r.error = Some(e);
            return r;
        }
        let ending = match ending {
            Ending::ModelDone => "model_done".to_string(),
            Ending::MaxTurns => "max_turns".to_string(),
            Ending::ApiError(e) => format!("api_error: {e}"),
        };
        cfg.mode.attempt(attempt, &ending, ok);
        r.attempts.push(
            json!({"n": attempt, "ending": ending, "verify": if ok { "GREEN" } else { "RED" },
                                "verify_tail": tail(&out, 600)}),
        );
        if ok {
            r.status = Status::Green;
            return r;
        }
        let m = json!({"role": "user", "content": format!(
            "The verification command `{}` failed. Fix the SPECIFIC failures below -- do not start \
             over or redo work that already passed. Run the tests of what you fix, then stop; the \
             harness runs the whole gate again.\n\n{out}",
            cfg.verify_cmd)});
        record(cfg, std::slice::from_ref(&m));
        messages.push(m);
    }
    r
}

enum Stop {
    Fatal(String),
    OutOfTime,
    GuestDead(String),
}

async fn turns(
    g: &Guest,
    cfg: &Config,
    messages: &mut Vec<Value>,
    r: &mut Report,
) -> Result<Ending, Stop> {
    for turn in 1..=cfg.max_turns {
        let turn_start = Instant::now();
        if Instant::now() > cfg.deadline {
            return Err(Stop::OutOfTime);
        }
        cfg.mode.header();
        trim(messages);
        let resp = match call(cfg, messages, turn).await {
            Ok(v) => v,
            Err(Call::Fatal(e)) => return Err(Stop::Fatal(e)),
            Err(Call::Failed(e)) => return Ok(Ending::ApiError(e)),
        };
        let time_llm = turn_start.elapsed();
        r.turns += 1;
        let usage = &resp["usage"];
        let cost = usage["cost"].as_f64().unwrap_or(0.0);
        r.cost_usd += cost;
        let reply = usage["completion_tokens"].as_u64().unwrap_or(0);
        r.reply_tokens += reply;
        let row = crate::out::TurnRow {
            turn,
            context: usage["prompt_tokens"].as_u64().unwrap_or(0),
            reply,
            reply_total: r.reply_tokens,
            cost,
            cost_total: r.cost_usd,
            time_llm,
            time_tools: Duration::ZERO,
            time_total: Duration::ZERO,
            steps: 0,
            diff: Default::default(),
            diff_total: Default::default(),
        };
        let msg = resp["choices"][0]["message"].clone();
        if !msg.is_object() {
            return Ok(Ending::ApiError(format!(
                "no message in reply: {}",
                tail(&resp.to_string(), 300)
            )));
        }
        let calls = msg["tool_calls"].as_array().cloned().unwrap_or_default();
        let n_steps = calls.len();
        record(cfg, std::slice::from_ref(&msg));
        messages.push(msg);
        if calls.is_empty() {
            finish_turn(g, cfg, r, row, 0, turn_start).await;
            return Ok(Ending::ModelDone);
        }
        for c in calls {
            let name = c["function"]["name"].as_str().unwrap_or("");
            let args: Value = c["function"]["arguments"]
                .as_str()
                .and_then(|s| serde_json::from_str(s).ok())
                .unwrap_or(json!({}));
            let (tool, summary) = step_summary(name, &args);
            cfg.mode.step(turn, tool, &summary);
            let limit = cfg
                .deadline
                .saturating_duration_since(Instant::now())
                .min(COMMAND_TIMEOUT);
            let guest0 = g.cpu().await;
            let span = cfg.events.begin("tool", tool);
            let out = run_tool(g, name, &args, limit)
                .await
                .unwrap_or_else(|e| format!("tool error: {e:#}"));
            let guest_cpu_busy = Cpu::busy_between(guest0, g.cpu().await);
            cfg.events.end(
                span,
                json!({"turn": turn, "cmd": summary.chars().take(300).collect::<String>(),
                       "exit": exit_of(&out), "output_bytes": out.len(),
                       "guest_cpu_busy": guest_cpu_busy}),
            );
            if let Some(e) = dead(g, &out).await {
                return Err(Stop::GuestDead(e));
            }
            let m = json!({"role": "tool", "tool_call_id": c["id"], "content": tail_cut(&out)});
            record(cfg, std::slice::from_ref(&m));
            messages.push(m);
        }
        finish_turn(g, cfg, r, row, n_steps, turn_start).await;
    }
    Ok(Ending::MaxTurns)
}

/// Reports a turn once its steps are done, so its time and diff include them.
async fn finish_turn(
    g: &Guest,
    cfg: &Config,
    r: &mut Report,
    mut row: crate::out::TurnRow,
    steps: usize,
    turn_start: Instant,
) {
    row.steps = steps;
    row.time_tools = turn_start.elapsed() - row.time_llm;
    row.time_total = cfg.start.elapsed();
    let span = cfg.events.begin("harness", "diff_stat");
    if r.tree.is_empty() {
        r.tree = g.tree_of(&cfg.base).await.unwrap_or_default();
    }
    // A failed count only blanks the column; the run does not depend on it.
    if let Ok((tree, diff, total)) = g.diff_stat(&r.tree, &cfg.base).await {
        (r.tree, row.diff, row.diff_total) = (tree, diff, total);
    }
    cfg.events.end(span, json!({"turn": row.turn}));
    cfg.mode.turn(&row);
}

/// The short tool name and its arguments as a person would scan them.
fn step_summary(name: &str, args: &Value) -> (&'static str, String) {
    match name {
        "run_bash" => ("bash", args["command"].as_str().unwrap_or("").to_string()),
        _ => ("?", name.to_string()),
    }
}

async fn run_tool(g: &Guest, name: &str, args: &Value, limit: Duration) -> Result<String> {
    if name != "run_bash" {
        return Ok(format!("unknown tool: {name}; the only tool is run_bash"));
    }
    let cmd = args["command"]
        .as_str()
        .ok_or_else(|| anyhow!("missing string argument `command`"))?;
    let o = g.sh(cmd, limit).await?;
    let rc = o.code.map_or("timeout".into(), |c| c.to_string());
    Ok(format!("$ {cmd}\n(exit {rc})\n{}", o.text))
}

enum Call {
    Fatal(String),
    Failed(String),
}

/// SPEC: 5xx, 408, 429, dropped connections and unparseable bodies are retried after 5 s and
/// 20 s; any other 4xx ends the attempt; quota and auth failures end the run as FATAL.
/// Every HTTP request is an event, and so is every wait before a retry.
async fn call(cfg: &Config, messages: &[Value], turn: usize) -> Result<Value, Call> {
    let mut body = json!({
        "model": cfg.model, "messages": messages, "tools": tools(), "tool_choice": "auto",
        // Without it some gateways reserve the model's whole context window and refuse the call
        // on a small balance.
        "max_tokens": cfg.max_tokens,
    });
    if let Some(b) = body.as_object_mut() {
        b.extend(cfg.extra_body.clone());
    }
    let mut last = String::new();
    for wait in API_RETRY_WAITS.iter().map(Some).chain([None]) {
        let (url, key, body) = (cfg.api_url.clone(), cfg.key.clone(), body.clone());
        let span = cfg.events.begin("llm", "request");
        let res = tokio::task::spawn_blocking(move || post(&url, &key, &body))
            .await
            .unwrap_or_else(|e| Err((true, e.to_string())));
        cfg.events.end(span, request_fields(turn, &res));
        match res {
            Ok(v) => return Ok(v),
            Err((_, e)) if is_fatal(&e) => return Err(Call::Fatal(e)),
            Err((false, e)) => return Err(Call::Failed(e)),
            Err((true, e)) => last = e,
        }
        if let Some(w) = wait {
            eprintln!(
                "  transient API failure ({}), retrying in {w}s",
                tail(&last, 200)
            );
            let span = cfg.events.begin("llm", "retry_wait");
            tokio::time::sleep(Duration::from_secs(*w)).await;
            cfg.events.end(span, json!({"turn": turn}));
        }
    }
    Err(Call::Failed(last))
}

/// What a request event records: the reply's size, tokens and cost, or the error.
fn request_fields(turn: usize, res: &Result<Value, (bool, String)>) -> Value {
    match res {
        Ok(v) => {
            let u = &v["usage"];
            let msg = &v["choices"][0]["message"];
            json!({"turn": turn, "ok": true,
                   "prompt_tokens": u["prompt_tokens"], "completion_tokens": u["completion_tokens"],
                   "cost_usd": u["cost"], "tool_calls": msg["tool_calls"].as_array().map(Vec::len),
                   "finish_reason": v["choices"][0]["finish_reason"], "provider": v["provider"]})
        }
        Err((retryable, e)) => {
            json!({"turn": turn, "ok": false, "retryable": retryable, "error": tail(e, 300)})
        }
    }
}

/// The exit code run_tool put on its output's second line, as the model saw it.
fn exit_of(out: &str) -> Value {
    out.lines()
        .nth(1)
        .and_then(|l| l.strip_prefix("(exit ")?.strip_suffix(')'))
        .map_or(Value::Null, |c| {
            c.parse::<i64>().map_or(c.into(), Value::from)
        })
}

/// Err((retryable, message)).
fn post(url: &str, key: &str, body: &Value) -> Result<Value, (bool, String)> {
    let agent: ureq::Agent = ureq::Agent::config_builder()
        .http_status_as_error(false)
        .timeout_global(Some(Duration::from_secs(180)))
        .build()
        .into();
    let mut resp = agent
        .post(url)
        .header("Authorization", &format!("Bearer {key}"))
        .send_json(body)
        .map_err(|e| (true, e.to_string()))?;
    let code = resp.status().as_u16();
    let text = resp
        .body_mut()
        .with_config()
        .limit(64 << 20)
        .read_to_string()
        .map_err(|e| (true, e.to_string()))?;
    if code != 200 {
        return Err((
            code >= 500 || code == 408 || code == 429,
            format!("HTTP {code}: {}", tail(&text, 500)),
        ));
    }
    let v: Value =
        serde_json::from_str(&text).map_err(|e| (true, format!("non-JSON reply: {e}")))?;
    // Some gateways report upstream failures as HTTP 200 with an error body.
    if let Some(err) = v.get("error") {
        return Err((true, format!("error body on HTTP 200: {err}")));
    }
    if v["choices"].as_array().is_none_or(|c| c.is_empty()) {
        return Err((true, format!("reply without choices: {}", tail(&text, 300))));
    }
    Ok(v)
}

/// EIO in a tool's output is what a dying guest disk looks like from inside, but a model can
/// also just print the phrase (grep for it, cat a log), so a write to /tmp decides.
async fn dead(g: &Guest, out: &str) -> Option<String> {
    if !out.contains("Input/output error") {
        return None;
    }
    let probe = g
        .sh(
            "echo x > /tmp/.worker-probe && rm /tmp/.worker-probe",
            BASH_TIMEOUT,
        )
        .await;
    match probe {
        Ok(o) if o.code == Some(0) => None,
        Ok(o) => Some(format!("guest cannot write /tmp: {}", tail(&o.text, 300))),
        Err(e) => Some(format!("guest stopped answering: {e:#}")),
    }
}

fn is_fatal(e: &str) -> bool {
    // A bad key can come back as a bare 401 that none of the phrases below match; 402 is out
    // of credit.
    if ["HTTP 401", "HTTP 402", "HTTP 403"]
        .iter()
        .any(|c| e.starts_with(c))
    {
        return true;
    }
    let e = e.to_lowercase();
    [
        "insufficient_quota",
        "insufficient credit",
        "requires more credits",
        "invalid_api_key",
        "api key expired",
        "no auth credentials found",
    ]
    .iter()
    .any(|p| e.contains(p))
}

fn tools() -> Value {
    json!([{"type": "function", "function": {
        "name": "run_bash",
        "description": "Run a shell command in /repo and get back its exit code and stdout+stderr.",
        "parameters": {"type": "object", "properties": {"command": {"type": "string"}},
                       "required": ["command"]}}}])
}

/// Drops the oldest whole turns (an assistant message with every tool reply answering it),
/// never the system prompt or the task, so no tool reply is left without its call.
fn trim(messages: &mut Vec<Value>) {
    let size = |m: &[Value]| m.iter().map(|v| v.to_string().len()).sum::<usize>();
    while size(messages) > MAX_CONVERSATION_CHARS && messages.len() > 3 {
        let end = 3 + messages[3..]
            .iter()
            .take_while(|m| m["role"] == "tool")
            .count();
        messages.drain(2..end);
    }
}

fn record(cfg: &Config, msgs: &[Value]) {
    // Watching a run must never be what breaks it.
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open(&cfg.transcript)
    {
        for m in msgs {
            let _ = writeln!(f, "{m}");
        }
    }
}

fn tail_cut(s: &str) -> String {
    if s.len() <= MAX_TOOL_OUTPUT {
        return s.to_string();
    }
    let cut = s.floor_char_boundary(MAX_TOOL_OUTPUT);
    format!(
        "{}\n... [truncated, {} more chars]",
        &s[..cut],
        s.len() - cut
    )
}

fn tail(s: &str, n: usize) -> String {
    s[s.ceil_char_boundary(s.len().saturating_sub(n))..].to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::ensure;

    /// Boots a real guest, so it is opt-in:
    /// WORKER_TEST_IMAGE=seagoat-worker:latest cargo test -- --ignored
    #[tokio::test]
    #[ignore]
    async fn tools_against_a_real_guest() {
        let image = std::env::var("WORKER_TEST_IMAGE").expect("WORKER_TEST_IMAGE");
        let g = Guest::boot(&image, 2, 2048).await.unwrap();
        // ensure!, not assert!, so the guest is removed before the test fails.
        let res = check_tools(&g).await;
        g.remove().await;
        res.unwrap();
    }

    async fn check_tools(g: &Guest) -> Result<()> {
        let bash = |cmd: &str| {
            let args = json!({"command": cmd});
            async move { run_tool(g, "run_bash", &args, BASH_TIMEOUT).await }
        };
        bash(
            "rm -rf /repo && mkdir /repo && cd /repo && git init -q \
              && git -c user.name=t -c user.email=t@t commit -q --allow-empty -m base",
        )
        .await?;
        let base = g.tree_of("HEAD").await?;
        bash("cd /repo && mkdir a && printf 'one\\n2\\n' > a/b.txt").await?;
        let (_, turn, total) = g.diff_stat(&base, "HEAD").await?;
        let counts = (turn.added, turn.deleted, total.added, total.deleted);
        ensure!(counts == (2, 0, 2, 0), "diff counts {counts:?}");
        let staged = g
            .sh("git diff --cached --name-only", BASH_TIMEOUT)
            .await?
            .text;
        ensure!(
            staged.is_empty(),
            "diff_stat touched the real index: {staged}"
        );
        // Committed work is still a change, the counts still see it, and the patch is one
        // plain diff with nothing but git's stdout in it.
        let commit = g.sh("git rev-parse HEAD", BASH_TIMEOUT).await?.text;
        let commit = commit.trim();
        ensure!(
            g.changed_since(commit).await?,
            "untracked file seen as unchanged"
        );
        bash("cd /repo && git add -A && git -c user.name=t -c user.email=t@t commit -qm work")
            .await?;
        ensure!(
            g.changed_since(commit).await?,
            "committed work seen as unchanged"
        );
        ensure!(
            !g.changed_since("HEAD").await?,
            "clean tree seen as changed"
        );
        let (_, _, total) = g.diff_stat(&base, commit).await?;
        ensure!(
            total.added == 2,
            "committed lines not counted: {}",
            total.added
        );
        bash("cd /repo && echo three >> a/b.txt && git -c user.name=t -c user.email=t@t commit -qam more")
            .await?;
        let patch = g.patch(commit).await?;
        ensure!(
            patch.starts_with("diff --git a/a/b.txt b/a/b.txt")
                && patch.matches("diff --git").count() == 1
                && patch.contains("+three"),
            "{patch}"
        );
        let out = run_tool(g, "replace", &json!({}), BASH_TIMEOUT).await?;
        ensure!(out.starts_with("unknown tool"), "{out}");
        // The case an earlier run_bash hung on: far more than a 64 KB pipe buffer.
        let start = Instant::now();
        let out =
            bash("head -c 2000000 /dev/zero | tr '\\0' x; echo; echo err >&2; exit 3").await?;
        ensure!(
            start.elapsed() < Duration::from_secs(30),
            "took {:?}",
            start.elapsed()
        );
        ensure!(
            out.contains("(exit 3)") && out.ends_with("err\n"),
            "{}",
            tail(&out, 200)
        );
        ensure!(out.len() > 2_000_000, "only {} bytes", out.len());
        // A healthy guest that merely prints the phrase is not dead; one that cannot write is.
        ensure!(
            dead(g, "grep hit: Input/output error").await.is_none(),
            "healthy guest called dead"
        );
        g.sh("mount -t tmpfs -o ro tmpfs /tmp", BASH_TIMEOUT)
            .await?;
        ensure!(
            dead(g, "cat: x: Input/output error").await.is_some(),
            "read-only /tmp not caught"
        );
        Ok(())
    }
}
