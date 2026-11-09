#!/usr/bin/env bash
# Preserve the original local demo DB and encryption key as a pair, without
# reading them or ever touching live PostgreSQL. Safe to repeat after a merge.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source="$root/.migration-backup/data"
target="$root/artifacts/api-server/python/data"
if [[ -e "$target/demo.sqlite3" || -e "$target/demo.key" ]]; then
  if [[ ! -f "$target/demo.sqlite3" || ! -f "$target/demo.key" ]]; then
    printf '%s\n' 'Demo state is incomplete. Restore its matching database and key before startup.' >&2
    exit 1
  fi
  exit 0
fi
if [[ -f "$source/demo.sqlite3" && -f "$source/demo.key" ]]; then
  umask 077
  mkdir -p "$target"
  cp -p "$source/demo.sqlite3" "$source/demo.key" "$target/"
fi
