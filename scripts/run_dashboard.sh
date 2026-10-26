#!/bin/bash
# Sets up (if needed) and runs the dashboard at
# http://127.0.0.1:8898/. --no-compile sidesteps a known olefile/pip
# bytecompile quirk on some Python installs -- see FamilyFinanceTracker's
# own install notes for the full story; harmless either way (Python
# compiles bytecode lazily on first import regardless).
#
# Prefer scripts/build_mac_app.sh instead if you just want a
# drop-in, no-setup app you can unzip and run on any Mac without Python
# installed at all -- this script is the "run from source" path, which
# still needs a working Python on the machine it runs on.
set -e
cd "$(dirname "$0")/.."
source scripts/_pick_python.sh

venv_is_healthy() {
  [ -x venv/bin/python3 ] && venv/bin/python3 -c "import sys" >/dev/null 2>&1
}

if [ -d venv ] && { ! venv_is_healthy || venv_uses_known_flaky_interpreter venv; }; then
  echo "Existing virtual environment isn't usable (or uses a Python known to misbehave with pip on some Macs) -- recreating it..."
  rm -rf venv
fi

if [ ! -d venv ]; then
  PYTHON_BIN="$(pick_python)" || {
    echo "Couldn't find a working Python 3 on this Mac -- Xcode's bundled python3 isn't functional here (common after an Xcode/macOS update) and no other install was found. Install Python from python.org or with 'brew install python3' (or, if you use pyenv, 'pyenv install 3.12'), then run this script again." >&2
    exit 1
  }
  echo "Creating virtual environment with $PYTHON_BIN..."
  "$PYTHON_BIN" -m venv venv
fi

echo "Installing dependencies..."
# venv/bin/python -m pip, not venv/bin/pip -- pip's own console-script
# entry points (venv/bin/pip, pip3, ...) have the venv's absolute path
# baked into their shebang line at creation time, so they break if the
# venv folder is ever moved or renamed after the fact. Invoking pip as
# a module of the interpreter sidesteps that entirely.
venv/bin/python -m pip install --no-compile -q -r requirements.txt

echo "Starting dashboard... (it also starts the bundled IBKR gateway on a private local port when Java is installed; FINSI_NO_GATEWAY=1 skips that)"
venv/bin/python -m source.webapp.dashboard
