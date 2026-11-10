#!/bin/bash
# Aqua Lite setup for macOS: copies the app, makes a private Python environment, installs the packages, runs the
# self-test and puts "Aqua Lite" in your Applications folder. Run it from the folder you downloaded:
#     bash install-mac.sh
# UNTESTED: written on Windows without a Mac. See docs/MAC.md for what to try and how to report back.
set -euo pipefail
cd "$(dirname "$0")"
SRC="$(pwd)"

DEST="$HOME/Library/Application Support/AquaLite"
APPDIR="$DEST/app"
VENV="$DEST/venv"
BUNDLE="$HOME/Applications/Aqua Lite.app"

echo
echo "  ================================================"
echo "    Aqua Lite setup  -  voice dictation for macOS"
echo "  ================================================"
echo

# ---- stop a running copy so files can be replaced
pkill -f "AquaLite.pyw" 2>/dev/null || true

# ---- 1. find Python 3.11-3.13 with Tk (the python.org installer has both; Homebrew needs python-tk)
PY=""
for cand in python3.12 python3.13 python3.11 python3; do
  if command -v "$cand" >/dev/null 2>&1 \
      && "$cand" -c "import sys, tkinter; assert (3, 11) <= sys.version_info[:2] <= (3, 13)" >/dev/null 2>&1; then
    PY="$(command -v "$cand")"
    break
  fi
done
if [ -z "$PY" ]; then
  echo "  Python 3.11, 3.12 or 3.13 with Tk wasn't found."
  echo "  Install Python 3.12 from https://www.python.org/downloads/macos/ (it includes Tk), then run this again."
  echo "  (With Homebrew: brew install python@3.12 python-tk@3.12)"
  exit 1
fi
echo "[1/5] Using Python: $PY"

# ---- 2. copy the app
echo "[2/5] Copying Aqua Lite to $APPDIR"
mkdir -p "$APPDIR"
rsync -a --delete --exclude ".git" --exclude ".venv" --exclude "__pycache__" --exclude "*.zip" --exclude ".claude" \
  "$SRC/" "$APPDIR/"

# ---- 3. private Python environment + packages
if [ ! -x "$VENV/bin/python" ]; then
  echo "[3/5] Creating a private Python environment..."
  "$PY" -m venv "$VENV"
fi
echo "[3/5] Installing packages (first time takes a few minutes)..."
"$VENV/bin/python" -m pip install --upgrade pip --quiet --disable-pip-version-check
if ! "$VENV/bin/python" -m pip install -r "$APPDIR/requirements-mac.txt" --quiet --disable-pip-version-check; then
  echo "  Package install failed - check your internet connection and run install-mac.sh again."
  exit 1
fi
"$VENV/bin/python" -c "import sys; sys.path.insert(0, sys.argv[1]); from aqualite import deps; deps.mark_installed()" \
  "$APPDIR" >/dev/null 2>&1 || true

# ---- 4. check everything works
echo "[4/5] Running the self-test..."
if ! (cd "$APPDIR" && "$VENV/bin/python" -c "from aqualite import selftest; selftest.main()"); then
  # Mac support is new: carry on so the rest can be tried, but this output is exactly what's needed to fix it
  echo
  echo "  The self-test failed (Mac support is new). Setup carries on so you can still try Aqua Lite,"
  echo "  but please copy everything above into a GitHub issue."
  echo
fi

# ---- 5. "Aqua Lite" in Applications: a small app that starts the private Python. macOS gives permissions
#         (Accessibility, Input Monitoring, Microphone) to this app, not to Terminal.
echo "[5/5] Adding Aqua Lite to $HOME/Applications"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"
cat > "$BUNDLE/Contents/MacOS/Aqua Lite" <<LAUNCH
#!/bin/bash
export AQUALITE_BUNDLE="$BUNDLE"
cd "$APPDIR"
exec "$VENV/bin/python" "$APPDIR/AquaLite.pyw" "\$@"
LAUNCH
chmod +x "$BUNDLE/Contents/MacOS/Aqua Lite"
VERSION="$(cat "$APPDIR/VERSION" 2>/dev/null || echo 2.0.0)"
cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>Aqua Lite</string>
  <key>CFBundleDisplayName</key><string>Aqua Lite</string>
  <key>CFBundleIdentifier</key><string>com.aqualite.app</string>
  <key>CFBundleExecutable</key><string>Aqua Lite</string>
  <key>CFBundleIconFile</key><string>AquaLite</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>LSUIElement</key><true/>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSMicrophoneUsageDescription</key>
  <string>Aqua Lite listens while you hold the talk shortcut and turns your voice into text.</string>
  <key>NSAppleEventsUsageDescription</key><string>Aqua Lite types your words into the app you're using.</string>
</dict>
</plist>
PLIST
# the icon, drawn by the app itself
ICONSET="$(mktemp -d)/AquaLite.iconset"
mkdir -p "$ICONSET"
if "$VENV/bin/python" - "$APPDIR" "$ICONSET" <<'ICON' >/dev/null 2>&1
import sys
sys.path.insert(0, sys.argv[1])
from aqualite.aero import app_icon
for s in (16, 32, 128, 256, 512):
    app_icon(s).save(f"{sys.argv[2]}/icon_{s}x{s}.png")
    app_icon(s * 2).save(f"{sys.argv[2]}/icon_{s}x{s}@2x.png")
ICON
then
  iconutil -c icns "$ICONSET" -o "$BUNDLE/Contents/Resources/AquaLite.icns" 2>/dev/null || true
fi
touch "$BUNDLE"

echo
echo "  Done. Open Aqua Lite from your Applications folder (it lives in the menu bar, top right)."
echo "  macOS will ask for Accessibility, Input Monitoring and the microphone: allow \"Aqua Lite\" each time,"
echo "  then quit and reopen it. Hold Fn and talk. In System Settings > Keyboard, set"
echo "  \"Press fn key to\" (or the globe key) to \"Do Nothing\" so the emoji picker doesn't open."
echo
open "$BUNDLE" || true
