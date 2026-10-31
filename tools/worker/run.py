#!/usr/bin/env python3
"""Run one task through the sandboxed worker and, if it comes back green, leave its patch in a worktree.

    python3 tools/worker/run.py <slug> --brief path/to/brief.md [--program p.json] [--base HEAD]

The program says what the run does: messages to the model, the model's turns, and the checks
the harness runs, as JSON steps (tools/worker/src/program.rs has the four kinds). The default,
tools/worker/programs/default.json, has the model work, then checks that something changed,
lints the changed files and runs tools/worker/verify.sh, retrying twice. For a quicker run,
copy it and change the checks. A run ends by counts (turns, retries), not by a time budget.

Steps: check that the image is loaded (tools/worker/image/build.sh builds and loads it), run
tools/worker against a copy of the repo at --base, and if the run is GREEN apply its patch in
`.claude/worktrees/worker-<slug>` (branch `worker/<slug>`), unstaged, for the calling session
to review and commit. Inside the sandbox the worker has already run the program's checks.
Everything a run writes is under `target/agent-tmp/worker/<slug>-<time>/` (`run.log` is the
live table: `tail -f` it). `run/events.jsonl` times every step with the machine's load
(tools/worker/timings.py summarizes it; run.py prints that at the end).

The API URL, model and extra request fields come from ~/.config/seagoat-worker/config.toml,
outside the repo, so which gateway and model are used is not part of it:

    api_url = "https://example.com/v1/chat/completions"
    model = "some/model"
    pin_provider = false   # optional; on by default: keep the first reply's provider
    [extra_body]   # optional, merged into every request body as-is

The key is read from ~/.config/seagoat-worker/api-key and handed to the worker in its
environment only; it is never printed.

Several tasks in parallel are several invocations with different slugs; each boots its own
sandbox. Mind --cpus: the machine is shared by all of them.

DECISION: no second verify on the host after the patch is applied: the guest runs the same
checks CI does.
Standard library only.
"""

import argparse
import contextlib
import datetime
import json
import os
import re
import subprocess
import sys
import time
import tomllib
from pathlib import Path

import timings

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "tools/worker"
MSB_HOME = Path.home() / ".cache/seagoat-worker/msb"
CONFIG_FILE = Path.home() / ".config/seagoat-worker/config.toml"
KEY_FILE = Path.home() / ".config/seagoat-worker/api-key"
IMAGE = "seagoat-worker:latest"


