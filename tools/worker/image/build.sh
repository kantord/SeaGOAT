#!/usr/bin/env bash
# Builds the worker's image from the repo at a commit (default HEAD) and loads it into the
# worker's microsandbox home as seagoat-worker:latest: `tools/worker/image/build.sh [<commit>]`.
# About 15 minutes, most of it the warming verify run inside the build.
set -euo pipefail
commit=${1:-HEAD}
here=$(cd "$(dirname "$0")" && pwd)
repo=$(git -C "$here" rev-parse --show-toplevel)
full=$(git -C "$repo" rev-parse "$commit^{commit}")
export MSB_HOME=${MSB_HOME:-$HOME/.cache/seagoat-worker/msb}
mkdir -p "$repo/target/agent-tmp"
tmp=$(mktemp -d -p "$repo/target/agent-tmp")
trap 'rm -rf "$tmp"' EXIT

mkdir "$tmp/repo"
git -C "$repo" archive "$full" | tar -x -C "$tmp/repo"
# verify.sh from this checkout, not the commit: a commit from before the worker has none.
cp "$here/Containerfile" "$here/../verify.sh" "$tmp/"
podman build --label commit="$full" -t localhost/seagoat-worker:latest "$tmp"
podman save --format oci-archive -o "$tmp/image.tar" localhost/seagoat-worker:latest
msb load -i "$tmp/image.tar" -t seagoat-worker:latest
# Drop only this script's earlier builds that the new one untagged (they carry the commit
# label), not the host's other dangling images; the tagged image stays as the layer cache.
podman image prune -f --filter label=commit >/dev/null
echo "seagoat-worker:latest is ${full:0:12}"
