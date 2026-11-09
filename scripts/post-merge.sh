#!/bin/bash
set -e
pnpm install --frozen-lockfile
# Streamline owns its existing database schemas. Never push the empty
# scaffold schema over them or perform production DDL during a port.
python3 -c 'import flask, requests, bs4, cryptography, waitress, dotenv, qrcode, psycopg'
bash scripts/restore-demo-state.sh
