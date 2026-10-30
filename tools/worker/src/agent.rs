//! Runs a program (program.rs): its messages, the model's turns with its one tool, and the
//! harness's own commands.
//!
//! PROVISIONAL (owner, 2026-10-21: "first try how it does without replace"): bash is the only
//! tool. An earlier version had five (ranged read_file, grep, exact-once replace, write_file,
//! run_bash); the evidence for them was one task that got stuck six times before ranged reads
//! and replace, and went green first try after.
//! RISK: multi-line exact edits in large files through shell quoting. Kill: runs that go red on
//! edits rather than on the task. Cost: small, bringing back a replace tool.

use std::io::Write;
use std::path::PathBuf;
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use anyhow::{Result, anyhow};
use serde_json::{Map, Value, json};

use crate::events::{Cpu, Events};
use crate::guest::Guest;
pub use crate::program::Program;
use crate::program::{Show, Step};

const MAX_TOOL_OUTPUT: usize = 8000;
/// What a passing `show: always` command hands the model: room for the few files a part needs.
const SHOWN_OUTPUT: usize = 40_000;
const MAX_CONVERSATION_CHARS: usize = 200_000;
const BASH_TIMEOUT: Duration = Duration::from_secs(300);
/// A program's command blocks until it ends, up to this, so a cold full gate fits.
/// DECISION (owner, 2026-10-29): time limits only stop commands that would never end. A run
/// ends by counts (an llm step's max_turns, a script's retries), and a command that hits its
/// limit fails like any other, so a script can retry it.
const COMMAND_TIMEOUT: Duration = Duration::from_secs(1800);
/// The model's own commands get less: it runs only focused tests (well under a minute) since the
/// harness runs the gate. *Because* one hung experiment of its own held a run for 25 of its 30
/// minutes (2026-10-29). An earlier 5-minute cap made the model poll a full gate it ran itself
/// (2026-10-22); the rules now tell it not to run the gate.
const MODEL_COMMAND_TIMEOUT: Duration = Duration::from_secs(300);
/// Tells the model why a reply did nothing, instead of taking it for "done".
const CUT_OFF: &str = "Your last reply was cut off at the reply token limit, so nothing in it \
     ran. Make smaller changes per command, e.g. edit a file in several steps instead of \
     writing it whole.";
/// A reply with neither text nor a tool call is not "done" either: 2026-10-30, three replies that
/// spent exactly 4096 reasoning tokens came back empty with finish_reason "stop", and each one
/// ended a pass with nothing written.
const EMPTY: &str = "Your last reply was empty: no text and no command, so nothing ran. \
     Continue the task with your next command, planning one small step at a time. If the task \
     is done, reply with the DONE: message.";
// One HTTP 500 used to end a whole attempt (2026-10-19).
const API_RETRY_WAITS: [u64; 2] = [5, 20];

pub struct Config {
    pub key: String,
    /// An OpenAI-style chat-completions endpoint.
    pub api_url: String,
    pub model: String,
    /// Merged into every request body as-is: gateway-specific fields live in the caller's
    /// config, not here.
    pub extra_body: Map<String, Value>,
    /// Ask the gateway to keep routing to the provider that answered the first request: a
    /// provider's prompt cache only serves requests that reach it (2026-10-29: 75% of prompt
    /// tokens cached with one provider, 56% in a run that switched provider 13 times).
    pub pin_provider: bool,
    /// The provider of the first reply that named one, when pin_provider is on.
    pub pinned: OnceLock<String>,
    /// The commit the run started from; command steps get it as $WORKER_BASE.
    pub base: String,
    pub max_tokens: u32,
    pub start: Instant,
    pub transcript: PathBuf,
    pub events: Events,
    /// Where `once` fragments live; None means once blocks always run and save nothing.
    pub once_dir: Option<PathBuf>,
    pub mode: crate::out::Mode,
}

