#!/bin/bash
set -euo pipefail
ROOT="/Users/ilyagazman/.openclaw/workspace/sheriffclaw"
PLIST_NAME="com.sheriffclaw.wakeup10min"
PLIST_PATH="$HOME/Library/LaunchAgents/${PLIST_NAME}.plist"
LOG="$ROOT/logs/wakeup_launchd_setup.log"

mkdir -p "$ROOT/logs" "$HOME/Library/LaunchAgents"

cat > "$PLIST_PATH" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>${PLIST_NAME}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${ROOT}/scripts/launchd_wakeup_10min.sh</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>600</integer>
  <key>StandardOutPath</key><string>${ROOT}/logs/wakeup_launchd.out</string>
  <key>StandardErrorPath</key><string>${ROOT}/logs/wakeup_launchd.err</string>
</dict>
</plist>
EOF

rm -f "$ROOT/.wakeup_launchd_count"

DOMAIN1="gui/$(id -u)"
DOMAIN2="user/$(id -u)"

{
  echo "[$(date)] trying bootstrap in $DOMAIN1"
  launchctl bootout "$DOMAIN1" "$PLIST_PATH" >/dev/null 2>&1 || true
  if launchctl bootstrap "$DOMAIN1" "$PLIST_PATH" >/dev/null 2>&1; then
    echo "[$(date)] bootstrapped in $DOMAIN1"
    exit 0
  fi

  echo "[$(date)] fallback bootstrap in $DOMAIN2"
  launchctl bootout "$DOMAIN2" "$PLIST_PATH" >/dev/null 2>&1 || true
  if launchctl bootstrap "$DOMAIN2" "$PLIST_PATH" >/dev/null 2>&1; then
    echo "[$(date)] bootstrapped in $DOMAIN2"
    exit 0
  fi

  echo "[$(date)] bootstrap failed in both domains"
  exit 1
} >> "$LOG" 2>&1