def git(*args, cwd=ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def image_loaded(image: str) -> bool:
    env = {**os.environ, "MSB_HOME": str(MSB_HOME)}
    return (
        subprocess.run(
            ["msb", "image", "inspect", image],
            env=env,
            capture_output=True,
            check=False,
        ).returncode
        == 0
    )


def host_cpu() -> tuple[int, int] | None:
    """(busy, total) clock ticks from /proc/stat, as events.rs reads them."""
    try:
        n = [int(v) for v in Path("/proc/stat").read_text().split("\n")[0].split()[1:9]]
    except (OSError, ValueError):
        return None
    return sum(n) - n[3] - n[4], sum(n)


@contextlib.contextmanager
def step(events: Path, phase: str, name: str):
    """One event in the run's events.jsonl, in events.rs's format; yields a dict for extra fields."""
    fields: dict = {}
    ts, t0, cpu0 = time.time(), time.monotonic(), host_cpu()
    try:
        yield fields
    finally:
        cpu1 = host_cpu()
        busy = None
        if cpu0 and cpu1 and cpu1[1] > cpu0[1]:
            busy = round((cpu1[0] - cpu0[0]) / (cpu1[1] - cpu0[1]), 3)
        event = {
            "ts": round(ts, 3), "phase": phase, "name": name,
            "duration_s": round(time.monotonic() - t0, 3),
            "host_cpu_busy": busy, "host_load1": os.getloadavg()[0],
            "host_cpus": os.cpu_count(), **fields,
        }  # fmt: skip
        events.parent.mkdir(parents=True, exist_ok=True)
        with events.open("a") as f:
            f.write(json.dumps(event) + "\n")


# Fragments older than this are deleted before a run. A program's own max_age_s may be shorter;
# this only stops the folder from growing forever.
ONCE_KEEP_SECONDS = 7 * 24 * 3600


def prune_once(once_dir: Path):
    for fragment in once_dir.glob("*.json"):
        with contextlib.suppress(OSError):
            if time.time() - fragment.stat().st_mtime > ONCE_KEEP_SECONDS:
                fragment.unlink()


def print_timings(out: Path):
    try:
        print(timings.show(timings.summary(timings.load(out))), flush=True)
    except (OSError, ValueError) as e:
        print(f"worker: no timings ({e})", flush=True)


def build_worker() -> Path:
    subprocess.run(
        ["nice", "-n", "19", "cargo", "build", "--release", "--locked", "-q"],
        cwd=WORKER,
        check=True,
    )
    return WORKER / "target/release/seagoat-worker"


# DECISION: the patch is model output, and some files run without anyone running them. Paths
# that a tool runs on opening the worktree (Claude Code's settings and hooks, direnv, editors) are
# refused outright. Paths that run on a build, test or commit, or that make up the gate itself,
# are applied but named, so they get read first. Nothing here makes the rest safe to run unread.
# CLAUDE.md and AGENTS.md load into the session that reviews the worktree: prompt injection on open.
RUN_ON_OPEN = (
    ".claude/",
    ".mcp.json",
    ".envrc",
    ".vscode/",
    ".idea/",
    "CLAUDE.md",
    "CLAUDE.local.md",
    "AGENTS.md",
    ".nvim.lua",
    ".exrc",
)
RUN_ON_USE = (
    "conftest.py", "build.rs", "pyproject.toml", "Cargo.toml", "uv.lock", "Cargo.lock",
    ".cargo/", "pytest.ini", "tox.ini", "setup.cfg",
    ".pre-commit-config.yaml", ".github/", "tools/worker/",
)  # fmt: skip


def patch_paths(patch: Path) -> list[str]:
    out = git("apply", "--numstat", "-z", str(patch))
    # Each entry is "added<TAB>deleted<TAB>path"; the guest makes the patch with --no-renames.
    return [e.split("\t", 2)[2] for e in out.split("\0") if e]


def patch_symlinks(patch: Path) -> list[str]:
    """The paths the patch makes into symlinks.

    A symlink would let a refused path through under another name: `.claude -> evil` plus
    `evil/settings.json` is Claude Code's settings file, though neither path matches.
    """
    out = git("apply", "--summary", str(patch))
    # " create mode 120000 path" or " mode change 100644 => 120000 path"
    return [
        line.split(" 120000 ", 1)[1]
        for line in out.splitlines()
        if " 120000 " in line and ("create mode" in line or "=> 120000" in line)
    ]


def risky(paths: list[str]) -> tuple[list[str], list[str]]:
    """(refused, to read first): the paths that match RUN_ON_OPEN and RUN_ON_USE.

    A pattern ending in / matches everything under a directory of that name anywhere (a nested
    .cargo/config.toml counts); any other matches a file of that name anywhere.
    """

    def matches(path: str, pattern: str) -> bool:
        if pattern.endswith("/"):
            # The trailing / also matches the directory itself (a symlink, or a file in its place)
            return f"/{path}/".find(f"/{pattern}") >= 0
        return Path(path).name == pattern

    def hits(patterns) -> list[str]:
        return [p for p in paths if any(matches(p, x) for x in patterns)]

    return hits(RUN_ON_OPEN), hits(RUN_ON_USE)


def apply_in_worktree(slug: str, base: str, patch: Path) -> Path:
    refused, read_first = risky(patch_paths(patch))
    refused += [f"{p} (a symlink)" for p in patch_symlinks(patch)]
    if refused:
        sys.exit(
            f"worker: the patch touches files that run when the worktree is opened: "
            f"{', '.join(refused)}; not applied. Read {patch}"
        )
    tree = ROOT / ".claude/worktrees" / f"worker-{slug}"
    git("worktree", "add", "-q", str(tree), "-b", f"worker/{slug}", base)
    done = subprocess.run(
        ["git", "apply", "--3way", str(patch)],
        cwd=tree,
        capture_output=True,
        text=True,
        check=False,
    )
    if done.returncode != 0:
        sys.exit(
            f"worker: the patch did not apply cleanly; resolve in {tree}\n{done.stderr}"
        )
    git(
        "reset", "-q", cwd=tree
    )  # leave the change unstaged, as a person's edit would be
    if read_first:
        print(
            f"worker: READ FIRST, these run on build, test or commit, or are the gate: "
            f"{', '.join(read_first)}",
            flush=True,
        )
    return tree


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("slug", help="short name: the branch is worker/<slug>")
    ap.add_argument("--brief", type=Path, required=True)
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--cpus", type=int, default=4)
    ap.add_argument("--model", help="overrides the config file's")
    ap.add_argument("--program", type=Path, default=WORKER / "programs/default.json")
    a = ap.parse_args(argv)
    # The slug becomes a path and a branch name.
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", a.slug):
        sys.exit(
            f"worker: slug {a.slug!r} must be lowercase letters, digits and dashes"
        )
    base = git("rev-parse", a.base).strip()
    if git("branch", "--list", f"worker/{a.slug}").strip():
        sys.exit(
            f"worker: branch worker/{a.slug} exists; pick another slug or delete it"
        )
    if not image_loaded(IMAGE):
        sys.exit(
            f"worker: no image {IMAGE} in {MSB_HOME}; run tools/worker/image/build.sh first"
        )
    if not KEY_FILE.is_file():
        sys.exit(f"worker: no API key at {KEY_FILE}")
    if not CONFIG_FILE.is_file():
        sys.exit(f"worker: no config at {CONFIG_FILE}; see this script's docstring")
    with CONFIG_FILE.open("rb") as f:
        config = tomllib.load(f)
    missing = [k for k in ("api_url", "model") if k not in config]
    if missing:
        sys.exit(f"worker: {CONFIG_FILE} lacks {', '.join(missing)}")
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = ROOT / "target/agent-tmp/worker" / f"{a.slug}-{stamp}"
    out.mkdir(parents=True)
    brief = out / "brief.md"
    brief.write_text(a.brief.read_text())
    program = out / "program.json"
    program.write_text(a.program.read_text())
    events = out / "run/events.jsonl"
    with step(events, "host", "build_worker"):
        binary = build_worker()
    log = out / "run.log"
    print(
        f"worker: {a.slug} on {base[:8]}, image {IMAGE}; watch: tail -f {log}",
        flush=True,
    )
    env = {
        **os.environ,
        "MSB_HOME": str(MSB_HOME),
        "SEAGOAT_WORKER_API_KEY": KEY_FILE.read_text().strip(),
        "CLICOLOR_FORCE": "1",
    }
    cmd = [
        "nice", "-n", "19", "ionice", "-c3", str(binary),
        "--repo", str(ROOT), "--base", base, "--task", str(brief), "--program", str(program),
        "--image", IMAGE,
        "--out", str(out / "run"), "--cpus", str(a.cpus),
    ]  # fmt: skip
    cmd += ["--api-url", config["api_url"], "--model", a.model or config["model"]]
    cmd += ["--extra-body", json.dumps(config.get("extra_body", {}))]
    cmd += ["--pin-provider", "true" if config.get("pin_provider", True) else "false"]
    once_dir = ROOT / "target/agent-tmp/once"
    prune_once(once_dir)
    cmd += ["--once-dir", str(once_dir)]
    with log.open("w") as f:
        code = subprocess.run(cmd, env=env, stderr=f, stdout=f, check=False).returncode
    run_json = out / "run/run.json"
    report = json.loads(run_json.read_text()) if run_json.is_file() else {}
    print(
        f"worker: exit {code}, status {report.get('status')}, {report.get('turns')} turns, "
        f"${report.get('cost_usd', 0):.3f}",
        flush=True,
    )
    patch = out / "run/patch"
    if (
        report.get("status") == "GREEN"
        and patch.is_file()
        and patch.stat().st_size == 0
    ):
        # A program with checks only (programs/gate.json) changes nothing by design.
        print("worker: GREEN, nothing to apply", flush=True)
        print_timings(out)
        return 0
    if (
        report.get("status") != "GREEN"
        or not patch.is_file()
        or patch.stat().st_size == 0
    ):
        print(f"worker: no green patch; see {out}", flush=True)
        print_timings(out)
        return 1
    with step(events, "host", "apply"):
        tree = apply_in_worktree(a.slug, base, patch)
    print(
        f"worker: changes uncommitted in {tree}; read the diff before running anything there",
        flush=True,
    )
    print(git("status", "--short", cwd=tree), end="", flush=True)
    print_timings(out)
    print(
        f"worker: every step is in {events}; tools/worker/timings.py {out} shows this again",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