#[derive(Clone, Copy, PartialEq)]
pub enum Status {
    Green,
    Red,
    Fatal,
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
    /// Every step that ran, in order, with whether it succeeded.
    pub steps: Vec<Value>,
    pub error: Option<String>,
}

impl Report {
    pub fn exit_code(&self) -> u8 {
        match self.status {
            Status::Green => 0,
            Status::Red => crate::EXIT_RED,
            Status::Fatal => crate::EXIT_FATAL,
            Status::SetupFailed => crate::EXIT_SETUP,
        }
    }

    pub fn status(&self) -> &'static str {
        match self.status {
            Status::Green => "GREEN",
            Status::Red => "RED",
            Status::Fatal => "FATAL",
            Status::SetupFailed => "SETUP_FAILED",
        }
    }

    pub fn json(&self) -> Value {
        json!({"status": self.status(), "turns": self.turns, "cost_usd": self.cost_usd,
               "reply_tokens": self.reply_tokens, "steps": self.steps, "error": self.error})
    }
}

/// How an llm step ended.
enum Ending {
    ModelDone,
    MaxTurns,
    ApiError(String),
}

/// The conversation, and how many of its opening messages trimming must keep.
struct Conversation {
    messages: Vec<Value>,
    /// Set when the first llm step starts: everything before it is the program's preamble.
    pinned: Option<usize>,
}

pub async fn run(g: &Guest, cfg: &Config, program: &Program) -> Report {
    let mut r = Report {
        status: Status::Red,
        turns: 0,
        cost_usd: 0.0,
        reply_tokens: 0,
        tree: String::new(),
        steps: vec![],
        error: None,
    };
    let mut conv = Conversation {
        messages: vec![],
        pinned: None,
    };
    r.status = match run_steps(g, cfg, &program.steps, &mut conv, &mut r).await {
        Ok(true) => Status::Green,
        Ok(false) => Status::Red,
        Err(Stop::Fatal(e)) => {
            r.error = Some(e);
            Status::Fatal
        }
        Err(Stop::GuestDead(e)) => {
            r.error = Some(e);
            Status::SetupFailed
        }
    };
    r
}

/// Runs `steps` in order and stops at the first that fails: Ok(false). Err is a failure no
/// retry can fix, and ends the whole run.
async fn run_steps(
    g: &Guest,
    cfg: &Config,
    steps: &[Step],
    conv: &mut Conversation,
    r: &mut Report,
) -> Result<bool, Stop> {
    for step in steps {
        let ok = match step {
            Step::Message { role, text, .. } => {
                say(cfg, conv, role.as_str(), text.clone());
                true
            }
            Step::Llm { name, max_turns } => {
                conv.pinned.get_or_insert(conv.messages.len());
                let ending = turns(g, cfg, conv, r, *max_turns).await?;
                let (ok, detail) = match ending {
                    Ending::ModelDone => (true, "model_done".to_string()),
                    Ending::MaxTurns => (false, "max_turns".to_string()),
                    Ending::ApiError(e) => (false, format!("api_error: {e}")),
                };
                if !ok {
                    say(
                        cfg,
                        conv,
                        "user",
                        format!("`{name}` ended without finishing ({detail})."),
                    );
                }
                outcome(cfg, r, name, ok, json!({"ending": detail}));
                ok
            }
            Step::Command { name, run, show } => command(g, cfg, conv, r, name, run, *show).await?,
            Step::Script {
                name,
                retries,
                steps,
            } => {
                let mut ok = false;
                for pass in 1..=retries + 1 {
                    ok = Box::pin(run_steps(g, cfg, steps, conv, r)).await?;
                    outcome(cfg, r, name, ok, json!({"pass": pass}));
                    if ok {
                        break;
                    }
                }
                ok
            }
            Step::Once {
                name,
                max_age_s,
                steps,
            } => once(g, cfg, conv, r, name, *max_age_s, steps).await?,
        };
        if !ok {
            return Ok(false);
        }
    }
    Ok(true)
}

