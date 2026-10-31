//! TERM: output mode -- how a run reports progress while it happens: a table for a person on
//! stderr, or JSON lines on stdout for an orchestrating agent. run.json at the end is the same
//! in both. Avoid: format, verbosity.
//!
//! TERM: turn -- one model reply. TERM: step -- one tool call inside a turn; a turn has zero or
//! more. With bash the only tool, a step is one shell command; the name stays for when another
//! tool comes back.
//!
//! DECISION: steps print as they start, so a five-minute verify shows while it runs; the
//! turn's totals print in bold once its steps are done, so its time can include them
//! (maintainer, 2026-10-21). Rejected: printing the turn row first, which had to drop the
//! tool time from it.
//!
//! DECISION: every turn is its own small table (header, its steps, its totals, two empty
//! lines), so the column names are on screen whatever turn a person scrolls to, and a bash
//! step is highlighted by `bat` when it is installed (owner, 2026-10-22).
//!
//! DECISION: JSON mode prints only the fields the caller lists (`--json turn,cost_total`),
//! because every line an orchestrating agent reads costs it tokens. Step lines appear only
//! when `step_events` is listed. Rejected: auto-detecting a pipe, which surprises a person
//! piping the table into `less`.

use std::io::IsTerminal;
use std::time::Duration;

use clap::ValueEnum;

use crate::guest::Lines;
use serde_json::{Map, Value, json};

#[derive(Clone, Copy, PartialEq, ValueEnum)]
#[value(rename_all = "snake_case")]
pub enum Field {
    Turn,
    /// The turn's prompt: the whole conversation, re-sent every turn.
    Context,
    Reply,
    ReplyTotal,
    Cost,
    CostTotal,
    /// Seconds waiting for the model this turn, retries included.
    TimeLlm,
    /// Seconds running the turn's steps in the guest.
    TimeTools,
    TimeTotal,
    Steps,
    /// Lines [added, deleted] by this turn's steps.
    Diff,
    /// Lines [added, deleted] against the base commit.
    DiffTotal,
    /// Not a field: a `step` line as each step starts.
    StepEvents,
}

pub enum Mode {
    Table,
    Json(Vec<Field>),
}

pub struct TurnRow {
    pub turn: usize,
    pub context: u64,
    pub reply: u64,
    pub reply_total: u64,
    pub cost: f64,
    pub cost_total: f64,
    pub time_llm: Duration,
    pub time_tools: Duration,
    pub time_total: Duration,
    pub steps: usize,
    pub diff: Lines,
    pub diff_total: Lines,
}

impl Mode {
    /// At the start of every turn.
    pub fn header(&self) {
        if let Mode::Table = self {
            eprintln!(
                "{:>4}  {:>7}  {:>11}  {:>15}  {:>12}  {:>5}  {:>15}",
                "Turn", "Context", "Reply", "Cost $", "Time", "Steps", "Diff"
            );
        }
    }

    /// As a step starts. `tool` is the short name, `summary` its arguments on one line.
    pub fn step(&self, turn: usize, tool: &str, summary: &str) {
        match self {
            Mode::Table => {
                // Cut first, colour after: the width counts visible characters only.
                let line = fit(&format!("      {tool:<5}  {}", one_line(summary)), width());
                let (name, args) = line.split_at(line.floor_char_boundary(11));
                let args = match tool {
                    "bash" => highlight_bash(args).unwrap_or_else(|| paint(DIM, args)),
                    _ => paint(DIM, args),
                };
                eprintln!("{}{args}", paint(CYAN, name));
            }
            Mode::Json(fields) if fields.contains(&Field::StepEvents) => {
                let summary: String = one_line(summary).chars().take(200).collect();
                println!(
                    "{}",
                    json!({"event": "step", "turn": turn, "tool": tool, "summary": summary})
                );
            }
            Mode::Json(_) => {}
        }
    }

    /// Once the turn's steps are done.
    pub fn turn(&self, r: &TurnRow) {
        match self {
            Mode::Table => {
                let reply = format!("{}/{}", tokens(r.reply), tokens(r.reply_total));
                let cost = format!("{:.4}/{:.4}", r.cost, r.cost_total);
                // model+steps/total: 3s+5m/5m is a turn spent in a test run.
                let time = format!(
                    "{}+{}/{}",
                    duration(r.time_llm),
                    duration(r.time_tools),
                    duration(r.time_total)
                );
                let line = format!(
                    "{:>4}  {:>7}  {reply:>11}  {cost:>15}  {time:>12}  {:>5}  {:>15}",
                    r.turn,
                    tokens(r.context),
                    r.steps,
                    format!("{}/{}", lines(r.diff), lines(r.diff_total))
                );
                eprintln!("{}", paint(BOLD, &line));
                eprintln!();
                eprintln!();
            }
            Mode::Json(fields) => {
                let mut m = Map::new();
                m.insert("event".into(), "turn".into());
                for f in fields {
                    let (k, v): (&str, Value) = match f {
                        Field::Turn => ("turn", r.turn.into()),
                        Field::Context => ("context", r.context.into()),
                        Field::Reply => ("reply", r.reply.into()),
                        Field::ReplyTotal => ("reply_total", r.reply_total.into()),
                        Field::Cost => ("cost", r.cost.into()),
                        Field::CostTotal => ("cost_total", r.cost_total.into()),
                        Field::TimeLlm => ("time_llm", r.time_llm.as_secs().into()),
                        Field::TimeTools => ("time_tools", r.time_tools.as_secs().into()),
                        Field::TimeTotal => ("time_total", r.time_total.as_secs().into()),
                        Field::Steps => ("steps", r.steps.into()),
                        Field::Diff => ("diff", json!([r.diff.added, r.diff.deleted])),
                        Field::DiffTotal => (
                            "diff_total",
                            json!([r.diff_total.added, r.diff_total.deleted]),
                        ),
                        Field::StepEvents => continue,
                    };
                    m.insert(k.into(), v);
                }
                println!("{}", Value::Object(m));
            }
        }
    }

