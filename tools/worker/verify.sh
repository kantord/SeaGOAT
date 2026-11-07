#!/usr/bin/env bash
# The worker's gate: what CI runs (.github/workflows/lint.yml and test.yml) as one command.
# Runs in the guest, where the worker calls it after `git add -A` so prek sees new files,
# and works the same on the host. About 7 minutes, nearly all of it pytest.
# `--warm` (the image build) stops before pytest: the tests fill no cache, and were about half
# of the build (2026-11-07: 2m47s of about 6 minutes).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
uv sync --locked --quiet
uv run prek run --all-files
cargo fmt --check
cargo clippy --all-targets --locked -- -D warnings
cargo test --locked
if [[ ${1:-} == --warm ]]; then
  # The one thing pytest left in the image: the ONNX model that conftest.py downloads
  uv run python -c 'from chromadb.utils.embedding_functions.onnx_mini_lm_l6_v2 import ONNXMiniLM_L6_V2; ONNXMiniLM_L6_V2()(["warm"])'
  exit 0
fi
uv run pytest . -q -p no:sugar --timeout=300
