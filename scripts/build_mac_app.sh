#!/bin/bash
# Builds the Mac app (named from source/common/branding.py) -- a double-clickable app that bundles Python and
# every dependency, so whoever runs it needs no Python, no pip and no
# Terminal. Run this ONCE on a Mac (it cannot be built on Linux or Windows),
# from the Code/ folder:   bash scripts/build_mac_app.sh
# It takes a few minutes (pandas/numpy/lxml are large) and produces:
#   dist/<Brand>.app        the app, runnable as-is
#   dist/<Brand>-mac.zip    the same thing zipped for sharing
#
# SIGNING AND NOTARIZING (so Macs open it with no warning). Needs an Apple
# Developer account. One time:  xcrun notarytool store-credentials "finsi-notary"
# (it asks for your Apple ID, team id and an app-specific password). Then:
#   SIGN_IDENTITY="Developer ID Application: Your Name (TEAMID)" \
#   NOTARY_PROFILE="finsi-notary" bash scripts/build_mac_app.sh
# Without those two variables the build still works, ad-hoc signed.
# It also makes dist/<Brand>-<version>.dmg (drag-to-Applications installer)
# and dist/latest.json (the file "Check for updates" reads once you host it).
#
# How the app works: Contents/MacOS/<Brand> is a tiny launcher. It starts the
# bundled server in the background (if it isn't already running), then opens
# the dashboard in the default browser. Opening the app again just opens the
# browser again. Setup > "Quit <Brand>" stops the server.
#
# The brand name (and tagline, bundle id) come from source/common/branding.py;
# the data folder is branding.INTERNAL_ID, which never changes with the brand.
# The app keeps its data in ~/Library/Application Support/<INTERNAL_ID>/ (see
# source/common/config.py), never inside the app bundle.
set -e
cd "$(dirname "$0")/.."
source scripts/_pick_python.sh

PORT=8898
SERVER_NAME="app-server"   # internal binary name; never shown, never brand-specific

if [ "$(uname -s)" != "Darwin" ]; then
  echo "This script builds a macOS app, so it has to run on a Mac (this is $(uname -s))." >&2
  exit 1
fi

PYTHON_BIN="$(pick_python)" || {
  echo "Couldn't find a working Python 3 to build with -- Xcode's bundled python3 isn't functional here and no other install (pyenv/Homebrew/python.org) was found. Install one (e.g. 'brew install python3'), then run this script again. This is a BUILD-time requirement only; the finished app needs no Python." >&2
  exit 1
}
echo "Building with $PYTHON_BIN..."

brand() { "$PYTHON_BIN" -c "import runpy; print(runpy.run_path('source/common/branding.py')['$1'])"; }
APP_NAME="$(brand PRODUCT_NAME)"
VERSION="$(brand APP_VERSION)"
BUNDLE_ID="$(brand BUNDLE_ID)"
DATA_FOLDER="$(brand INTERNAL_ID)"
echo "Brand: $APP_NAME ($BUNDLE_ID); data folder: ~/Library/Application Support/$DATA_FOLDER"

BUILD_VENV=.build_venv
rm -rf "$BUILD_VENV"
"$PYTHON_BIN" -m venv "$BUILD_VENV"
echo "Installing build dependencies..."
"$BUILD_VENV/bin/python" -m pip install -q --upgrade pip
# cryptography must come as a ready-made wheel (it carries its own OpenSSL). Built
# from source it links the Mac's OpenSSL and the app then fails with
# "Symbol not found: _SSL_get0_group_name".
"$BUILD_VENV/bin/python" -m pip install -q --only-binary=:all: cryptography
"$BUILD_VENV/bin/python" -m pip install --no-compile -q -r requirements.txt "pyinstaller>=6.10"
"$BUILD_VENV/bin/python" -m pip install -q --only-binary=:all: cryptography

echo "Running PyInstaller (a few minutes)..."
rm -rf build dist "$SERVER_NAME.spec"
# --collect-all on the packages most likely to hide files PyInstaller's static
# analysis can't see (compiled extensions, plugin discovery, bundled data).
"$BUILD_VENV/bin/python" -m PyInstaller \
  --name "$SERVER_NAME" \
  --onedir \
  --noconfirm \
  --clean \
  --collect-all pandas \
  --collect-all numpy \
  --collect-all yfinance \
  --collect-all lxml \
  --collect-all cryptography \
  --collect-all keyring \
  --collect-all truststore \
  --collect-all msoffcrypto \
  --collect-all openpyxl \
  --collect-all plaid \
  --collect-all bs4 \
  --collect-all requests_cache \
  --collect-all frozendict \
  --add-data "source/webapp/static:source/webapp/static" \
  run_app.py

if [ ! -x "dist/$SERVER_NAME/$SERVER_NAME" ]; then
  echo "PyInstaller finished but dist/$SERVER_NAME/$SERVER_NAME wasn't produced -- scroll up for the actual error." >&2
  exit 1
fi

echo "Checking the built program starts..."
if ! "dist/$SERVER_NAME/$SERVER_NAME" --selftest; then
  echo "The built program failed its start-up check (see the error above)." >&2
  echo "Send that text along if you ask for help." >&2
  exit 1
fi