    /// When a program step (other than a message) ends.
    pub fn outcome(&self, name: &str, ok: bool) {
        match self {
            Mode::Table => {
                let line = format!("== {name}: {} ==", if ok { "ok" } else { "FAILED" });
                eprintln!("{}", paint(if ok { GREEN } else { RED }, &line));
            }
            Mode::Json(_) => println!("{}", json!({"event": "outcome", "name": name, "ok": ok})),
        }
    }

    /// The last line in JSON mode; details are in run.json.
    pub fn done(&self, status: &str, exit: u8) {
        if let Mode::Json(_) = self {
            println!(
                "{}",
                json!({"event": "done", "status": status, "exit": exit})
            );
        }
    }
}

const BOLD: &str = "1";
const DIM: &str = "2";
const RED: &str = "1;31";
const GREEN: &str = "1;32";
const CYAN: &str = "36";

/// Colour for a person at a terminal, or for a log they follow with `tail -f` when
/// `CLICOLOR_FORCE` is set (the usual convention); otherwise plain text.
fn colour() -> bool {
    std::io::stderr().is_terminal() || std::env::var_os("CLICOLOR_FORCE").is_some_and(|v| v != "0")
}

/// A bash command coloured by `bat`, or None (no colour, or no `bat` on PATH).
fn highlight_bash(s: &str) -> Option<String> {
    use std::io::Write;
    use std::process::{Command, Stdio};
    if !colour() {
        return None;
    }
    let mut child = Command::new("bat")
        .args([
            "--language",
            "bash",
            "--color",
            "always",
            "--style",
            "plain",
        ])
        .args(["--paging", "never"])
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .spawn()
        .ok()?;
    child.stdin.take()?.write_all(s.as_bytes()).ok()?;
    let out = child.wait_with_output().ok()?;
    let text = String::from_utf8(out.stdout).ok()?;
    out.status
        .success()
        .then(|| text.trim_end_matches('\n').to_string())
}

/// ANSI colour for a person at a terminal; a log file gets plain text.
fn paint(code: &str, s: &str) -> String {
    if colour() {
        format!("\x1b[{code}m{s}\x1b[0m")
    } else {
        s.to_string()
    }
}

/// The terminal's columns, or None when stderr is not one (a log file keeps whole lines).
fn width() -> Option<usize> {
    if !std::io::stderr().is_terminal() {
        return None;
    }
    terminal_size::terminal_size_of(std::io::stderr()).map(|(w, _)| w.0 as usize)
}

/// Also drops control characters: a command is model text, and an ESC or OSC sequence in it
/// would reach the terminal of whoever follows the log.
fn one_line(s: &str) -> String {
    s.split_whitespace()
        .map(|w| w.chars().filter(|c| !c.is_control()).collect::<String>())
        .collect::<Vec<_>>()
        .join(" ")
}

/// Cut to `width` characters, the last one an ellipsis, as the maintainer asked for.
fn fit(line: &str, width: Option<usize>) -> String {
    match width {
        Some(w) if line.chars().count() > w && w > 0 => {
            line.chars().take(w - 1).chain(['\u{2026}']).collect()
        }
        _ => line.to_string(),
    }
}

/// +12-3, or 0 for a turn that changed nothing.
fn lines(l: Lines) -> String {
    if l.added == 0 && l.deleted == 0 {
        "0".into()
    } else {
        format!("+{}-{}", l.added, l.deleted)
    }
}

/// 42s under a minute, whole minutes after that: 5m/90m reads at a glance.
fn duration(d: Duration) -> String {
    match d.as_secs() {
        s @ 0..60 => format!("{s}s"),
        s => format!("{}m", s / 60),
    }
}

/// 121, 5.6K, 17.8K, 1.2M: one decimal is enough to watch a prompt grow.
fn tokens(n: u64) -> String {
    match n {
        0..1_000 => n.to_string(),
        1_000..1_000_000 => format!("{:.1}K", n as f64 / 1e3),
        _ => format!("{:.1}M", n as f64 / 1e6),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn durations_read_as_seconds_then_minutes() {
        let got: Vec<String> = [0, 42, 59, 60, 299, 5400]
            .map(|s| duration(Duration::from_secs(s)))
            .into();
        assert_eq!(got, ["0s", "42s", "59s", "1m", "4m", "90m"]);
    }

    #[test]
    fn token_counts_shorten() {
        let got: Vec<String> = [121, 999, 1_549, 17_816, 999_949, 1_234_567]
            .map(tokens)
            .into();
        assert_eq!(got, ["121", "999", "1.5K", "17.8K", "999.9K", "1.2M"]);
    }

    #[test]
    fn long_lines_end_in_an_ellipsis_at_the_width() {
        assert_eq!(fit("cd /repo && just check", Some(10)), "cd /repo \u{2026}");
        assert_eq!(fit("short", Some(10)), "short");
        assert_eq!(
            fit("not a terminal keeps it all", None),
            "not a terminal keeps it all"
        );
        assert_eq!(one_line("a\n  b\tc"), "a b c");
        // An OSC 52 clipboard write and a cursor move, as a model could put in a command.
        assert_eq!(
            one_line("ls\x1b]52;c;ZXZpbA==\x07 \x1b[2Aok"),
            "ls]52;c;ZXZpbA== [2Aok"
        );
    }
}
