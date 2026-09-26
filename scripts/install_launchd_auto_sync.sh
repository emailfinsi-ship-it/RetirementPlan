#!/bin/bash
# Optional: a REAL background schedule for Plaid syncing -- one that runs
# even on a day you never open the Retirement Plan dashboard at all.
#
# source.collector.auto_sync (the "Automatic sync" card on the Setup
# page) already catches up automatically the moment you next open the
# app if it's gone stale, with zero setup -- that covers most people.
# This script is only for the stronger guarantee: "sync every month, no
# matter what, whether or not I ever open the app that day." It does that
# by installing a macOS launchd user agent -- the standard, supported way
# any Mac app runs something on a schedule in the background.
#
# What this installs:
#   - ~/Library/LaunchAgents/com.retirementplan.autosync.plist, a launchd
#     job that runs `venv/bin/python -m source.collector.sync` (a
#     headless sync -- no dashboard, no browser tab, just pulls fresh
#     Plaid data into your database) once a month, plus once a day it
#     misses (e.g. this Mac was asleep at the scheduled time -- launchd's
#     StartCalendarInterval runs the job the next time the Mac is awake
#     rather than skipping it entirely).
#   - Logs go to logs/auto_sync_launchd.log next to this script, so you
#     can check whether it's actually been running.
#
# Run this yourself, once, in your own Terminal:
#   cd ~/Downloads/RetirementPlan/Code   # or wherever you extracted it
#   bash scripts/install_launchd_auto_sync.sh
#
# It edits nothing outside your own home folder (~/Library/LaunchAgents
# is a normal per-user location, not a system-wide one), and only runs
# after you review it and load it yourself -- this script prints the
# `launchctl load` command at the end rather than running it for you, so
# you can read the generated plist first if you'd like.
#
# To remove it later:
#   launchctl unload ~/Library/LaunchAgents/com.retirementplan.autosync.plist
#   rm ~/Library/LaunchAgents/com.retirementplan.autosync.plist

set -e
cd "$(dirname "$0")/.."
CODE_DIR="$(pwd)"
PLIST_LABEL="com.retirementplan.autosync"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_LABEL}.plist"
LOG_PATH="$CODE_DIR/logs/auto_sync_launchd.log"

if [ ! -x "$CODE_DIR/venv/bin/python" ]; then
  echo "No venv found at $CODE_DIR/venv -- run scripts/run_dashboard.sh at least once first to set it up." >&2
  exit 1
fi

mkdir -p "$CODE_DIR/logs"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${PLIST_LABEL}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${CODE_DIR}/venv/bin/python</string>
        <string>-m</string>
        <string>source.collector.sync</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${CODE_DIR}</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Day</key>
        <integer>1</integer>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>${LOG_PATH}</string>
    <key>StandardErrorPath</key>
    <string>${LOG_PATH}</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

echo "Wrote $PLIST_PATH"
echo "It's set to run on the 1st of every month at 9:00am (launchd catches up automatically if your Mac is asleep or off at that moment, next time it wakes)."
echo
echo "Review the file above, then load it yourself with:"
echo "  launchctl load \"$PLIST_PATH\""
echo
echo "To run it once right now (to confirm it works) instead of waiting for the schedule:"
echo "  launchctl start ${PLIST_LABEL}"
echo "  tail -f \"$LOG_PATH\""