async fn command(
    g: &Guest,
    cfg: &Config,
    conv: &mut Conversation,
    r: &mut Report,
    name: &str,
    run: &str,
    show: Show,
) -> Result<bool, Stop> {
    let guest0 = g.cpu().await;
    let span = cfg.events.begin("command", name);
    let o = g
        .sh(
            &format!("export WORKER_BASE={};\n{run}", cfg.base),
            COMMAND_TIMEOUT,
        )
        .await;
    let guest_cpu_busy = Cpu::busy_between(guest0, g.cpu().await);
    let exit = o.as_ref().ok().map(|o| o.code);
    cfg.events.end(
        span,
        json!({"exit": exit, "guest_cpu_busy": guest_cpu_busy, "cmd": run}),
    );
    // The exec itself failing means the guest is gone, not that the code is wrong.
    let o = o.map_err(|e| Stop::GuestDead(format!("`{name}` could not run: {e:#}")))?;
    let ok = o.code == Some(0);
    if !ok && let Some(e) = dead(g, &o.text).await {
        return Err(Stop::GuestDead(e));
    }
    let exit = o.code.map_or("timeout".into(), |c| c.to_string());
    let text = match (ok, show) {
        (true, Show::Always) => Some(format!("`{name}`:\n\n{}", head(&o.text, SHOWN_OUTPUT))),
        (true, _) => None,
        (false, Show::Never) => Some(format!("`{name}` failed (exit {exit}).")),
        (false, _) => Some(format!(
            "`{name}` failed (exit {exit}):\n\n{}",
            tail(&o.text, 6000)
        )),
    };
    if let Some(text) = text {
        say(cfg, conv, "user", text);
    }
    outcome(
        cfg,
        r,
        name,
        ok,
        json!({"exit": o.code, "tail": tail(&o.text, 600)}),
    );
    Ok(ok)
}

/// DECISION (owner, 2026-10-29): a once block's fragment is keyed by everything its result
/// depends on: its steps (not its name or max_age_s), the model, the conversation before it and
/// the base commit, so it is only ever replayed where it would come out the same; `max_age_s`
/// additionally bounds how old a replayed fragment may be. Fragments are never updated, so a file's age is
/// the fragment's age. Placed before the brief, a shared fragment also gives every run from the
/// same base an identical prompt prefix, which the provider can serve from its cache.
async fn once(
    g: &Guest,
    cfg: &Config,
    conv: &mut Conversation,
    r: &mut Report,
    name: &str,
    max_age_s: Option<u64>,
    steps: &[Step],
) -> Result<bool, Stop> {
    let key = once_key(steps, &cfg.model, &conv.messages, &cfg.base);
    let file = cfg.once_dir.as_ref().map(|d| d.join(format!("{key}.json")));
    if let Some((messages, age)) = file.as_deref().and_then(|f| read_fragment(f, max_age_s)) {
        let span = cfg.events.begin("once", name);
        let n = messages.len();
        for m in messages {
            record(cfg, std::slice::from_ref(&m));
            conv.messages.push(m);
        }
        let detail = json!({"key": key, "replayed": true, "age_s": age, "messages": n});
        cfg.events.end(span, detail.clone());
        outcome(cfg, r, name, true, detail);
        return Ok(true);
    }
    let start = conv.messages.len();
    let before = tree_state(g, name).await?;
    if !Box::pin(run_steps(g, cfg, steps, conv, r)).await? {
        outcome(cfg, r, name, false, json!({"key": key, "replayed": false}));
        return Ok(false);
    }
    // A replay restores messages, not files, so a fragment is only sound if its steps changed none.
    // Compared with the state before the block, so earlier steps' changes do not count.
    let after = tree_state(g, name).await?;
    if after != before {
        say(
            cfg,
            conv,
            "user",
            format!(
                "`{name}` is a once block and must only read, but the tree changed while it ran."
            ),
        );
        outcome(cfg, r, name, false, json!({"key": key, "replayed": false}));
        return Ok(false);
    }
    if let Some(f) = &file {
        // Seeing a fragment again is an optimization; failing to save one must not fail the run.
        if let Err(e) = write_fragment(f, &conv.messages[start..]) {
            eprintln!("  could not save once fragment {}: {e:#}", f.display());
        }
    }
    outcome(
        cfg,
        r,
        name,
        true,
        json!({"key": key, "replayed": false, "saved": file.is_some()}),
    );
    Ok(true)
}

