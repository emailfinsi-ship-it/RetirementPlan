#!/bin/bash
# Pushes master, version2 and version3 to GitHub when any of them has commits GitHub does not.
# Runs on this Mac (so it uses the GitHub login your own Keychain already holds), normally every few
# minutes from the LaunchAgent that scripts/install_auto_push.sh sets up. It only ever does a plain
# push: it never forces, never rewrites history and never asks for a password (if the login is
# missing or expired it just writes that to the log and tries again next time).
#
#   bash scripts/auto_push.sh            push what is ahead
#   bash scripts/auto_push.sh --dry-run  only say what would be pushed
set -u
REPO="${FINSI_REPO:-/Users/Shared/RetirementPlan/Code}"
LOG="${FINSI_PUSH_LOG:-$HOME/Library/Logs/finsi-auto-push.log}"
BRANCHES=(master version2 version3)
DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1
mkdir -p "$(dirname "$LOG")"
say() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; [ "$DRY" = 1 ] && echo "$*"; return 0; }

cd "$REPO" 2>/dev/null || { say "repo not found: $REPO"; exit 0; }
export GIT_TERMINAL_PROMPT=0     # never sit waiting for a password prompt
# Another git command (a commit, a merge) is mid-way: try again next time.
if [ -e .git/index.lock ] || [ -e .git/HEAD.lock ]; then say "git is busy; will retry"; exit 0; fi

ahead=()
for b in "${BRANCHES[@]}"; do
  git rev-parse --verify -q "refs/heads/$b" >/dev/null || continue
  remote="refs/remotes/origin/$b"
  if ! git rev-parse --verify -q "$remote" >/dev/null; then ahead+=("$b"); continue; fi
  n=$(git rev-list --count "$remote..refs/heads/$b" 2>/dev/null || echo 0)
  [ "$n" -gt 0 ] && ahead+=("$b")
done
if [ "${#ahead[@]}" -eq 0 ]; then [ "$DRY" = 1 ] && echo "Nothing to push: GitHub is up to date."; exit 0; fi
if [ "$DRY" = 1 ]; then echo "Would push: ${ahead[*]}"; exit 0; fi

if out=$(git push origin "${ahead[@]}" 2>&1); then
  say "pushed: ${ahead[*]}"
else
  say "push failed (${ahead[*]}): $(echo "$out" | tail -3 | tr '\n' ' ')"
fi
exit 0
