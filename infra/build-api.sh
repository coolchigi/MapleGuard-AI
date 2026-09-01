#!/usr/bin/env bash
# Package the FastAPI API for the API Lambda (api/lambda_handler.py) into build/api_pkg/.
#
# The API Lambda needs only the web-serving deps (FastAPI + Mangum + Anthropic-Bedrock +
# Pydantic); boto3 is provided by the Lambda runtime, and strands is NOT needed (agent.tools
# imports it lazily and falls back). We install those as linux/x86_64 wheels (the Lambda arch),
# then copy the pure-Python server source. `make api-package` runs this before `terraform apply`.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
SERVER="$HERE/../server"
PKG="$HERE/build/api_pkg"
PY_VERSION="3.12"

rm -rf "$PKG"
mkdir -p "$PKG"

# Deploy deps as manylinux x86_64 wheels so compiled packages (pydantic-core, jiter) match the
# Lambda runtime, regardless of the machine running this build.
python3 -m pip install \
  --platform manylinux2014_x86_64 --implementation cp --python-version "$PY_VERSION" \
  --only-binary=:all: --upgrade --target "$PKG" \
  fastapi mangum "anthropic>=0.39" "pydantic>=2.6"

# The server source (pure Python; no tests, caches, or the agent/API-only-at-runtime bits).
for mod in crs pnp paths noc ingest agent api; do
  rsync -a --exclude '__pycache__' --exclude 'tests' --exclude '._*' \
    "$SERVER/$mod" "$PKG/"
done

echo "built $PKG ($(du -sh "$PKG" | cut -f1))"
