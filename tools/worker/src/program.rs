//! TERM: program -- what a run does, as data: a JSON file of steps the harness runs in order.
//! TERM: program step -- one of six kinds (`type`), each with a `name` that labels its event
//! and what the model is told when it fails. Avoid: task (that is the brief), stage.
//!
//!   message  {role: system|user, text}   appends to the conversation; `{brief}` in the text is
//!                                         replaced by the brief. Always succeeds.
//!   llm      {max_turns}                  the model works with its tool until it stops calling
//!                                         it (succeeds) or runs out of turns (fails).
//!   command  {run, show?}                 a shell command in the guest's /repo, with
//!                                         $WORKER_BASE set to the base commit; exit 0 succeeds.
//!                                         When it fails, the model is told its name. `show`
//!                                         adds its output: "failure" the tail of a failing one,
//!                                         "always" also the start of a passing one, which is
//!                                         how a program hands the model the files it needs.
//!   script   {retries, steps}             runs its steps until one fails; then runs all of them
//!                                         again, up to `retries` more times. Succeeds when one
//!                                         pass gets through every step.
//!   try      {steps, catch?}              runs its steps until one fails; then runs `catch`,
//!                                         whose result is the try's. Succeeds when its steps
//!                                         all pass, or when `catch` passes; an empty or missing
//!                                         `catch` ignores the failure. A run that stops (BLOCKED,
//!                                         FATAL, a dead guest) is not a failure it catches.
//!   once     {max_age_s?, steps}          runs its steps and saves the messages they added; a
//!                                         later run with the same steps, model, conversation so
//!                                         far and base commit replays them instead, if the saved
//!                                         fragment is not older than max_age_s. Its steps may
//!                                         only read: a once block that changes the tree fails.
//!                                         No once inside once.
//!
//! The run is GREEN when every top-level step succeeds. Some failures end the run whatever is
//! left to retry: a bad key or no credit (FATAL), a dead guest. A run ends by counts: at most
//! each llm step's max_turns per pass, and each script's retries; a command that runs past its
//! fixed timeout (30 minutes) fails like any other. Five turns before an llm step's last, the
//! model is told how many are left.
//!
//! TERM: BLOCKED -- an llm step's final reply (no tool calls) starting with `BLOCKED:`. The run
//! ends there with status BLOCKED (exit 5): no later step, no script retry, no check runs. The
//! patch is still collected and the reply is the report's `error`.
//!
//! DECISION (owner, 2026-10-31): a brief that says "if X, stop and report" is obeyed by a model
//! that stops, so that stop is an outcome of its own, not a failure: retrying it only spends
//! turns (2026-10-31: 56 and 79 turns in two such runs) on a run that already has its answer.
//!
//! DECISION (owner, 2026-10-29): a program is data, so which checks run, in what order and how
//! often is chosen per run instead of being built into the loop. No variables, and no loops
//! beyond a script's retries. Message is the only kind that writes prose; a command decides
//! only whether the model sees its failing output.
//!
//! DECISION (owner, 2026-11-07): `try` is the one condition. An llm step that runs out of turns
//! used to end its pass before any check ran (2026-11-06: 3 of 3 passes in one run), throwing
//! away work the checks might have accepted. A try around it lets the program decide what
//! happens next, instead of a per-kind option such as `on_max_turns`.

use std::collections::HashSet;
use std::path::Path;

use anyhow::{Context, Result, bail, ensure};
use serde::{Deserialize, Serialize};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Program {
    pub steps: Vec<Step>,
}

#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum Step {
    Message {
        name: String,
        role: Role,
        text: String,
    },
    Llm {
        name: String,
        max_turns: usize,
    },
    Command {
        name: String,
        run: String,
        #[serde(default)]
        show: Show,
    },
    Script {
        name: String,
        retries: usize,
        steps: Vec<Step>,
    },
    Try {
        name: String,
        steps: Vec<Step>,
        #[serde(default, skip_serializing_if = "Vec::is_empty")]
        catch: Vec<Step>,
    },
    Once {
        name: String,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        max_age_s: Option<u64>,
        steps: Vec<Step>,
    },
}

/// Which of a command's output the model sees.
#[derive(Debug, Deserialize, Serialize, Clone, Copy, Default, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum Show {
    #[default]
    Never,
    Failure,
    Always,
}

#[derive(Debug, Deserialize, Serialize, Clone, Copy)]
#[serde(rename_all = "snake_case")]
pub enum Role {
    System,
    User,
}

impl Role {
    pub fn as_str(self) -> &'static str {
        match self {
            Role::System => "system",
            Role::User => "user",
        }
    }
}

impl Step {
    pub fn name(&self) -> &str {
        match self {
            Step::Message { name, .. }
            | Step::Llm { name, .. }
            | Step::Command { name, .. }
            | Step::Script { name, .. }
            | Step::Try { name, .. }
            | Step::Once { name, .. } => name,
        }
    }
}

/// Reads and checks a program, with `{brief}` already replaced, before any sandbox boots.
pub fn load(path: &Path, brief: &str) -> Result<Program> {
    let text = std::fs::read_to_string(path).with_context(|| format!("reading {path:?}"))?;
    parse(&text, brief).with_context(|| format!("program {path:?}"))
}

pub fn parse(text: &str, brief: &str) -> Result<Program> {
    let mut program: Program = serde_json::from_str(text)?;
    ensure!(!program.steps.is_empty(), "no steps");
    let mut names = HashSet::new();
    check(&mut program.steps, brief, &mut names)?;
    Ok(program)
}

