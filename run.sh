#!/usr/bin/env bash
set -euo pipefail
app_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$app_dir"
if [[ ! -x .venv/bin/python ]] || ! cmp -s requirements.lock .venv/installed-requirements.lock; then
  bash install.sh
fi
# This package serves checkout directly at / in its own Replit project.
export STREAMBOT_BASE_PATH=''
export STREAMBOT_HOST='0.0.0.0'
# Trust Replit's final forwarding hop only when running inside Replit.
if [[ -n "${REPLIT_DEV_DOMAIN:-}${REPLIT_DEPLOYMENT:-}${REPL_ID:-}" ]]; then
  export STREAMBOT_TRUST_PROXY='true'
fi
exec .venv/bin/python replit_start.py "$@"
