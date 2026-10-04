#!/usr/bin/env bash
# BenchPilot v1 starter. Creates venv, installs deps, runs the server.
set -e
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
.venv/bin/pip install -q -r requirements.txt

echo "BenchPilot starting at http://127.0.0.1:8741"
echo "(optional) export BENCHPILOT_PASSWORD='...' to gate the UI with HTTP basic auth"
.venv/bin/python -m uvicorn app.server:app --host 127.0.0.1 --port 8741