fn once_key(steps: &[Step], model: &str, before: &[Value], base: &str) -> String {
    use sha2::{Digest, Sha256};
    let mut h = Sha256::new();
    for part in [
        serde_json::to_vec(steps).expect("program steps serialize"),
        model.as_bytes().to_vec(),
        serde_json::to_vec(before).expect("messages serialize"),
        base.as_bytes().to_vec(),
    ] {
        // Length-prefixed, so no two different inputs hash the same bytes.
        h.update((part.len() as u64).to_le_bytes());
        h.update(part);
    }
    h.finalize().iter().map(|b| format!("{b:02x}")).collect()
}

/// The working tree's content as a git tree hash (through a private index, so the model's own
/// index is untouched) plus the ignored files' names: any write a once block makes changes it.
async fn tree_state(g: &Guest, name: &str) -> Result<String, Stop> {
    g.sh(
        "export GIT_INDEX_FILE=/tmp/.once-index; cp .git/index $GIT_INDEX_FILE 2>/dev/null; \
         git add -A >/dev/null 2>&1 && git write-tree && git status --porcelain --ignored | grep '^!!'",
        BASH_TIMEOUT,
    )
    .await
    .map(|o| o.text)
    .map_err(|e| Stop::GuestDead(format!("`{name}` could not check the tree: {e:#}")))
}

/// The saved messages and their age in seconds, or None when missing, unreadable or too old.
fn read_fragment(file: &std::path::Path, max_age_s: Option<u64>) -> Option<(Vec<Value>, u64)> {
    let age = file
        .metadata()
        .ok()?
        .modified()
        .ok()?
        .elapsed()
        .ok()?
        .as_secs();
    if max_age_s.is_some_and(|max| age > max) {
        return None;
    }
    let v: Value = serde_json::from_str(&std::fs::read_to_string(file).ok()?).ok()?;
    Some((v["messages"].as_array()?.clone(), age))
}

/// Written under a temporary name and renamed, so a reader never sees half a fragment.
fn write_fragment(file: &std::path::Path, messages: &[Value]) -> Result<()> {
    let dir = file.parent().ok_or_else(|| anyhow!("no parent folder"))?;
    std::fs::create_dir_all(dir)?;
    let tmp = dir.join(format!(".{}.tmp", std::process::id()));
    std::fs::write(&tmp, serde_json::to_vec(&json!({"messages": messages}))?)?;
    std::fs::rename(&tmp, file)?;
    Ok(())
}

fn say(cfg: &Config, conv: &mut Conversation, role: &str, text: String) {
    let m = json!({"role": role, "content": text});
    record(cfg, std::slice::from_ref(&m));
    conv.messages.push(m);
}

/// Records how a step ended, in run.json and on the progress output.
fn outcome(cfg: &Config, r: &mut Report, name: &str, ok: bool, detail: Value) {
    cfg.mode.outcome(name, ok);
    let mut v = json!({"name": name, "ok": ok});
    if let (Some(m), Value::Object(d)) = (v.as_object_mut(), detail) {
        m.extend(d);
    }
    r.steps.push(v);
}

enum Stop {
    Fatal(String),
    GuestDead(String),
}

