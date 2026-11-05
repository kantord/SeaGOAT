#!/usr/bin/env bash
# Runs the msb CLI whose version matches the microsandbox SDK the worker is built with:
# `tools/worker/msb.sh <msb args...>`, with MSB_HOME set by the caller.
#
# msb upgrades a sandbox database to its own schema whenever it touches it, even for a
# read-only `image inspect`, and an older msb then refuses that database. So the CLI used
# on the worker's MSB_HOME must never be newer than the SDK pinned in Cargo.toml.
#
# Prefers the copy the SDK installs into $MSB_HOME/bin on the worker's first boot. Before
# that exists (a fresh machine), the msb on PATH is used only if its version is exactly the
# pinned one.
set -euo pipefail
: "${MSB_HOME:?MSB_HOME must be set}"
bundled="$MSB_HOME/bin/msb"
if [[ -x "$bundled" ]]; then
	exec "$bundled" "$@"
fi
here=$(cd "$(dirname "$0")" && pwd)
pinned=$(sed -n 's/^microsandbox = { version = "=\([^"]*\)".*/\1/p' "$here/Cargo.toml")
found=$(msb --version 2>/dev/null | awk '{print $2}' || true)
if [[ -z "$pinned" || "$found" != "$pinned" ]]; then
	echo "worker: no msb in $MSB_HOME/bin, and the msb on PATH is ${found:-missing}, not" \
		"${pinned:-the version pinned in tools/worker/Cargo.toml}. Install msb $pinned" \
		"(e.g. into a directory first on PATH) and retry." >&2
	exit 1
fi
exec msb "$@"
