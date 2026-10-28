#!/usr/bin/env python3
"""Run one task through the sandboxed worker and, if it comes back green, leave its patch in a worktree.

    python3 tools/worker/run.py <slug> --brief path/to/brief.md [--base HEAD] [--budget s]

Steps: check that the image is loaded (tools/worker/image/build.sh builds and loads it), run
tools/worker against a copy of the repo at --base, and if the run is GREEN apply its patch in
`.claude/worktrees/worker-<slug>` (branch `worker/<slug>`), unstaged, for the calling session
to review and commit. Inside the sandbox the worker has already run tools/worker/verify.sh.
Everything a run writes is under `target/agent-tmp/worker/<slug>-<time>/` (`run.log` is the
live table: `tail -f` it).

The API URL, model and extra request fields come from ~/.config/seagoat-worker/config.toml,
outside the repo, so which gateway and model are used is not part of it:

    api_url = "https://example.com/v1/chat/completions"
    model = "some/model"
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
import datetime
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

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


def build_worker() -> Path:
    subprocess.run(
        ["nice", "-n", "19", "cargo", "build", "--release", "-q"],
        cwd=WORKER,
        check=True,
    )
    return WORKER / "target/release/seagoat-worker"


def apply_in_worktree(slug: str, base: str, patch: Path) -> Path:
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
    return tree


def main(argv) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("slug", help="short name: the branch is worker/<slug>")
    ap.add_argument("--brief", type=Path, required=True)
    ap.add_argument("--base", default="HEAD")
    ap.add_argument("--budget", type=int, default=3600)
    ap.add_argument("--cpus", type=int, default=4)
    ap.add_argument("--model", help="overrides the config file's")
    ap.add_argument(
        "--verify-cmd", help="default: the worker's, tools/worker/verify.sh"
    )
    a = ap.parse_args(argv)
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
        "--repo", str(ROOT), "--base", base, "--task", str(brief), "--image", IMAGE,
        "--out", str(out / "run"), "--budget", str(a.budget), "--cpus", str(a.cpus),
    ]  # fmt: skip
    cmd += ["--api-url", config["api_url"], "--model", a.model or config["model"]]
    cmd += ["--extra-body", json.dumps(config.get("extra_body", {}))]
    if a.verify_cmd:
        cmd += ["--verify-cmd", a.verify_cmd]
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
        report.get("status") != "GREEN"
        or not patch.is_file()
        or patch.stat().st_size == 0
    ):
        print(f"worker: no green patch; see {out}", flush=True)
        return 1
    tree = apply_in_worktree(a.slug, base, patch)
    print(f"worker: changes uncommitted in {tree}", flush=True)
    print(git("status", "--short", cwd=tree), end="", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
