#!/bin/bash
# Runs the dashboard in DEMO MODE: a built-in sample household in a
# throwaway data folder, on its own port (http://127.0.0.1:8897/), with no
# login. It never reads or writes your real database, so it is safe for
# demos, screenshots and investor walk-throughs. Use "Hide balances" in the
# page header too if you ever demo with real data.
set -e
cd "$(dirname "$0")/.."
export FINSI_DEMO=1
exec bash scripts/run_dashboard.sh
