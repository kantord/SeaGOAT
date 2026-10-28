#!/usr/bin/env bash
# The worker's gate: what CI runs (.github/workflows/lint.yml and test.yml) as one command.
# Runs in the guest, where the worker calls it after `git add -A` so pre-commit sees new files,
# and works the same on the host. About 7 minutes, nearly all of it pytest.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
uv sync --locked --quiet
uv run pre-commit run --all-files
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --locked
uv run pytest . -q -p no:sugar --timeout=300
