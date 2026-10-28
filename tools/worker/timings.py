#!/usr/bin/env python3
"""Where a worker run's time went: `python3 tools/worker/timings.py <run dir>`.

Reads <run dir>/run/events.jsonl (one line per step; tools/worker/src/events.rs says what is in
it) and prints the wall time, the time per phase and what no step accounts for, the slowest
steps, and the model's tokens and cost. CPU busy is the share of all CPUs that were not idle
during a step, weighted by duration when summed; "host" is this machine, "guest" the sandbox.
`--json` prints the same as one JSON object, for comparing runs.

run.py writes its own host steps (building the worker, applying the patch) into the same file.
Standard library only.
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path


def load(run_dir: Path) -> list[dict]:
    path = run_dir / "run" / "events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def weighted(events: list[dict], key: str) -> float | None:
    pairs = [(e[key], e["duration_s"]) for e in events if e.get(key) is not None]
    total = sum(d for _, d in pairs)
    return round(sum(v * d for v, d in pairs) / total, 3) if total else None


def summary(events: list[dict]) -> dict:
    start = min(e["ts"] for e in events)
    wall = max(e["ts"] + e["duration_s"] for e in events) - start
    phases = defaultdict(list)
    for e in events:
        phases[e["phase"]].append(e)
    llm = [e for e in phases.get("llm", []) if e["name"] == "request" and e.get("ok")]
    return {
        "wall_s": round(wall, 1),
        "unaccounted_s": round(wall - sum(e["duration_s"] for e in events), 1),
        "phases": {
            p: {
                "steps": len(es),
                "total_s": round(sum(e["duration_s"] for e in es), 1),
                "share": round(sum(e["duration_s"] for e in es) / wall, 3)
                if wall
                else None,
                "host_cpu_busy": weighted(es, "host_cpu_busy"),
                "guest_cpu_busy": weighted(es, "guest_cpu_busy"),
            }
            for p, es in sorted(
                phases.items(), key=lambda kv: -sum(e["duration_s"] for e in kv[1])
            )
        },
        "slowest": sorted(events, key=lambda e: -e["duration_s"])[:10],
        "llm": {
            "requests": len(llm),
            "failed_requests": sum(
                1 for e in phases.get("llm", []) if e.get("ok") is False
            ),
            "prompt_tokens": sum(e.get("prompt_tokens") or 0 for e in llm),
            "completion_tokens": sum(e.get("completion_tokens") or 0 for e in llm),
            "cost_usd": round(sum(e.get("cost_usd") or 0 for e in llm), 4),
            "s_per_request": round(sum(e["duration_s"] for e in llm) / len(llm), 1)
            if llm
            else None,
        },
        "host_load1": [
            e["host_load1"] for e in events if e.get("host_load1") is not None
        ],
        "host_cpus": max((e.get("host_cpus") or 0 for e in events), default=0),
    }


def pct(x: float | None) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def show(s: dict) -> str:
    load = s["host_load1"]
    lines = [
        (
            f"wall {s['wall_s']}s, not in any step {s['unaccounted_s']}s; "
            f"host load {min(load, default=0):.0f}-{max(load, default=0):.0f} on {s['host_cpus']} CPUs"
        ),
        "",
        f"{'phase':<9} {'steps':>5} {'total':>8} {'share':>6} {'host':>5} {'guest':>5}",
    ]
    for p, v in s["phases"].items():
        lines.append(
            f"{p:<9} {v['steps']:>5} {v['total_s']:>7}s {pct(v['share']):>6} "
            f"{pct(v['host_cpu_busy']):>5} {pct(v['guest_cpu_busy']):>5}"
        )
    m = s["llm"]
    lines += [
        "",
        (
            f"model: {m['requests']} requests ({m['failed_requests']} failed), "
            f"{m['s_per_request']}s each, {m['prompt_tokens']} prompt + "
            f"{m['completion_tokens']} reply tokens, ${m['cost_usd']}"
        ),
        "",
        "slowest steps:",
    ]
    for e in s["slowest"]:
        what = e.get("cmd") or e.get("error") or ""
        lines.append(
            f"  {e['duration_s']:>7.1f}s  {e['phase']}/{e['name']:<14} host {pct(e.get('host_cpu_busy')):>4} "
            f"guest {pct(e.get('guest_cpu_busy')):>4}  {' '.join(str(what).split())[:70]}"
        )
    return "\n".join(lines)


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    s = summary(load(a.run_dir))
    print(json.dumps(s) if a.json else show(s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
