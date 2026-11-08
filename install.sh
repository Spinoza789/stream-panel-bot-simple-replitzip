#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
python_bin="${STREAMBOT_PYTHON:-python3}"
"$python_bin" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required; add a Python system module to this Replit project."'
if [[ ! -x .venv/bin/python ]]; then
  if ! "$python_bin" -m venv .venv; then
    if command -v uv >/dev/null 2>&1; then
      uv venv --seed --python "$python_bin" .venv
    elif "$python_bin" -m virtualenv --version >/dev/null 2>&1; then
      "$python_bin" -m virtualenv .venv
    else
      printf '%s\n' 'Enable a Python system module with venv, or install uv/virtualenv, then rerun this installer.' >&2
      exit 1
    fi
  fi
fi
.venv/bin/python -m pip install --disable-pip-version-check -r requirements.lock
.venv/bin/python -m compileall -q streambot replit_start.py
cp requirements.lock .venv/installed-requirements.lock
printf '%s\n' 'Ready. Click Run, or start with: bash run.sh'
