//! TERM: program -- what a run does, as data: a JSON file of steps the harness runs in order.
//! TERM: program step -- one of four kinds (`type`), each with a `name` that labels its event
//! and what the model is told when it fails. Avoid: task (that is the brief), stage.
//!
//!   message  {role: system|user, text}   appends to the conversation; `{brief}` in the text is
//!                                         replaced by the brief. Always succeeds.
//!   llm      {max_turns}                  the model works with its tool until it stops calling
//!                                         it (succeeds) or runs out of turns (fails).
//!   command  {run, show_failure?}         a shell command in the guest's /repo, with
//!                                         $WORKER_BASE set to the base commit; exit 0 succeeds.
//!                                         When it fails, the model is told its name, and with
//!                                         show_failure also the output's tail.
//!   script   {retries, steps}             runs its steps until one fails; then runs all of them
//!                                         again, up to `retries` more times. Succeeds when one
//!                                         pass gets through every step.
//!
//! The run is GREEN when every top-level step succeeds. Some failures end the run whatever is
//! left to retry: a bad key or no credit (FATAL), the deadline (TIMEOUT), a dead guest.
//!
//! DECISION (owner, 2026-10-29): a program is data, so which checks run, in what order and how
//! often is chosen per run instead of being built into the loop. Four kinds and no more: no
//! variables, conditions or loops beyond a script's retries. Message is the only kind that
//! writes prose; a command decides only whether the model sees its failing output.

use std::collections::HashSet;
use std::path::Path;

use anyhow::{Context, Result, bail, ensure};
use serde::Deserialize;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Program {
    pub steps: Vec<Step>,
}

#[derive(Debug, Deserialize)]
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
        show_failure: bool,
    },
    Script {
        name: String,
        retries: usize,
        steps: Vec<Step>,
    },
}

#[derive(Debug, Deserialize, Clone, Copy)]
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
            | Step::Script { name, .. } => name,
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
                check(steps, brief, names)?;
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
        ];
        for (text, want) in bad {
            let err = format!("{:#}", parse(text, "").unwrap_err());
            assert!(err.contains(want), "{text}: {err}");
        }
    }
}