fn check(steps: &mut [Step], brief: &str, names: &mut HashSet<String>) -> Result<()> {
    check_in(steps, brief, names, false)
}

fn check_in(
    steps: &mut [Step],
    brief: &str,
    names: &mut HashSet<String>,
    in_once: bool,
) -> Result<()> {
    for step in steps {
        let name = step.name().to_string();
        ensure!(!name.trim().is_empty(), "a step has an empty name");
        // Names label events and failure messages, so one name must mean one step.
        if !names.insert(name.clone()) {
            bail!("two steps are named {name:?}");
        }
        match step {
            Step::Message { text, .. } => *text = text.replace("{brief}", brief),
            Step::Llm { max_turns, .. } => ensure!(*max_turns > 0, "{name:?}: max_turns is 0"),
            Step::Command { run, .. } => ensure!(!run.trim().is_empty(), "{name:?}: empty run"),
            Step::Script { steps, .. } => {
                ensure!(!steps.is_empty(), "{name:?}: no steps");
                check_in(steps, brief, names, in_once)?;
            }
            Step::Try { steps, catch, .. } => {
                ensure!(!steps.is_empty(), "{name:?}: no steps");
                check_in(steps, brief, names, in_once)?;
                check_in(catch, brief, names, in_once)?;
            }
            Step::Once { steps, .. } => {
                ensure!(!in_once, "{name:?}: a once block inside a once block");
                ensure!(!steps.is_empty(), "{name:?}: no steps");
                check_in(steps, brief, names, true)?;
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_default_program_is_valid() {
        let text = include_str!("../programs/default.json");
        let p = parse(text, "do X").unwrap();
        let task = p.steps.iter().find_map(|s| match s {
            Step::Message { text, .. } if text.contains("do X") => Some(text),
            _ => None,
        });
        assert!(task.is_some(), "no message carries the brief");
    }

    #[test]
    fn strict_validation_rejects_mistakes() {
        let bad = [
            (r#"{"steps": []}"#, "no steps"),
            (r#"{"steps": [], "extra": 1}"#, "unknown field"),
            (
                r#"{"steps": [{"type": "shell", "name": "a"}]}"#,
                "unknown variant",
            ),
            (
                r#"{"steps": [{"type": "llm", "name": "a", "max_turns": 5, "retries": 1}]}"#,
                "unknown field",
            ),
            (
                r#"{"steps": [{"type": "llm", "name": "a"}]}"#,
                "missing field",
            ),
            (
                r#"{"steps": [{"type": "llm", "name": "a", "max_turns": 0}]}"#,
                "max_turns is 0",
            ),
            (
                r#"{"steps": [{"type": "command", "name": "", "run": "true"}]}"#,
                "empty name",
            ),
            (
                r#"{"steps": [{"type": "command", "name": "a", "run": "true"},
                              {"type": "script", "name": "s", "retries": 1, "steps": [
                                {"type": "command", "name": "a", "run": "true"}]}]}"#,
                "two steps are named",
            ),
            (
                r#"{"steps": [{"type": "message", "name": "m", "role": "tool", "text": "x"}]}"#,
                "unknown variant",
            ),
            (
                r#"{"steps": [{"type": "command", "name": "c", "run": "true", "show": "sometimes"}]}"#,
                "unknown variant",
            ),
            (
                r#"{"steps": [{"type": "once", "name": "o", "steps": [
                    {"type": "once", "name": "p", "steps": [{"type": "command", "name": "c", "run": "true"}]}]}]}"#,
                "inside a once block",
            ),
            (
                r#"{"steps": [{"type": "once", "name": "o", "max_age_s": -1, "steps": []}]}"#,
                "invalid value",
            ),
            (
                r#"{"steps": [{"type": "try", "name": "t", "steps": []}]}"#,
                "\"t\": no steps",
            ),
            (
                r#"{"steps": [{"type": "try", "name": "t",
                    "steps": [{"type": "command", "name": "a", "run": "true"}],
                    "catch": [{"type": "command", "name": "a", "run": "true"}]}]}"#,
                "two steps are named",
            ),
            (
                r#"{"steps": [{"type": "try", "name": "t",
                    "steps": [{"type": "command", "name": "a", "run": "true"}],
                    "catch": [{"type": "llm", "name": "b", "max_turns": 0}]}]}"#,
                "max_turns is 0",
            ),
        ];
        for (text, want) in bad {
            let err = format!("{:#}", parse(text, "").unwrap_err());
            assert!(err.contains(want), "{text}: {err}");
        }
    }

    #[test]
    fn a_try_block_parses_with_and_without_catch() {
        let p = parse(
            r#"{"steps": [
              {"type": "try", "name": "t1", "steps": [{"type": "command", "name": "a", "run": "true"}]},
              {"type": "try", "name": "t2", "steps": [{"type": "command", "name": "b", "run": "true"}],
               "catch": [{"type": "message", "name": "m", "role": "user", "text": "x {brief}"}]}
            ]}"#,
            "B",
        )
        .unwrap();
        match &p.steps[..] {
            [
                Step::Try { catch: none, .. },
                Step::Try {
                    catch: handlers, ..
                },
            ] => {
                assert!(none.is_empty());
                assert!(matches!(&handlers[..], [Step::Message { text, .. }] if text == "x B"));
            }
            other => panic!("{other:?}"),
        }
    }
}
