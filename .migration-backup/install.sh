#!/usr/bin/env bash
set -euo pipefail
project_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$project_dir"
python_bin="${STREAMBOT_PYTHON:-python3}"
"$python_bin" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ is required; add a Python system module to this Replit project."'
# Replit installs requirements.txt in its managed dependency layer before Build.
# pip's default target is the immutable Nix system environment during publishing.
# Validate the prepared dependencies here; never install into /nix/store.
"$python_bin" -c 'import flask, requests, bs4, cryptography, waitress, dotenv, qrcode, psycopg'
"$python_bin" -m compileall -q streambot replit_start.py
printf '%s\n' 'Ready. Click Run, or start with: bash run.sh'
