#!/bin/bash
# Starts the bundled server if it isn't running, then opens the dashboard.
# If the server cannot start, say so in plain words instead of opening a dead
# page ("refused to connect").
URL="http://127.0.0.1:@PORT@/"
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_ROOT="$(cd "$HERE/../.." && pwd)"
SERVER="$HERE/../Resources/server/@SERVER_NAME@"
LOG_DIR="$HOME/Library/Application Support/@DATA_FOLDER@/logs"
LOG="$LOG_DIR/launch.log"
NAME="@APP_NAME@"

healthy() { curl -fs --max-time 2 "${URL}api/health" >/dev/null 2>&1; }

say() {  # a plain-language dialog; never blocks the launcher for long
  /usr/bin/osascript -e "display dialog \"$1\" with title \"$NAME\" buttons {\"OK\"} default button \"OK\" with icon caution" >/dev/null 2>&1
}

if healthy; then
  open "$URL"; exit 0
fi

mkdir -p "$LOG_DIR"
{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') launching $NAME"
  echo "mac: $(sw_vers -productVersion 2>/dev/null) $(uname -m)"
  echo "app: $APP_ROOT"
} >> "$LOG"

# A copy that came through AirDrop, a download or a zip is marked "quarantined"
# and macOS may refuse to run the program inside it. Clear the mark (it is our
# own app) and, if the signature was broken by copying, re-sign it on this Mac.
if /usr/bin/xattr -p com.apple.quarantine "$APP_ROOT" >/dev/null 2>&1; then
  echo "clearing quarantine mark" >> "$LOG"
  /usr/bin/xattr -dr com.apple.quarantine "$APP_ROOT" >> "$LOG" 2>&1
fi
if [ -x /usr/bin/codesign ] && ! /usr/bin/codesign --verify "$SERVER" >/dev/null 2>&1; then
  echo "signature not valid here; signing on this Mac" >> "$LOG"
  /usr/bin/codesign --force --deep --sign - "$APP_ROOT" >> "$LOG" 2>&1
fi

# "Bad CPU type in executable" = the app was built for the other kind of Mac
# (Apple chip vs Intel). Say so plainly instead of failing silently.
if [ "$(/usr/sbin/sysctl -n hw.optional.arm64 2>/dev/null)" = "1" ]; then THIS=arm64; else THIS=x86_64; fi
BUILT="$(/usr/bin/lipo -archs "$SERVER" 2>/dev/null)"
echo "this Mac: $THIS; app built for: ${BUILT:-unknown}" >> "$LOG"
if [ -n "$BUILT" ]; then
  case " $BUILT " in
    *" $THIS "*) ;;
    *)
      if [ "$THIS" = "arm64" ]; then
        # An Intel-built app can run on an Apple-chip Mac once Rosetta is installed.
        if ! /usr/bin/arch -x86_64 /usr/bin/true >/dev/null 2>&1; then
          if /usr/bin/osascript -e "display dialog \"This copy of $NAME was built for Intel Macs. This Mac can run it after installing Apple's free Rosetta helper. Install it now?\" with title \"$NAME\" buttons {\"Not now\", \"Install\"} default button \"Install\"" 2>/dev/null | grep -q Install; then
            /usr/bin/osascript -e 'do shell script "/usr/sbin/softwareupdate --install-rosetta --agree-to-license" with administrator privileges' >> "$LOG" 2>&1
          fi
        fi
        if ! /usr/bin/arch -x86_64 /usr/bin/true >/dev/null 2>&1; then
          say "This copy of $NAME was built for Intel Macs and needs Rosetta to run here. Or build $NAME on this Mac (see the Read me first file)."
          exit 1
        fi
      else
        echo "wrong chip for this Mac" >> "$LOG"
        say "This copy of $NAME was built for Macs with an Apple chip, but this is an Intel Mac. Please build $NAME on this Mac (see the Read me first file), or ask for the Intel version."
        exit 1
      fi ;;
  esac
fi

if [ ! -x "$SERVER" ]; then
  echo "server program missing or not executable: $SERVER" >> "$LOG"
  say "$NAME's program file is missing or damaged. Please copy the whole app again (use a .dmg or Finder, not a partial copy). Details: $LOG"
  exit 1
fi

nohup "$SERVER" --no-browser >> "$LOG" 2>&1 &
PID=$!

for _ in $(seq 1 120); do
  sleep 0.5
  if healthy; then open "$URL"; exit 0; fi
  if ! kill -0 "$PID" 2>/dev/null; then
    wait "$PID" 2>/dev/null; CODE=$?
    echo "server stopped on its own, exit code $CODE" >> "$LOG"
    case "$CODE" in
      126|127) HINT="macOS would not run the program. Try right-click the app, Open." ;;
      137|132|133|134|139) HINT="macOS stopped the program (code $CODE). On a Mac with a different chip, rebuild the app on that Mac." ;;
      *) HINT="It stopped right after starting (code $CODE)." ;;
    esac
    say "$NAME could not start. $HINT The log is at: $LOG"
    exit 1
  fi
done

echo "server did not answer within 60 seconds" >> "$LOG"
say "$NAME is taking too long to start. Wait a minute and open it again. If it keeps happening, send the file at $LOG to support."
exit 1
