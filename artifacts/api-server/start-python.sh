#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/python"
# The managed artifact assigns PORT; the legacy launcher uses STREAMBOT_PORT.
export STREAMBOT_PORT="${PORT:?The API artifact must provide PORT}"
if [[ "${1:-}" == "--demo" ]]; then
  bash ../../../scripts/restore-demo-state.sh
  export STREAMBOT_MODE=demo
  export STREAMBOT_TELEGRAM_ENABLED=false
  export STREAMBOT_LIVE_PAYMENTS_ENABLED=false
  export STREAMBOT_PANEL_WRITE_ENABLED=false
  # A production origin must not break same-origin requests in the preview.
  unset STREAMBOT_PUBLIC_URL
fi
exec bash run.sh
