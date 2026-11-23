#!/bin/bash
# Sets up the nightly BoardDocs snapshot on a Mac. Run once in Terminal:
#   bash install.sh
# To remove it later:
#   launchctl bootout gui/$(id -u)/org.civicswa.boarddocs; rm ~/Library/LaunchAgents/org.civicswa.boarddocs.plist
set -euo pipefail
REPO=https://github.com/davidmorganlund-oss/civicswa.git
DIR="$HOME/Library/Application Support/CivicsWA"
PLIST="$HOME/Library/LaunchAgents/org.civicswa.boarddocs.plist"

if ! xcode-select -p >/dev/null 2>&1; then
  echo "macOS needs its command line tools (git and python3). A window will open; install them, then run this again."
  xcode-select --install || true
  exit 1
fi
mkdir -p "$DIR"
if [ ! -d "$DIR/repo/.git" ]; then git clone -q "$REPO" "$DIR/repo"; fi
cd "$DIR/repo" && git fetch -q origin main && git reset -q --hard origin/main
if command -v gh >/dev/null 2>&1; then gh auth setup-git >/dev/null 2>&1 || true; fi

echo "Running it once now (this also checks that your Mac can push to GitHub)..."
if ! bash tools/boarddocs/run.sh; then
  echo
  echo "The first run didn't finish. If the problem was signing in to GitHub, sign in"
  echo "(GitHub Desktop, or 'gh auth login'), then run this script again."
  exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>org.civicswa.boarddocs</string>
  <key>ProgramArguments</key><array><string>/bin/bash</string><string>$DIR/repo/tools/boarddocs/run.sh</string></array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>1</integer><key>Minute</key><integer>40</integer></dict>
  <key>StandardOutPath</key><string>$DIR/boarddocs.log</string>
  <key>StandardErrorPath</key><string>$DIR/boarddocs.log</string>
</dict></plist>
PL
launchctl bootout "gui/$(id -u)/org.civicswa.boarddocs" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo
echo "Done. It will run every night at 1:40 a.m. (or when your Mac next wakes)."
echo "Log: $DIR/boarddocs.log"
