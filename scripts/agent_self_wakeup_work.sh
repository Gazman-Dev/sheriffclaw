#!/bin/bash
set -euo pipefail

ROOT="/Users/ilyagazman/.openclaw/workspace/sheriffclaw"
COUNT_FILE="$ROOT/.agent_self_wakeup_count"
LOG_FILE="$ROOT/logs/agent_self_wakeup.log"
TAG="sheriffclaw-self-wakeup-10min-6x"
TELEGRAM_TARGET="8221289202"

mkdir -p "$ROOT/logs"
count=0
if [ -f "$COUNT_FILE" ]; then
  count=$(cat "$COUNT_FILE" 2>/dev/null || echo 0)
fi
count=$((count+1))
echo "$count" > "$COUNT_FILE"

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] wake cycle $count/6 start" >> "$LOG_FILE"

if [ -d "$ROOT/.venv" ]; then
  (
    cd "$ROOT"
    . .venv/bin/activate
    # Work payload: strengthen testing feedback loop
    python -m pytest -q tests/test_ctl_cli.py tests/test_memory_phase4.py >> "$LOG_FILE" 2>&1 || true
    ./scripts/qa_cycle.sh >> "$LOG_FILE" 2>&1 || true
  )
fi

echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] wake cycle $count/6 done" >> "$LOG_FILE"

# Telegram summary after each cycle (best effort)
summary="Wake cycle ${count}/6 complete. Ran testing hardening tasks (pytest subset + qa_cycle)."
openclaw message send --channel telegram --target "$TELEGRAM_TARGET" --message "$summary" >/dev/null 2>&1 || true

if [ "$count" -ge 6 ]; then
  tmp=$(mktemp)
  crontab -l 2>/dev/null | grep -v "$TAG" > "$tmp" || true
  crontab "$tmp"
  rm -f "$tmp"
  echo "[$(date '+%Y-%m-%d %H:%M:%S %Z')] completed 6 cycles; cron removed" >> "$LOG_FILE"
fi
