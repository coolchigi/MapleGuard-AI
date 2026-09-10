#!/usr/bin/env bash
# Package the monitor for the monitor Lambda (agent.monitor_lambda.lambda_handler) into
# build/monitor_pkg/.
#
# The monitor is NOT pure source: agent/schemas.py imports typing_extensions at module load, and
# the opt-in policy watch (MAPLEGUARD_POLICY_URL) needs anthropic for the Bedrock classifier +
# matcher. Without these in the package the Lambda either fails to import (typing_extensions) or
# silently skips policy classification (anthropic absent -> build_bedrock_noc_clients returns None).
# boto3 is provided by the Lambda runtime; strands is imported lazily and not needed here.
#
# We install the deps as linux/x86_64 wheels (the Lambda arch), then copy the pure-Python source.
# `make monitor-package` runs this before `terraform apply`.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/../server"
PKG="$HERE/build/monitor_pkg"
PY_VERSION="3.12"

rm -rf "$PKG"
mkdir -p "$PKG"

# Deploy deps as manylinux x86_64 wheels so compiled packages (pydantic-core, jiter) match the
# Lambda runtime, regardless of the machine running this build.
python3 -m pip install \
  --platform manylinux2014_x86_64 --implementation cp --python-version "$PY_VERSION" \
  --only-binary=:all: --upgrade --target "$PKG" \
  "anthropic>=0.39" "typing_extensions>=4.0"

# The server source the monitor imports (pure Python). No api/, no tests, no caches. The monitor
# entrypoint is agent/monitor_lambda.py; it reaches crs/pnp/paths/noc/ingest through agent.
for mod in crs pnp paths noc ingest agent; do
  rsync -a --exclude '__pycache__' --exclude 'tests' --exclude '._*' \
    "$SERVER/$mod" "$PKG/"
done

echo "built $PKG ($(du -sh "$PKG" | cut -f1))"
