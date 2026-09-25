#!/bin/bash
# Builds a fully self-contained "unzip and run" version of the Retirement
# Plan dashboard -- bundles Python itself (via PyInstaller) alongside
# every dependency, so the result runs on this Mac (or another Mac with
# a matching macOS version/chip) without anyone needing to install
# Python, run pip install, or deal with Xcode's command line tools at
# all. Run this ONCE (or again whenever the app's code changes) to
# produce dist/RetirementPlan/ and RetirementPlan-App.zip; from then on
# that zip is the drop-in deliverable -- scripts/run_dashboard.sh (the
# plain-source path, which still needs a working Python already on the
# machine) is no longer involved for anyone just running the app.
set -e
cd "$(dirname "$0")/.."
source scripts/_pick_python.sh

PYTHON_BIN="$(pick_python)" || {
  echo "Couldn't find a working Python 3 to build with -- Xcode's bundled python3 isn't functional here (common after an Xcode/macOS update) and no other install (pyenv/Homebrew/python.org) was found. Install one of those, then run this script again. This is a one-time BUILD-time requirement only -- the app this script produces needs no Python at all to run, on this Mac or anyone else's." >&2
  exit 1
}
echo "Building with $PYTHON_BIN..."

BUILD_VENV=.build_venv
rm -rf "$BUILD_VENV"
"$PYTHON_BIN" -m venv "$BUILD_VENV"

echo "Installing build dependencies (this app's requirements + PyInstaller)..."
"$BUILD_VENV/bin/python" -m pip install --no-compile -q -r requirements.txt "pyinstaller>=6.10"

echo "Running PyInstaller (a few minutes -- pandas/numpy/lxml are large)..."
rm -rf build dist RetirementPlan.spec
# --collect-all on the packages most likely to hide files PyInstaller's
# static import analysis can't see on its own (compiled extensions,
# entry-point-based plugin discovery, bundled data files) -- errs on the
# side of a larger build over a missing-module crash at runtime, since
# nobody's there to "pip install the one it missed" once this is unzipped
# on a Mac with no Python at all.
"$BUILD_VENV/bin/python" -m PyInstaller \
  --name RetirementPlan \
  --onedir \
  --noconfirm \
  --clean \
  --collect-all pandas \
  --collect-all numpy \
  --collect-all yfinance \
  --collect-all lxml \
  --collect-all cryptography \
  --collect-all keyring \
  --collect-all msoffcrypto \
  --collect-all openpyxl \
  --collect-all plaid \
  --collect-all bs4 \
  --collect-all requests_cache \
  --collect-all frozendict \
  --add-data "source/webapp/static:source/webapp/static" \
  run_app.py

if [ ! -x "dist/RetirementPlan/RetirementPlan" ]; then
  echo "PyInstaller finished but dist/RetirementPlan/RetirementPlan wasn't produced -- something went wrong above; scroll up for the actual error." >&2
  exit 1
fi

echo "Assembling the app folder (data/output/logs/config, launcher scripts)..."
mkdir -p dist/RetirementPlan/data dist/RetirementPlan/output dist/RetirementPlan/logs dist/RetirementPlan/config
touch dist/RetirementPlan/data/.keep dist/RetirementPlan/output/.keep dist/RetirementPlan/logs/.keep dist/RetirementPlan/config/.keep

cat > "dist/RetirementPlan/Start Retirement Plan.command" <<'EOF'
#!/bin/bash
# Double-click this in Finder -- macOS runs .command files in a new
# Terminal window. Keep that window open while using the dashboard; it's
# where "Retirement Plan dashboard running at http://127.0.0.1:8898/"
# and any errors show up. Close the window (or Ctrl+C in it) to stop.
cd "$(dirname "$0")"
./RetirementPlan
EOF
chmod +x "dist/RetirementPlan/Start Retirement Plan.command"

cat > "dist/RetirementPlan/Stop Retirement Plan.command" <<'EOF'
#!/bin/bash
PIDS=$(lsof -ti tcp:8898 2>/dev/null || true)
if [ -z "$PIDS" ]; then
  echo "Nothing is listening on port 8898 -- dashboard is not running."
else
  kill -INT $PIDS 2>/dev/null || true
  echo "Stopped."
fi
read -p "Press Return to close this window..." _
EOF
chmod +x "dist/RetirementPlan/Stop Retirement Plan.command"

# An abridged, plain-language setup doc, copied in fresh on every build --
# whoever receives just this zip (not the source repo/README.md) has
# nothing else to go on, so this is the only guidance they'll see.
# Source of truth is scripts/app_readme.txt (edit that, not this copy).
cp "$(dirname "$0")/app_readme.txt" "dist/RetirementPlan/README.txt"

rm -f RetirementPlan-App.zip
(cd dist && zip -r -X -q ../RetirementPlan-App.zip RetirementPlan)

echo ""
echo "Done."
echo "  dist/RetirementPlan/       -- the app folder, runnable as-is"
echo "  RetirementPlan-App.zip     -- the same thing, zipped for sharing"
echo "                                (includes README.txt -- an abridged"
echo "                                setup doc for whoever unzips it)"
echo ""
echo "To use it: unzip RetirementPlan-App.zip anywhere and double-click"
echo "\"Start Retirement Plan.command\" inside it. No Python setup needed."
echo ""
echo "First launch only: macOS will likely say this app is from an"
echo "unidentified developer (it isn't notarized by Apple). Right-click"
echo "\"Start Retirement Plan.command\" (or RetirementPlan itself) and"
echo "choose Open once, then confirm -- after that it opens normally."
