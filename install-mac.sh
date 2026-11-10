#!/bin/bash
# Aqua Lite setup for macOS: copies the app, makes a private Python environment, installs the packages, runs the
# self-test and puts "Aqua Lite" in your Applications folder. Three ways to run it:
#   - double-click "Install Aqua Lite.command" in the Mac download
#   - from the downloaded folder:  bash install-mac.sh
#   - with nothing downloaded:     curl -fsSL https://raw.githubusercontent.com/undeadhuman37/aqua-lite/main/install-mac.sh | bash
# Running it again updates Aqua Lite. AQUALITE_CI=1 is for the automatic check on GitHub (no window, stricter).
set -euo pipefail
REPO="undeadhuman37/aqua-lite"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" 2>/dev/null && pwd || pwd)"

DEST="$HOME/Library/Application Support/AquaLite"
APPDIR="$DEST/app"
VENV="$DEST/venv"
BUNDLE="$HOME/Applications/Aqua Lite.app"

echo
echo "  ================================================"
echo "    Aqua Lite setup  -  voice dictation for macOS"
echo "  ================================================"
echo

# ---- 0. run on its own (curl | bash): fetch the latest Mac download first
if [ ! -d "$SRC/aqualite" ]; then
  echo "[0/5] Downloading Aqua Lite..."
  TMP="$(mktemp -d)"
  if ! curl -fsSL -o "$TMP/aqualite.zip" "https://github.com/$REPO/releases/latest/download/AquaLite-Mac.zip"; then
    curl -fsSL -o "$TMP/aqualite.zip" "https://github.com/$REPO/archive/refs/heads/main.zip"
  fi
  ditto -x -k "$TMP/aqualite.zip" "$TMP/x"
  SRC="$(dirname "$(find "$TMP/x" -maxdepth 3 -name AquaLite.pyw | head -1)")"
fi
cd "$SRC"

# ---- stop a running copy so files can be replaced
pkill -f "AquaLite.pyw" 2>/dev/null || true

# ---- 1. find Python 3.11-3.13 with Tk (the python.org installer has both); install 3.12 if there's none
FW=/Library/Frameworks/Python.framework/Versions   # python.org installs here, even before PATH is updated
find_python() {
  for cand in "$FW/3.12/bin/python3" python3.12 python3.13 python3.11 python3 "$FW/3.13/bin/python3" \
      "$FW/3.11/bin/python3" /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    if command -v "$cand" >/dev/null 2>&1 \
        && "$cand" -c "import sys, tkinter; assert (3, 11) <= sys.version_info[:2] <= (3, 13)" >/dev/null 2>&1; then
      command -v "$cand"
      return 0
    fi
  done
  return 1
}
PY="$(find_python || true)"
if [ -z "$PY" ]; then
  echo "[1/5] Installing Python 3.12 from python.org (Aqua Lite runs on it). macOS asks for your password once."
  PKG="$(mktemp -d)/python-3.12.10-macos11.pkg"
  curl -fsSL -o "$PKG" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg"
  sudo installer -pkg "$PKG" -target / >/dev/null
  bash "/Applications/Python 3.12/Install Certificates.command" >/dev/null 2>&1 || true   # so HTTPS works
  PY="$(find_python || true)"
fi
if [ -z "$PY" ]; then
  echo "  Python 3.12 couldn't be set up. Install it from https://www.python.org/downloads/macos/ and run this again."
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
  [ -n "${AQUALITE_CI:-}" ] && exit 1
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
[ -z "${AQUALITE_CI:-}" ] && open "$BUNDLE" || true
