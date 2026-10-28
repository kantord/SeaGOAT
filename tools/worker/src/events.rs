//! TERM: event -- one timed step of a run, one JSON line in events.jsonl: what ran, when, how
//! long it took, how busy the host was meanwhile (and the guest, for steps that run in it), and
//! for model calls the tokens and cost. timings.py reads it; so can anyone asking why a run was
//! slow. Avoid: log (the run log is the table on stderr), trace.
//!
//! DECISION (owner, 2026-10-28): every step of a run is an event, so a slow run can be taken
//! apart afterwards instead of guessed at. Steps never overlap, so their durations add up, and
//! what they leave uncovered is time no step accounts for. run.py appends its own host steps
//! to the same file; `ts` is wall-clock seconds so both writers line up.
//!
//! DECISION: CPU busy is the share of all CPUs (host or guest) that were not idle between the
//! step's start and end, from /proc/stat. The 1-minute load average lags by design, so a short
//! step only gets it as context. Rejected: per-process accounting, which misses the other
//! work on the machine, the usual cause of a slow verify here (2026-10-28: load 55 on 20 CPUs).

use std::io::Write;
use std::path::PathBuf;
use std::time::{Instant, SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value, json};

#[derive(Clone)]
pub struct Events {
    path: PathBuf,
}

pub struct Span {
    phase: &'static str,
    name: String,
    ts: f64,
    t0: Instant,
    host: Option<Cpu>,
}

/// Cumulative CPU time from the first line of /proc/stat, in clock ticks.
#[derive(Clone, Copy)]
pub struct Cpu {
    busy: u64,
    total: u64,
}

impl Cpu {
    /// `cpu  user nice system idle iowait irq softirq steal ...`; idle and iowait are not busy.
    pub fn parse(stat: &str) -> Option<Cpu> {
        let n: Vec<u64> = stat
            .lines()
            .next()?
            .strip_prefix("cpu ")?
            .split_whitespace()
            .map(|v| v.parse().ok())
            .collect::<Option<_>>()?;
        let total: u64 = n.iter().take(8).sum();
        let idle = n.get(3)? + n.get(4)?;
        Some(Cpu {
            busy: total - idle,
            total,
        })
    }

    fn host() -> Option<Cpu> {
        Cpu::parse(&std::fs::read_to_string("/proc/stat").ok()?)
    }

    /// The share of CPU time between two samples that was busy, 0 to 1.
    pub fn busy_between(a: Option<Cpu>, b: Option<Cpu>) -> Option<f64> {
        let (a, b) = (a?, b?);
        let total = b.total.checked_sub(a.total)?;
        (total > 0).then(|| round3((b.busy - a.busy) as f64 / total as f64))
    }
}

impl Events {
    pub fn new(path: PathBuf) -> Self {
        Self { path }
    }

    pub fn begin(&self, phase: &'static str, name: impl Into<String>) -> Span {
        Span {
            phase,
            name: name.into(),
            ts: now(),
            t0: Instant::now(),
            host: Cpu::host(),
        }
    }

    /// Writes the step with `fields` (a JSON object: exit code, cost, ...) merged in.
    pub fn end(&self, span: Span, fields: Value) {
        let mut m = Map::new();
        m.insert("ts".into(), json!(round3(span.ts)));
        m.insert("phase".into(), span.phase.into());
        m.insert("name".into(), span.name.into());
        m.insert(
            "duration_s".into(),
            json!(round3(span.t0.elapsed().as_secs_f64())),
        );
        m.insert(
            "host_cpu_busy".into(),
            json!(Cpu::busy_between(span.host, Cpu::host())),
        );
        m.insert("host_load1".into(), json!(load1()));
        m.insert(
            "host_cpus".into(),
            json!(std::thread::available_parallelism().map_or(0, |n| n.get())),
        );
        if let Value::Object(f) = fields {
            m.extend(f);
        }
        // Timing a run must never be what breaks it.
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
        {
            let _ = writeln!(f, "{}", Value::Object(m));
        }
    }
}

fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0.0, |d| d.as_secs_f64())
}

fn load1() -> Option<f64> {
    std::fs::read_to_string("/proc/loadavg")
        .ok()?
        .split_whitespace()
        .next()?
        .parse()
        .ok()
}

fn round3(x: f64) -> f64 {
    (x * 1000.0).round() / 1000.0
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn cpu_busy_counts_idle_and_iowait_as_idle() {
        let a = Cpu::parse("cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 1 2 3").unwrap();
        let b = Cpu::parse("cpu  200 0 200 800 100 0 0 0 0 0\n").unwrap();
        assert_eq!(Cpu::busy_between(Some(a), Some(b)), Some(0.667));
        assert_eq!(Cpu::busy_between(Some(a), None), None);
        assert!(Cpu::parse("intr 1 2").is_none());
    }
}
