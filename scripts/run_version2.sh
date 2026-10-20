#!/bin/bash
# Runs Version 2 (this folder) next to your normal app, so you can compare.
# It has its own copy of the data (data/ in this folder) and its own port,
# 8899, so your original app on 8898 and its database are not touched.
#
#   Start:  ./scripts/run_version2.sh        Stop: ./scripts/stop_dashboard.sh 8899
set -e
cd "$(dirname "$0")/.."
PY="../Code/venv/bin/python"
[ -x "$PY" ] || PY="venv/bin/python"
export FINSI_PORT=8899
echo "Version 2 is starting at http://127.0.0.1:8899/ (your original app on 8898 is not affected)"
exec "$PY" -m source.webapp.dashboard
