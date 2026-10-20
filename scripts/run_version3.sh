#!/bin/bash
# Runs Version 3 (this folder) next to your normal app and Version 2, so you can compare.
# It has its own copy of the data (data/ in this folder) and its own port, 8900,
# so your original app (8898) and Version 2 (8899) and their databases are not touched.
#
#   Start:  ./scripts/run_version3.sh        Stop: ./scripts/stop_dashboard.sh 8900
set -e
cd "$(dirname "$0")/.."
PY="../Code/venv/bin/python"
[ -x "$PY" ] || PY="venv/bin/python"
export FINSI_PORT=8900
echo "Version 3 is starting at http://127.0.0.1:8900/ (your other copies are not affected)"
exec "$PY" -m source.webapp.dashboard