async fn turns(
    g: &Guest,
    cfg: &Config,
    conv: &mut Conversation,
    r: &mut Report,
    max_turns: usize,
) -> Result<Ending, Stop> {
    for _ in 0..max_turns {
        // Numbered across the whole run, so events and the table never repeat a turn number.
        let turn = r.turns + 1;
        let turn_start = Instant::now();
        cfg.mode.header();
        trim(conv);
        let resp = match call(cfg, &conv.messages, turn).await {
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
        let mut msg = resp["choices"][0]["message"].clone();
        if !msg.is_object() {
            return Ok(Ending::ApiError(format!(
                "no message in reply: {}",
                tail(&resp.to_string(), 300)
            )));
        }
        let calls = msg["tool_calls"].as_array().cloned().unwrap_or_default();
        let n_steps = calls.len();
        // A reply that hit max_tokens is cut off: its text is partial and a tool call in it
        // would be too, so none of its calls run, and they are dropped from the conversation
        // (a call without a reply would make the next request invalid).
        // 2026-10-29: one ended a pass as "done" with nothing changed.
        let cut_off = resp["choices"][0]["finish_reason"] == "length";
        if cut_off && let Some(m) = msg.as_object_mut() {
            m.remove("tool_calls");
            // A message with neither calls nor text is invalid for some APIs.
            if m.get("content").is_none_or(Value::is_null) {
                m.insert("content".into(), "".into());
            }
        }
        let empty = msg["content"].as_str().is_none_or(|t| t.trim().is_empty());
        record(cfg, std::slice::from_ref(&msg));
        conv.messages.push(msg);
        if cut_off {
            say(cfg, conv, "user", CUT_OFF.into());
            finish_turn(g, cfg, r, row, 0, turn_start).await;
            continue;
        }
        if calls.is_empty() {
            if empty {
                say(cfg, conv, "user", EMPTY.into());
                finish_turn(g, cfg, r, row, 0, turn_start).await;
                continue;
            }
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
            let limit = MODEL_COMMAND_TIMEOUT;
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
            conv.messages.push(m);
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
    if let Some(p) = cfg.pinned.get() {
        pin(&mut body, p);
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
            Ok(v) => {
                if cfg.pin_provider
                    && let Some(p) = v["provider"].as_str()
                {
                    let _ = cfg.pinned.set(p.to_string());
                }
                return Ok(v);
            }
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

/// Puts `provider` first in the body's provider order, keeping any other provider settings
/// from extra_body. Fallbacks stay allowed: a pinned provider that is down must not end the run.
fn pin(body: &mut Value, provider: &str) {
    let settings = &mut body["provider"];
    if !settings.is_object() {
        *settings = json!({});
    }
    if settings.get("order").is_none() {
        settings["order"] = json!([provider]);
    }
    if settings.get("allow_fallbacks").is_none() {
        settings["allow_fallbacks"] = json!(true);
    }
}

/// What a request event records: the reply's size, tokens and cost, or the error.
fn request_fields(turn: usize, res: &Result<Value, (bool, String)>) -> Value {
    match res {
        Ok(v) => {
            let u = &v["usage"];
            let msg = &v["choices"][0]["message"];
            json!({"turn": turn, "ok": true,
                   "prompt_tokens": u["prompt_tokens"], "completion_tokens": u["completion_tokens"],
                   // How much of the prompt the provider served from its cache.
                   "cached_tokens": u["prompt_tokens_details"]["cached_tokens"],
                   "usage": u,
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
/// never the program's preamble, so no tool reply is left without its call.
fn trim(conv: &mut Conversation) {
    let keep = conv.pinned.unwrap_or(0);
    let m = &mut conv.messages;
    let size = |m: &[Value]| m.iter().map(|v| v.to_string().len()).sum::<usize>();
    while size(m) > MAX_CONVERSATION_CHARS && m.len() > keep + 1 {
        let end = keep
            + 1
            + m[keep + 1..]
                .iter()
                .take_while(|v| v["role"] == "tool")
                .count();
        m.drain(keep..end);
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

/// The first `n` bytes, with a note saying how much was left out.
fn head(s: &str, n: usize) -> String {
    if s.len() <= n {
        return s.to_string();
    }
    let cut = s.floor_char_boundary(n);
    format!("{}\n... [cut, {} more chars]", &s[..cut], s.len() - cut)
}

fn tail(s: &str, n: usize) -> String {
    s[s.ceil_char_boundary(s.len().saturating_sub(n))..].to_string()
}

#[cfg(test)]
mod tests {
    use super::*;
    use anyhow::ensure;

    #[test]
    fn pin_puts_the_provider_first_and_keeps_extra_body_settings() {
        let mut body = json!({"model": "m"});
        pin(&mut body, "a");
        assert_eq!(
            body["provider"],
            json!({"order": ["a"], "allow_fallbacks": true})
        );

        // extra_body's own provider settings win
        let mut body = json!({"provider": {"order": ["b"], "allow_fallbacks": false, "sort": "x"}});
        pin(&mut body, "a");
        assert_eq!(
            body["provider"],
            json!({"order": ["b"], "allow_fallbacks": false, "sort": "x"})
        );
    }

    /// A once block runs and saves the first time, replays without running after, runs again
    /// when its fragment is older than max_age_s, and fails when its steps change the tree.
    #[tokio::test]
    #[ignore]
    async fn once_blocks_against_a_real_guest() {
        let image = std::env::var("WORKER_TEST_IMAGE").expect("WORKER_TEST_IMAGE");
        let g = Guest::boot(&image, 2, 2048).await.unwrap();
        let res = check_once(&g).await;
        g.remove().await;
        res.unwrap();
    }

    async fn check_once(g: &Guest) -> Result<()> {
        let dir = std::env::temp_dir().join(format!("worker-once-test-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir)?;
        let cfg = Config {
            key: String::new(),
            api_url: String::new(),
            model: String::new(),
            extra_body: Map::new(),
            pin_provider: false,
            pinned: OnceLock::new(),
            base: "BASE".into(),
            max_tokens: 1,
            start: Instant::now(),
            transcript: dir.join("transcript.jsonl"),
            events: Events::new(dir.join("events.jsonl")),
            once_dir: Some(dir.join("once")),
            mode: crate::out::Mode::Json(vec![]),
        };
        let cfg = &cfg;
        // Runs count themselves in /tmp, outside the repo, so the block still only reads the repo.
        let block = |max_age: &str| {
            format!(
                r#"{{"steps": [{{"type": "once", "name": "explore"{max_age}, "steps": [
                     {{"type": "command", "name": "look", "show": "always",
                       "run": "echo ran >> /tmp/once-runs; echo found-it"}}]}}]}}"#
            )
        };
        let run = |text: String| async move {
            let program = crate::program::parse(&text, "")?;
            let mut conv = Conversation {
                messages: vec![],
                pinned: None,
            };
            let mut r = Report {
                status: Status::Red,
                turns: 0,
                cost_usd: 0.0,
                reply_tokens: 0,
                tree: String::new(),
                steps: vec![],
                error: None,
            };
            let ok = run_steps(g, cfg, &program.steps, &mut conv, &mut r)
                .await
                .map_err(|_| anyhow!("stopped"))?;
            let said: Vec<String> = conv
                .messages
                .iter()
                .filter_map(|m| m["content"].as_str().map(String::from))
                .collect();
            let runs = g
                .sh("wc -l < /tmp/once-runs", BASH_TIMEOUT)
                .await?
                .text
                .trim()
                .to_string();
            Ok::<_, anyhow::Error>((ok, said, runs))
        };
        bash_in(
            g,
            "rm -rf /repo && mkdir /repo && cd /repo && git init -q && rm -f /tmp/once-runs",
        )
        .await?;

        let (ok, said, runs) = run(block("")).await?;
        ensure!(
            ok && runs == "1" && said == ["`look`:\n\nfound-it\n"],
            "first: {ok} {runs} {said:?}"
        );
        let (ok, said, runs) = run(block("")).await?;
        ensure!(
            ok && runs == "1" && said == ["`look`:\n\nfound-it\n"],
            "replay: {ok} {runs} {said:?}"
        );
        // max_age_s is not part of the key, and a fragment younger than a second is not older
        // than 0 s: it still replays.
        let (ok, _, runs) = run(block(r#", "max_age_s": 0"#)).await?;
        ensure!(ok && runs == "1", "a fresh fragment should replay: {runs}");
        tokio::time::sleep(Duration::from_millis(1100)).await;
        let (ok, _, runs) = run(block(r#", "max_age_s": 0"#)).await?;
        ensure!(
            ok && runs == "2",
            "a fragment older than max_age_s should run again: {runs}"
        );

        // A tree that earlier steps changed is fine, as long as the block changes nothing more.
        bash_in(g, "echo before > /repo/dirty").await?;
        let reader = r#"{"steps": [{"type": "once", "name": "reads", "steps": [
            {"type": "command", "name": "cat", "run": "cat /repo/dirty"}]}]}"#;
        let (ok, said, _) = run(reader.to_string()).await?;
        ensure!(
            ok,
            "a read-only block on a dirty tree should pass: {said:?}"
        );
        // Editing a file that was already modified is a change too, unlike in plain git status.
        let editor = r#"{"steps": [{"type": "once", "name": "edits", "steps": [
            {"type": "command", "name": "append", "run": "echo more >> /repo/dirty"}]}]}"#;
        let (ok, said, _) = run(editor.to_string()).await?;
        ensure!(
            !ok && said.iter().any(|m| m.contains("must only read")),
            "editor: {ok} {said:?}"
        );

        let writer = r#"{"steps": [{"type": "once", "name": "writes", "steps": [
            {"type": "command", "name": "touch", "run": "touch /repo/new-file"}]}]}"#;
        let (ok, said, _) = run(writer.to_string()).await?;
        ensure!(
            !ok && said.iter().any(|m| m.contains("must only read")),
            "writer: {ok} {said:?}"
        );
        std::fs::remove_dir_all(&dir)?;
        Ok(())
    }

    async fn bash_in(g: &Guest, cmd: &str) -> Result<()> {
        let o = g.sh(cmd, BASH_TIMEOUT).await?;
        ensure!(o.code == Some(0), "{cmd}: {}", o.text);
        Ok(())
    }

    /// A program of commands only, so no model is called: a script retries until its steps
    /// all pass, stops each pass at the first failure, and tells the model what failed.
    #[tokio::test]
    #[ignore]
    async fn program_steps_against_a_real_guest() {
        let image = std::env::var("WORKER_TEST_IMAGE").expect("WORKER_TEST_IMAGE");
        let g = Guest::boot(&image, 2, 2048).await.unwrap();
        let res = check_program(&g).await;
        g.remove().await;
        res.unwrap();
    }

    async fn check_program(g: &Guest) -> Result<()> {
        let dir = std::env::temp_dir().join(format!("worker-program-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir)?;
        let cfg = Config {
            key: String::new(),
            api_url: String::new(),
            model: String::new(),
            extra_body: Map::new(),
            pin_provider: false,
            pinned: OnceLock::new(),
            base: "BASE".into(),
            max_tokens: 1,
            start: Instant::now(),
            transcript: dir.join("transcript.jsonl"),
            events: Events::new(dir.join("events.jsonl")),
            once_dir: None,
            mode: crate::out::Mode::Json(vec![]),
        };
        // `flaky` fails on its first two passes; `after` must never run on a failing pass.
        let program = crate::program::parse(
            r#"{"steps": [
              {"type": "message", "name": "rules", "role": "system", "text": "brief: {brief}"},
              {"type": "command", "name": "context", "run": "echo hello-context", "show": "always"},
              {"type": "script", "name": "work", "retries": 2, "steps": [
                {"type": "command", "name": "count", "run": "echo x >> /tmp/passes"},
                {"type": "command", "name": "flaky", "show": "failure",
                 "run": "echo base=$WORKER_BASE; test $(wc -l < /tmp/passes) -ge 3"},
                {"type": "command", "name": "after", "run": "echo y >> /tmp/after"}
              ]},
              {"type": "command", "name": "last", "run": "exit 4"}
            ]}"#,
            "B",
        )?;
        let mut conv = Conversation {
            messages: vec![],
            pinned: None,
        };
        let mut r = Report {
            status: Status::Red,
            turns: 0,
            cost_usd: 0.0,
            reply_tokens: 0,
            tree: String::new(),
            steps: vec![],
            error: None,
        };
        g.sh("rm -f /tmp/passes /tmp/after", BASH_TIMEOUT).await?;
        let ok = run_steps(g, &cfg, &program.steps, &mut conv, &mut r).await;
        let ok = ok.map_err(|_| anyhow!("stopped"))?;
        ensure!(!ok, "a failing top-level `last` must fail the program");
        let passes = g
            .sh("wc -l < /tmp/passes; wc -l < /tmp/after", BASH_TIMEOUT)
            .await?
            .text;
        ensure!(
            passes.split_whitespace().eq(["3", "1"]),
            "passes/after: {passes}"
        );
        let said: Vec<&str> = conv
            .messages
            .iter()
            .filter_map(|m| m["content"].as_str())
            .collect();
        ensure!(said[0] == "brief: B", "{said:?}");
        // A passing command with `show: always` hands the model its output.
        ensure!(said[1] == "`context`:\n\nhello-context\n", "{said:?}");
        ensure!(
            said[2].starts_with("`flaky` failed (exit 1):") && said[2].contains("base=BASE"),
            "{said:?}"
        );
        ensure!(
            said.len() == 5 && said[4] == "`last` failed (exit 4).",
            "{said:?}"
        );
        let outcomes: Vec<(String, bool)> = r
            .steps
            .iter()
            .map(|s| {
                (
                    s["name"].as_str().unwrap_or("").to_string(),
                    s["ok"] == true,
                )
            })
            .collect();
        ensure!(
            outcomes
                .iter()
                .filter(|(n, _)| n == "work")
                .map(|(_, ok)| *ok)
                .eq([false, false, true]),
            "{outcomes:?}"
        );
        std::fs::remove_dir_all(&dir)?;
        Ok(())
    }

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

    fn find_command(steps: &[Step], want: &str) -> Option<String> {
        steps.iter().find_map(|s| match s {
            Step::Command { name, run, .. } if name == want => Some(run.clone()),
            Step::Script { steps, .. } => find_command(steps, want),
            _ => None,
        })
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
        // The default program's `changed` step: an untracked file and committed work both count
        // as changes; a tree equal to the base does not. The counts and the patch see committed
        // work too, and the patch is one plain diff with nothing but git's stdout in it.
        let program = crate::program::parse(include_str!("../programs/default.json"), "").unwrap();
        let changed = find_command(&program.steps, "changed").expect("a `changed` step");
        let changed_since = |rev: String| {
            let cmd = format!("export WORKER_BASE={rev}; {changed}");
            async move { Ok::<_, anyhow::Error>(g.sh(&cmd, BASH_TIMEOUT).await?.code == Some(0)) }
        };
        let commit = g.sh("git rev-parse HEAD", BASH_TIMEOUT).await?.text;
        let commit = commit.trim();
        ensure!(
            changed_since(commit.into()).await?,
            "untracked file seen as unchanged"
        );
        bash("cd /repo && git add -A && git -c user.name=t -c user.email=t@t commit -qm work")
            .await?;
        ensure!(
            changed_since(commit.into()).await?,
            "committed work seen as unchanged"
        );
        ensure!(
            !changed_since("HEAD".into()).await?,
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
