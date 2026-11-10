#!/bin/bash
# Double-click to install Aqua Lite on your Mac (or to update it). It opens in Terminal and takes a few minutes.
cd "$(dirname "$0")"
bash install-mac.sh
echo
read -n 1 -s -r -p "  Press any key to close this window"
echo
