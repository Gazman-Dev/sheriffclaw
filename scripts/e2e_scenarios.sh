#!/bin/bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WITH_DOCKER=0

for arg in "$@"; do
  case "$arg" in
    --with-docker) WITH_DOCKER=1 ;;
    --quick) WITH_DOCKER=0 ;;
    *) echo "Unknown arg: $arg"; echo "Usage: $0 [--quick|--with-docker]"; exit 2 ;;
  esac
done

PASS=0
FAIL=0
RESULTS=()

bootstrap_local() {
  if [ ! -x "${ROOT_DIR}/.venv/bin/python" ]; then
    echo "missing ${ROOT_DIR}/.venv; run local setup first"
    exit 1
  fi
  "${ROOT_DIR}/.venv/bin/pip" install -q "$ROOT_DIR"
}

run_scenario() {
  local name="$1"
  shift
  local start end rc
  start=$(date +%s)
  echo "[scenario] $name"
  set +e
  "$@"
  rc=$?
  set -e
  end=$(date +%s)
  if [ "$rc" -eq 0 ]; then
    PASS=$((PASS+1))
    RESULTS+=("PASS: $name ($((end-start))s)")
  else
    FAIL=$((FAIL+1))
    RESULTS+=("FAIL: $name ($((end-start))s)")
  fi
}

scenario_debug_fifo() {
  local sbin="${ROOT_DIR}/.venv/bin/sheriff"
  local cbin="${ROOT_DIR}/.venv/bin/sheriff-ctl"
  [ -x "$sbin" ] && [ -x "$cbin" ]

  local tmp_root
  tmp_root="$(mktemp -d)"
  export SHERIFFCLAW_ROOT="$tmp_root"
  trap 'rm -rf "${tmp_root:-}"' RETURN

  "$cbin" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null
  "$sbin" --debug on >/dev/null

  mkdir -p "$tmp_root/gw/state"
  cat > "$tmp_root/gw/state/debug.agent.jsonl" <<'EOF'
{"text":"debug-one"}
{"text":"debug-two"}
EOF

  local o1 o2 o3
  o1="$(mktemp)"; o2="$(mktemp)"; o3="$(mktemp)"
  "$sbin" "hello" > "$o1"
  "$sbin" "hello" > "$o2"
  "$sbin" "hello" > "$o3" 2>&1 || true

  grep -q "debug-one" "$o1"
  grep -q "debug-two" "$o2"
  ! grep -q "\[AGENT\]" "$o3"
}

scenario_keep_unchanged_onboard() {
  local cbin="${ROOT_DIR}/.venv/bin/sheriff-ctl"
  [ -x "$cbin" ]

  local tmp_root
  tmp_root="$(mktemp -d)"
  export SHERIFFCLAW_ROOT="$tmp_root"
  trap 'rm -rf "${tmp_root:-}"' RETURN

  "$cbin" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null
  printf "k\n\n\n\n" | "$cbin" onboard --master-password masterpass --keep-unchanged >/dev/null

  local prov
  prov="$(${ROOT_DIR}/.venv/bin/python - <<'PY'
from pathlib import Path
from shared.secrets_state import SecretsState
import os
root = Path(os.environ['SHERIFFCLAW_ROOT']) / 'gw' / 'state'
st = SecretsState(root / 'secrets.enc', root / 'master.json')
assert st.unlock('masterpass')
print(st.get_llm_provider())
PY
)"
  [ "$prov" = "stub" ]
}

scenario_one_shot_wait_10s() {
  local sbin="${ROOT_DIR}/.venv/bin/sheriff"
  local cbin="${ROOT_DIR}/.venv/bin/sheriff-ctl"
  [ -x "$sbin" ] && [ -x "$cbin" ]

  local tmp_root
  tmp_root="$(mktemp -d)"
  export SHERIFFCLAW_ROOT="$tmp_root"
  trap 'rm -rf "${tmp_root:-}"' RETURN

  "$cbin" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null
  "$sbin" --debug on >/dev/null
  mkdir -p "$tmp_root/gw/state"
  echo '{"text":"timing"}' > "$tmp_root/gw/state/debug.agent.jsonl"

  local start end elapsed
  start=$(date +%s)
  "$sbin" "hello" >/dev/null
  end=$(date +%s)
  elapsed=$((end - start))
  [ "$elapsed" -ge 9 ] && [ "$elapsed" -le 20 ]
}

scenario_one_shot_esc_cancel() {
  local sbin="${ROOT_DIR}/.venv/bin/sheriff"
  local cbin="${ROOT_DIR}/.venv/bin/sheriff-ctl"
  [ -x "$sbin" ] && [ -x "$cbin" ]

  local tmp_root
  tmp_root="$(mktemp -d)"
  export SHERIFFCLAW_ROOT="$tmp_root"
  trap 'rm -rf "${tmp_root:-}"' RETURN

  "$cbin" onboard --master-password masterpass --llm-provider stub --llm-api-key "" --llm-bot-token "" --gate-bot-token "" --deny-telegram >/dev/null
  "$sbin" --debug on >/dev/null
  mkdir -p "$tmp_root/gw/state"
  echo '{"text":"esc-test"}' > "$tmp_root/gw/state/debug.agent.jsonl"

  local out t cancelled
  out="$(ROOT_DIR="$ROOT_DIR" ${ROOT_DIR}/.venv/bin/python - <<'PY'
import os, pty, subprocess, time, select
sbin = os.path.join(os.environ['ROOT_DIR'], '.venv/bin/sheriff')
start = time.time()
master, slave = pty.openpty()
p = subprocess.Popen([sbin, 'hello'], stdin=slave, stdout=slave, stderr=slave, close_fds=True)
os.close(slave)
buf = b''
sent = False
while time.time() - start < 12:
    r, _, _ = select.select([master], [], [], 0.2)
    if r:
        chunk = os.read(master, 4096)
        if not chunk:
            break
        buf += chunk
    if (not sent) and (time.time() - start > 2.0):
        os.write(master, b'\x1b')
        sent = True
    if p.poll() is not None:
        break
if p.poll() is None:
    p.wait(timeout=5)
print(f"{time.time()-start:.3f}|{int(b'(wait cancelled)' in buf)}")
PY
)"
  t="${out%%|*}"
  cancelled="${out##*|}"
  [ "$cancelled" = "1" ]
  awk -v t="$t" 'BEGIN { exit !(t < 9.5) }'
}

bootstrap_local
run_scenario "sheriff_entry" "$ROOT_DIR/scripts/e2e_sheriff_entry.sh"
run_scenario "debug_fifo" scenario_debug_fifo
run_scenario "keep_unchanged_onboard" scenario_keep_unchanged_onboard
run_scenario "one_shot_wait_10s" scenario_one_shot_wait_10s
run_scenario "one_shot_esc_cancel" scenario_one_shot_esc_cancel
if [ "$WITH_DOCKER" -eq 1 ]; then
  run_scenario "docker_fresh_install" "$ROOT_DIR/scripts/e2e_fresh_install_docker.sh"
fi

echo ""
echo "=== Scenario Results ==="
printf '%s\n' "${RESULTS[@]}"
echo "Passed: $PASS"
echo "Failed: $FAIL"

if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
