#!/bin/bash
# Builds a shareable SOURCE zip of this whole project -- the sibling of
# build_standalone_app.sh, for when the recipient (a friend, your own
# second computer, wherever) is fine having Python installed and running
# this from source instead of a bundled app. Produces
# RetirementPlan-Share.zip one level up from Code/ (alongside this
# project's own README.md/Documents/), containing:
#
#   README.md, Documents/, and Code/ (source/, tests/, scripts/,
#   requirements.txt, run_app.py) with data/output/logs/config emptied
#   out to just their .keep placeholders.
#
# Deliberately excluded, every time this runs: your actual database and
# backups (data/*.db, data/backups/), your generated exports (output/*),
# your app log (logs/*.log), any custom data/output-location settings
# (config/*.json), this Mac's own venv/build artifacts (venv/,
# .build_venv/, build/, dist/, RetirementPlan.spec,
# RetirementPlan-App.zip, RetirementPlan-Share.zip itself), and every
# __pycache__/.DS_Store. None of that belongs in something you hand to
# someone else -- see build_standalone_app.sh's own zip for the same
# rule applied to the no-Python-needed build.
#
# Run this ONCE (or again whenever the code changes) to refresh the zip
# -- like build_standalone_app.sh, nothing here updates it automatically.
set -e
cd "$(dirname "$0")/.."          # -> Code/
PROJECT_ROOT="$(cd .. && pwd)"   # -> RetirementPlan/ (README.md, Documents/, Code/)
cd "$PROJECT_ROOT"

if [ ! -f README.md ] || [ ! -d Code ]; then
  echo "Expected to find README.md and Code/ in $PROJECT_ROOT -- this script assumes the usual RetirementPlan/{README.md,Documents,Code} layout. Nothing built." >&2
  exit 1
fi

STAGE_DIR="$(mktemp -d)"
trap 'rm -rf "$STAGE_DIR"' EXIT
STAGE="$STAGE_DIR/RetirementPlan-Share"
mkdir -p "$STAGE"

echo "Copying README.md and Documents/..."
cp README.md "$STAGE/"
[ -d Documents ] && cp -R Documents "$STAGE/Documents"

echo "Copying Code/ (source, tests, scripts, requirements.txt, run_app.py)..."
mkdir -p "$STAGE/Code"
# rsync, not cp -R, so the exclude list below can drop this Mac's own
# venv/build artifacts and personal data in one pass instead of copying
# everything and pruning it after.
rsync -a \
  --exclude='venv/' \
  --exclude='venv_broken_old/' \
  --exclude='.build_venv/' \
  --exclude='build/' \
  --exclude='dist/' \
  --exclude='RetirementPlan.spec' \
  --exclude='RetirementPlan-App.zip' \
  --exclude='RetirementPlan-Share.zip' \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  --exclude='.DS_Store' \
  --exclude='.pytest_cache/' \
  --exclude='data/' \
  --exclude='output/' \
  --exclude='logs/' \
  --exclude='config/' \
  Code/ "$STAGE/Code/"

echo "Adding empty data/output/logs/config (no personal data)..."
for d in data output logs config; do
  mkdir -p "$STAGE/Code/$d"
  touch "$STAGE/Code/$d/.keep"
done

echo "Zipping..."
rm -f RetirementPlan-Share.zip
(cd "$STAGE_DIR" && zip -r -X -q "$PROJECT_ROOT/RetirementPlan-Share.zip" RetirementPlan-Share)

echo ""
echo "Done: RetirementPlan-Share.zip"
echo ""
echo "To use it: unzip it anywhere, cd into the Code folder inside it, and run"
echo "  ./scripts/run_dashboard.sh"
echo "That one script creates its own venv and installs every dependency"
echo "automatically -- the only thing the recipient needs already on their"
echo "machine is Python 3 itself (see README.md's \"Python trouble on this"
echo "Mac?\" note if it can't find one)."
