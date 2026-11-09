#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$app_dir"
python_bin="${STREAMBOT_PYTHON:-python3}"
# This package serves checkout directly at / in its own Replit project.
export STREAMBOT_BASE_PATH=''
export STREAMBOT_HOST="${STREAMBOT_HOST:-0.0.0.0}"
# Trust Replit's final forwarding hop only when running inside Replit.
if [[ -n "${REPLIT_DEV_DOMAIN:-}${REPLIT_DEPLOYMENT:-}${REPL_ID:-}" ]]; then
  export STREAMBOT_TRUST_PROXY='true'
fi
exec "$python_bin" replit_start.py "$@"
