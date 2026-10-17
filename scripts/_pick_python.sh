# Shared by run_dashboard.sh and build_mac_app.sh -- not meant to
# be run directly (no shebang/executable bit on purpose; it's sourced).
#
# Picks a real, working python3, and specifically avoids two paths that
# exist on plenty of Macs but can silently fail: plain macOS python3
# (/usr/bin/python3) and Xcode's own copy
# (/Applications/Xcode.app/Contents/Developer/usr/bin/python3). Both are
# really just stubs that shell out to `xcodebuild -find python` /
# `xcode-select` under the hood the first time certain operations touch
# them (observed here: basic "python3 -c ..." calls succeed, but pip
# needing to run something as plain "python" during a dependency install
# does not) -- if Xcode's command line tools are missing, stale, or
# unlicensed, or Xcode has simply stopped bundling a python at all (true
# for recent Xcode versions), that lookup fails with an
# "xcode-select: Failed to locate 'python' ..." error, even though a
# perfectly good, self-contained Python (pyenv, Homebrew, python.org) is
# already installed elsewhere on the same Mac. Each candidate below is
# actually exercised (not just checked for existence) before being
# trusted, since a stub can exist as a file yet still fail like this when
# run.
pick_python() {
  local candidates=()
  if [ -d "$HOME/.pyenv/versions" ]; then
    local v
    for v in $(ls -1 "$HOME/.pyenv/versions" 2>/dev/null | sort -rV); do
      candidates+=("$HOME/.pyenv/versions/$v/bin/python3")
    done
  fi
  candidates+=(
    /opt/homebrew/bin/python3
    /usr/local/bin/python3
    /Library/Frameworks/Python.framework/Versions/Current/bin/python3
  )
  local c
  for c in "${candidates[@]}"; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c "import sys" >/dev/null 2>&1; then
      echo "$c"
      return 0
    fi
  done
  # Last resort: whatever "python3" resolves to on PATH, including
  # /usr/bin/python3 or Xcode's copy -- better than nothing if pyenv/
  # Homebrew/python.org genuinely aren't installed, but this is exactly
  # the case that has misbehaved before, so callers should treat this
  # branch as a warning sign, not a clean success.
  if command -v python3 >/dev/null 2>&1 && python3 -c "import sys" >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  return 1
}

# True if `venv`'s own python3 symlink resolves to one of the two stub
# paths above -- used to force a rebuild even when the interpreter passes
# a trivial health check, since that check alone isn't enough (see the
# comment on pick_python).
venv_uses_known_flaky_interpreter() {
  local venv_dir="${1:-venv}"
  [ -L "$venv_dir/bin/python3" ] || return 1
  local target
  target="$(readlink "$venv_dir/bin/python3")"
  case "$target" in
    */Xcode.app/*|/usr/bin/python3|/usr/bin/python) return 0 ;;
    *) return 1 ;;
  esac
}
