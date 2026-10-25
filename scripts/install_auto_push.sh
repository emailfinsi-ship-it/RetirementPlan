#!/bin/bash
# One-time setup: a LaunchAgent that runs scripts/auto_push.sh every 5 minutes (and when you log in),
# so commits made in master / version2 / version3 reach GitHub by themselves.
#   bash scripts/install_auto_push.sh            install
#   bash scripts/install_auto_push.sh --remove   turn it off again
set -e
LABEL="com.finsi.autopush"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
REPO="${FINSI_REPO:-/Users/Shared/RetirementPlan/Code}"
if [ "${1:-}" = "--remove" ]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"; echo "Auto-push turned off."; exit 0
fi
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$REPO/scripts/auto_push.sh</string></array>
  <key>StartInterval</key><integer>300</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardErrorPath</key><string>$HOME/Library/Logs/finsi-auto-push.err</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "Auto-push is on: master, version2 and version3 are pushed to GitHub every 5 minutes when they have new commits."
echo "Log: $HOME/Library/Logs/finsi-auto-push.log   Turn off: bash scripts/install_auto_push.sh --remove"
echo "Checking now:"; bash "$REPO/scripts/auto_push.sh" --dry-run
