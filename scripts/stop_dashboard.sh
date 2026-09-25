#!/bin/bash
# Stops the Retirement Plan dashboard by finding whatever process is bound
# to its port (127.0.0.1:8898 -- see source.webapp.dashboard.PORT) and
# signaling it, same idea as Ctrl+C in the Terminal window running
# scripts/run_dashboard.sh, so it hits that script's own
# "except KeyboardInterrupt" and shuts down its ThreadingHTTPServer
# cleanly instead of just being killed outright.
#
# Usage: ./scripts/stop_dashboard.sh [port]   (defaults to 8898)
set -e
PORT="${1:-8898}"

PIDS=$(lsof -ti tcp:"$PORT" 2>/dev/null || true)

if [ -z "$PIDS" ]; then
  echo "Nothing is listening on port $PORT -- dashboard is not running."
  exit 0
fi

echo "Stopping Retirement Plan dashboard (pid: $PIDS)..."
kill -INT $PIDS 2>/dev/null || true

for _ in 1 2 3 4 5; do
  sleep 1
  if ! lsof -ti tcp:"$PORT" >/dev/null 2>&1; then
    echo "Stopped."
    exit 0
  fi
done

echo "Still running after 5s -- forcing stop."
kill -9 $PIDS 2>/dev/null || true
echo "Stopped."