echo "Assembling $APP_NAME.app..."
APP="dist/$APP_NAME.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp -R dist/$SERVER_NAME "$APP/Contents/Resources/server"

sed -e "s#@PORT@#$PORT#g" -e "s#@SERVER_NAME@#$SERVER_NAME#g" \
    -e "s#@DATA_FOLDER@#$DATA_FOLDER#g" -e "s#@APP_NAME@#$APP_NAME#g" \
    scripts/assets/launcher.sh > "$APP/Contents/MacOS/$APP_NAME"
chmod +x "$APP/Contents/MacOS/$APP_NAME"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleVersion</key><string>$VERSION</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleExecutable</key><string>$APP_NAME</string>
  <key>CFBundleIconFile</key><string>$APP_NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.finance</string>
  <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

echo "Making the app icon..."
ICONSET="build/$APP_NAME.iconset"
rm -rf "$ICONSET"; mkdir -p "$ICONSET"
SRC=scripts/assets/app-icon-1024.png
for s in 16 32 128 256 512; do
  sips -z $s $s "$SRC" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  sips -z $((s*2)) $((s*2)) "$SRC" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/$APP_NAME.icns"

ENTITLEMENTS=scripts/assets/entitlements.plist
if [ -n "${SIGN_IDENTITY:-}" ]; then
  echo "Signing with your Developer ID (hardened runtime)..."
  # Sign every nested binary first, then the app itself.
  find "$APP/Contents/Resources/server" -type f \( -name "*.so" -o -name "*.dylib" -o -perm +111 \) -print0 |
    xargs -0 -n1 codesign --force --timestamp --options runtime --entitlements "$ENTITLEMENTS" --sign "$SIGN_IDENTITY" >/dev/null 2>&1 || true
  codesign --force --timestamp --options runtime --entitlements "$ENTITLEMENTS" --sign "$SIGN_IDENTITY" "$APP"
  codesign --verify --deep --strict "$APP" && echo "Signature OK."
else
  # Ad-hoc signature: not a developer identity (so macOS still asks you to
  # right-click > Open the first time), but Apple-silicon Macs refuse to run
  # completely unsigned code.
  codesign --force --deep --sign - "$APP" >/dev/null 2>&1 || echo "(codesign skipped -- the app should still run; right-click > Open the first time.)"
fi

notarize() {  # $1 = file to send to Apple (zip or dmg)
  xcrun notarytool submit "$1" --keychain-profile "$NOTARY_PROFILE" --wait
}

if [ -n "${SIGN_IDENTITY:-}" ] && [ -n "${NOTARY_PROFILE:-}" ]; then
  echo "Sending the app to Apple for notarization (a few minutes)..."
  ditto -c -k --keepParent "$APP" "build/notarize.zip"
  notarize build/notarize.zip
  xcrun stapler staple "$APP"
fi

sed -e "s/__APP_NAME__/$APP_NAME/g" -e "s/__DATA_FOLDER__/$DATA_FOLDER/g" -e "s/__SERVER_NAME__/$SERVER_NAME/g" scripts/app_readme.txt > "dist/README.txt"
rm -f "dist/$APP_NAME-mac.zip"
ditto -c -k --keepParent "$APP" "dist/$APP_NAME-mac.zip"

echo "Making the installer (.dmg)..."
ARCH_LABEL="$([ "$(uname -m)" = "arm64" ] && echo apple-chip || echo intel)"
DMG="dist/$APP_NAME-$VERSION-$ARCH_LABEL.dmg"
STAGE="build/dmg"
rm -rf "$STAGE" "$DMG"; mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
cp "dist/README.txt" "$STAGE/Read me first.txt"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
if [ -n "${SIGN_IDENTITY:-}" ]; then
  codesign --force --timestamp --sign "$SIGN_IDENTITY" "$DMG"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    notarize "$DMG"
    xcrun stapler staple "$DMG"
  fi
fi
cat > dist/latest.json <<JSON
{"version": "$VERSION", "url": "https://YOUR-SITE/$APP_NAME-$VERSION-$ARCH_LABEL.dmg", "notes": "Describe what changed."}
JSON

echo
echo "Done."
echo "  dist/$APP_NAME.app        -- drag this into Applications"
echo "  dist/$APP_NAME-mac.zip    -- the same, zipped"
echo "  $DMG  -- the installer to share (only runs on $ARCH_LABEL Macs; build on the other kind for those)"
echo "  dist/latest.json          -- upload next to the dmg; set its address in Setup > About"
echo
if [ -z "${SIGN_IDENTITY:-}" ]; then
  echo "First time: right-click $APP_NAME.app > Open > Open (macOS warns about an unidentified developer)."
  echo "(Set SIGN_IDENTITY and NOTARY_PROFILE to remove that warning; see the top of this script.)"
fi
echo "Check it on a clean setup:  python3 scripts/smoke_test.py --server dist/$SERVER_NAME/$SERVER_NAME"
echo "Your data lives in ~/Library/Application Support/$DATA_FOLDER/ ."
echo
echo "To bring an existing source install's data across, QUIT the old dashboard, then run:"
echo "  mkdir -p ~/Library/Application\\ Support/$DATA_FOLDER/data"
echo "  cp -R /path/to/your/old/Code/data/. ~/Library/Application\\ Support/$DATA_FOLDER/data/"
