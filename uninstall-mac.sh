#!/bin/bash
# Remove Aqua Lite from this Mac. Your settings, history and downloaded models stay unless you add --all:
#     bash uninstall-mac.sh          (keeps settings)
#     bash uninstall-mac.sh --all    (removes everything)
set -uo pipefail
DEST="$HOME/Library/Application Support/AquaLite"

pkill -f "AquaLite.pyw" 2>/dev/null || true
rm -rf "$HOME/Applications/Aqua Lite.app" "$DEST/app" "$DEST/app.backup" "$DEST/venv"
rm -f "$HOME/Library/LaunchAgents/com.aqualite.app.plist"
if [ "${1:-}" = "--all" ]; then
  rm -rf "$DEST"
  echo "Aqua Lite and all its settings are removed."
else
  echo "Aqua Lite is removed. Your settings are kept in $DEST (run with --all to remove them too)."
fi
echo "You can also switch Aqua Lite off in System Settings > Privacy & Security (Accessibility, Input Monitoring)."
