#!/bin/bash
set -euo pipefail

home_for_user() {
    local user="$1"
    if command -v getent >/dev/null 2>&1; then
        getent passwd "$user" | cut -d: -f6
        return 0
    fi
    if [ "$(uname -s)" = "Darwin" ] && command -v dscl >/dev/null 2>&1; then
        dscl . -read "/Users/$user" NFSHomeDirectory 2>/dev/null | awk '{print $2}'
        return 0
    fi
    awk -F: -v target="$user" '$1 == target { print $6; exit }' /etc/passwd
}

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        err "Run the installer as root so it does not need to prompt for sudo."
        err "Example: curl -fsSL <installer-url> | sudo bash"
        exit 1
    fi
}

# Configuration
REPO_URL="${SHERIFF_REPO_URL:-https://github.com/Gazman-Dev/sheriffclaw.git}"
INVOKING_USER="${SUDO_USER:-$(id -un)}"
INVOKING_HOME="${SUDO_HOME:-$(home_for_user "$INVOKING_USER")}"
[ -n "$INVOKING_HOME" ] || INVOKING_HOME="$HOME"
INSTALL_DIR="${SHERIFF_INSTALL_DIR:-$INVOKING_HOME/.sheriffclaw}"
SOURCE_DIR="$INSTALL_DIR/source"
VENV_DIR="$INSTALL_DIR/venv"
LOCK_DIR="$INSTALL_DIR/.install.lock"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[0;33m'
RED='\033[0;31m'
NC='\033[0m'

log() { echo -e "${GREEN}[+] $*${NC}"; }
warn() { echo -e "${YELLOW}[!] $*${NC}"; }
err() { echo -e "${RED}[!] $*${NC}"; }

# Keep installer output clean for end-users.
export PYTHONWARNINGS="ignore"

reset_terminal_state() {
    if [ -r /dev/tty ] && [ -w /dev/tty ]; then
        stty sane < /dev/tty 2>/dev/null || true
        printf '\033[0m' > /dev/tty 2>/dev/null || true
        return 0
    fi
    stty sane 2>/dev/null || true
    printf '\033[0m' 2>/dev/null || true
}

print_install_version() {
    local sheriff_version="unknown"
    local source_commit="unknown"
    if [ -f "$SOURCE_DIR/versions.json" ]; then
        sheriff_version="$(python3 - <<PY 2>/dev/null || true
import json
from pathlib import Path
fp = Path(r"$SOURCE_DIR") / "versions.json"
try:
    payload = json.loads(fp.read_text(encoding="utf-8"))
    print(payload.get("sheriff", "unknown"))
except Exception:
    print("unknown")
PY
)"
    fi
    if [ -d "$SOURCE_DIR/.git" ]; then
        source_commit="$(git -C "$SOURCE_DIR" rev-parse --short HEAD 2>/dev/null || printf 'unknown')"
    fi
    echo "installer version: sheriff=${sheriff_version} commit=${source_commit}"
}

lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

run_as_invoking_user() {
    if [ "$(id -u)" -eq 0 ] && [ "$INVOKING_USER" != "root" ]; then
        sudo -u "$INVOKING_USER" env HOME="$INVOKING_HOME" SHERIFFCLAW_ROOT="$INSTALL_DIR" "$@"
        return $?
    fi
    HOME="$INVOKING_HOME" SHERIFFCLAW_ROOT="$INSTALL_DIR" "$@"
}

is_linux() { [ "$(uname -s)" = "Linux" ]; }
is_macos() { [ "$(uname -s)" = "Darwin" ]; }

prompt_yes_no() {
    local prompt="$1"
    local reply=""
    if [ -t 0 ]; then
        read -r -p "$prompt" reply
    elif [ -r /dev/tty ] && [ -w /dev/tty ]; then
        read -r -p "$prompt" reply < /dev/tty
    else
        return 1
    fi
    reply="$(lower "$reply")"
    [[ "$reply" == "y" || "$reply" == "yes" ]]
}

run_pkg_install() {
    if command -v apt-get >/dev/null 2>&1; then
        local sudo_cmd=""
        [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
        $sudo_cmd apt-get update -y
        $sudo_cmd apt-get install -y "$@"
        return 0
    fi
    if command -v dnf >/dev/null 2>&1; then
        local sudo_cmd=""
        [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
        $sudo_cmd dnf install -y "$@"
        return 0
    fi
    if command -v yum >/dev/null 2>&1; then
        local sudo_cmd=""
        [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
        $sudo_cmd yum install -y "$@"
        return 0
    fi
    if command -v apk >/dev/null 2>&1; then
        local sudo_cmd=""
        [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
        $sudo_cmd apk add --no-cache "$@"
        return 0
    fi
    return 1
}

ensure_system_dependencies() {
    local missing=()
    command -v git >/dev/null 2>&1 || missing+=("git")
    command -v python3 >/dev/null 2>&1 || missing+=("python3")

    if [ ${#missing[@]} -eq 0 ]; then
        return 0
    fi

    warn "Missing required tools: ${missing[*]}"

    if is_macos; then
        if ! command -v brew >/dev/null 2>&1; then
            err "Homebrew is required to auto-install dependencies on macOS."
            err "Install Homebrew, then run: brew install git python"
            exit 1
        fi
        log "Installing dependencies via Homebrew..."
        brew install git python
        return 0
    fi

    if is_linux; then
        log "Installing dependencies via system package manager..."
        if command -v apt-get >/dev/null 2>&1; then
            run_pkg_install git python3 python3-venv python3-pip ca-certificates curl sudo
            return 0
        fi
        if command -v dnf >/dev/null 2>&1; then
            run_pkg_install git python3 python3-pip ca-certificates curl sudo
            return 0
        fi
        if command -v yum >/dev/null 2>&1; then
            run_pkg_install git python3 python3-pip ca-certificates curl sudo
            return 0
        fi
        if command -v apk >/dev/null 2>&1; then
            run_pkg_install git python3 py3-pip py3-virtualenv ca-certificates curl sudo
            return 0
        fi
    fi

    err "Could not auto-install dependencies on this OS/package manager."
    exit 1
}

ensure_sandbox_dependencies() {
    if is_macos; then
        if ! command -v sandbox-exec >/dev/null 2>&1; then
            err "sandbox-exec is required for strict codex-mcp-host sandbox on macOS."
            exit 1
        fi
        return 0
    fi

    if is_linux; then
        if command -v bwrap >/dev/null 2>&1; then
            return 0
        fi
        log "Installing Linux sandbox dependency (bubblewrap)..."
        if command -v apt-get >/dev/null 2>&1; then
            run_pkg_install bubblewrap
            return 0
        fi
        if command -v dnf >/dev/null 2>&1; then
            run_pkg_install bubblewrap
            return 0
        fi
        if command -v yum >/dev/null 2>&1; then
            run_pkg_install bubblewrap
            return 0
        fi
        if command -v apk >/dev/null 2>&1; then
            run_pkg_install bubblewrap
            return 0
        fi
        err "Could not install bubblewrap on this Linux distribution."
        exit 1
    fi
}

next_macos_uid() {
    local sudo_cmd=""
    [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
    $sudo_cmd dscl . -list /Users UniqueID 2>/dev/null | awk '
        BEGIN { max = 500 }
        { if ($2 ~ /^[0-9]+$/ && $2 > max) max = $2 }
        END { print max + 1 }
    '
}

create_macos_service_user() {
    local user="$1"
    local group="${2:-sheriffclaw}"
    local sudo_cmd=""
    local uid
    local gid
    [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"

    if ! command -v dscl >/dev/null 2>&1; then
        err "dscl is required to create the dedicated codex-mcp-host user on macOS."
        return 1
    fi

    uid="$(next_macos_uid)"
    [ -n "$uid" ] || {
        err "Could not determine a UniqueID for macOS service user creation."
        return 1
    }

    gid="$($sudo_cmd dscl . -list /Groups PrimaryGroupID 2>/dev/null | awk -v target="$(printf '%s' "$group" | tr '[:upper:]' '[:lower:]')" '
        BEGIN { max = 500; found = "" }
        {
            name = tolower($1)
            if ($2 ~ /^[0-9]+$/ && $2 > max) max = $2
            if (name == target) found = $2
        }
        END {
            if (found != "") print found
            else print max + 1
        }
    ')"
    [ -n "$gid" ] || {
        err "Could not determine a PrimaryGroupID for macOS service group creation."
        return 1
    }

    if ! $sudo_cmd dscl . -read "/Groups/$group" >/dev/null 2>&1; then
        log "Creating dedicated codex-mcp-host group on macOS: $group (gid=$gid)"
        $sudo_cmd dscl . -create "/Groups/$group"
        $sudo_cmd dscl . -create "/Groups/$group" PrimaryGroupID "$gid"
        $sudo_cmd dscl . -create "/Groups/$group" RealName "SheriffClaw Service Group"
        $sudo_cmd dscl . -append "/Groups/$group" GroupMembership "$user" || true
    else
        gid="$($sudo_cmd dscl . -read "/Groups/$group" PrimaryGroupID | awk '{print $2}')"
    fi

    log "Creating dedicated codex-mcp-host user on macOS: $user (uid=$uid, gid=$gid)"
    $sudo_cmd dscl . -create "/Users/$user"
    $sudo_cmd dscl . -create "/Users/$user" UserShell /usr/bin/false
    $sudo_cmd dscl . -create "/Users/$user" RealName "Sheriff AI Worker"
    $sudo_cmd dscl . -create "/Users/$user" UniqueID "$uid"
    $sudo_cmd dscl . -create "/Users/$user" PrimaryGroupID "$gid"
    $sudo_cmd dscl . -create "/Users/$user" NFSHomeDirectory "/Users/$user"
    $sudo_cmd dscl . -create "/Users/$user" IsHidden 1
    $sudo_cmd mkdir -p "/Users/$user"
    $sudo_cmd dscl . -append "/Groups/$group" GroupMembership "$user" || true
    $sudo_cmd chown "$user":"$group" "/Users/$user"
    $sudo_cmd chmod 700 "/Users/$user"
}

install_macos_ai_worker_launcher() {
    local invoking_user="$1"
    local worker_user="$2"
    local worker_group="${3:-sheriffclaw}"
    local launcher="/usr/local/bin/sheriff-codex-mcp-host-launch"
    local sudoers_dir="/private/etc/sudoers.d"
    local sudoers_file="$sudoers_dir/sheriffclaw-codex-mcp-host"
    local runtime_root="/Users/$worker_user/ai-runtime"
    local sudo_cmd=""
    local tmp_launcher
    local tmp_sudoers
    local runtime_source
    local py_ver
    local site_packages
    [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"

    runtime_source="$("$VENV_DIR/bin/python" - <<'PY'
from pathlib import Path
import sys
print(Path(sys.executable).resolve().parent.parent)
PY
)"
    py_ver="$("$VENV_DIR/bin/python" - <<'PY'
import sys
print(f"{sys.version_info.major}.{sys.version_info.minor}")
PY
)"
    site_packages="$INSTALL_DIR/venv/lib/python$py_ver/site-packages"

    $sudo_cmd mkdir -p "$runtime_root"
    $sudo_cmd rm -rf "$runtime_root"
    $sudo_cmd cp -R "$runtime_source" "$runtime_root"
    $sudo_cmd chown -R "$worker_user":"$worker_group" "$runtime_root"
    $sudo_cmd chmod -R u+rwX,go-rwx "$runtime_root"

    tmp_launcher="$(mktemp)"
    cat > "$tmp_launcher" <<EOF
#!/bin/bash
set -euo pipefail
pidfile="/private/tmp/sheriffclaw/ai_worker.pid"
mkdir -p "/private/tmp/sheriffclaw"

stop_worker() {
    if [ -f "\$pidfile" ]; then
        pid="\$(cat "\$pidfile" 2>/dev/null || true)"
        if [ -n "\${pid:-}" ] && kill -0 "\$pid" 2>/dev/null; then
            kill -TERM "\$pid" 2>/dev/null || true
            for _ in 1 2 3 4 5 6 7 8 9 10; do
                if ! kill -0 "\$pid" 2>/dev/null; then
                    break
                fi
                sleep 0.2
            done
            kill -KILL "\$pid" 2>/dev/null || true
        fi
        rm -f "\$pidfile"
    fi
    pkill -f "services.ai_worker.__main__" 2>/dev/null || true
    pkill -f "/opt/homebrew/bin/codex chat --no-alt-screen" 2>/dev/null || true
}

case "\${1:-run}" in
    stop)
        stop_worker
        exit 0
        ;;
    status)
        if [ -f "\$pidfile" ]; then
            pid="\$(cat "\$pidfile" 2>/dev/null || true)"
            if [ -n "\${pid:-}" ] && kill -0 "\$pid" 2>/dev/null; then
                printf '%s\n' "\$pid"
                exit 0
            fi
        fi
        pgrep -f "services.ai_worker.__main__" | head -n 1
        exit \$?
        ;;
esac

cd "/Users/$worker_user"
export HOME="/Users/$worker_user"
export PYTHONHOME="$runtime_root"
export PYTHONPATH="$site_packages"
export SHERIFFCLAW_ROOT="$INSTALL_DIR"
export SHERIFF_RPC_HOST="127.0.0.1"
export SHERIFF_RPC_PORT="47610"
stop_worker
/usr/bin/sandbox-exec -f "/private/tmp/sheriffclaw/ai_worker.sb" "$runtime_root/bin/python$py_ver" -m services.ai_worker.__main__ </dev/null &
child=\$!
printf '%s\n' "\$child" > "\$pidfile"
trap 'kill -TERM "\$child" 2>/dev/null || true; wait "\$child" 2>/dev/null || true; rm -f "\$pidfile"' TERM INT EXIT
wait "\$child"
EOF
    $sudo_cmd install -o root -g wheel -m 755 "$tmp_launcher" "$launcher"
    rm -f "$tmp_launcher"

    tmp_sudoers="$(mktemp)"
    printf '%s ALL=(%s) NOPASSWD: %s\n' "$invoking_user" "$worker_user" "$launcher" > "$tmp_sudoers"
    $sudo_cmd mkdir -p "$sudoers_dir"
    $sudo_cmd install -o root -g wheel -m 440 "$tmp_sudoers" "$sudoers_file"
    rm -f "$tmp_sudoers"

    if command -v visudo >/dev/null 2>&1; then
        $sudo_cmd visudo -cf "$sudoers_file" >/dev/null
    fi
}

repair_ai_worker_shared_paths() {
    local owner_user="$1"
    local worker_group="${2:-sheriffclaw}"
    local sudo_cmd=""
    [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"

    local paths=(
        "$INSTALL_DIR/gw"
        "$INSTALL_DIR/llm"
        "$INSTALL_DIR/agents/codex"
        "$INSTALL_DIR/agent_repo"
    )

    for p in "${paths[@]}"; do
        $sudo_cmd mkdir -p "$p"
        $sudo_cmd chown -R "$owner_user":"$worker_group" "$p"
        $sudo_cmd find "$p" -type d -exec chmod 2775 {} \;
        $sudo_cmd find "$p" -type f -exec chmod 664 {} \;
    done

    $sudo_cmd mkdir -p "/private/tmp/sheriffclaw"
    $sudo_cmd chgrp "$worker_group" "/private/tmp/sheriffclaw"
    $sudo_cmd chmod 2775 "/private/tmp/sheriffclaw"
    for p in "/private/tmp/sheriffclaw/ai_worker.sb" "/private/tmp/sheriffclaw/ai_worker.pid"; do
        [ -e "$p" ] || continue
        $sudo_cmd chgrp "$worker_group" "$p"
        $sudo_cmd chmod 664 "$p"
    done
}

setup_ai_worker_user() {
    local user="${SHERIFF_AI_WORKER_USER:-sheriffai}"
    local group="${SHERIFF_AI_WORKER_GROUP:-sheriffclaw}"
    local allow_net="${SHERIFF_AI_WORKER_ALLOW_NET:-1}"
    local strict="${SHERIFF_SETUP_AI_WORKER_USER:-1}"
    if [ "$strict" = "0" ]; then
        return 0
    fi

    if ! is_linux && ! is_macos; then
        return 0
    fi

    if id "$user" >/dev/null 2>&1; then
        log "Using existing codex-mcp-host user: $user"
    else
        log "Creating dedicated codex-mcp-host user: $user"
        if is_linux; then
            if command -v useradd >/dev/null 2>&1; then
                if [ "$(id -u)" -eq 0 ]; then
                    useradd -m -s /usr/sbin/nologin "$user"
                else
                    sudo useradd -m -s /usr/sbin/nologin "$user"
                fi
            fi
        elif is_macos; then
            create_macos_service_user "$user" "$group"
        fi
    fi

    if ! id "$user" >/dev/null 2>&1; then
        err "Dedicated codex-mcp-host user '$user' is required but was not created successfully."
        exit 1
    fi

    if is_macos; then
        install_macos_ai_worker_launcher "$INVOKING_USER" "$user" "$group"
    fi

    if [ "$allow_net" = "0" ] || [ "$allow_net" = "false" ] || [ "$allow_net" = "no" ]; then
        run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" sandbox --user "$user" --deny-net
    else
        run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" sandbox --user "$user" --allow-net
    fi

    repair_ai_worker_shared_paths "$INVOKING_USER" "$group"
}

acquire_lock() {
    mkdir -p "$INSTALL_DIR"
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        printf '%s\n' "$$" > "$LOCK_DIR/pid"
        trap 'rm -rf "$LOCK_DIR"' EXIT
    else
        local lock_pid=""
        if [ -f "$LOCK_DIR/pid" ]; then
            lock_pid="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
        fi
        if [ -n "$lock_pid" ] && kill -0 "$lock_pid" 2>/dev/null; then
            warn "Another installation appears to be running (lock: $LOCK_DIR, pid=$lock_pid)."
            if prompt_yes_no "Kill the other installation and start fresh? [y/N]: "; then
                kill -TERM "$lock_pid" 2>/dev/null || true
                sleep 1
                if kill -0 "$lock_pid" 2>/dev/null; then
                    pkill -P "$lock_pid" 2>/dev/null || true
                    kill -KILL "$lock_pid" 2>/dev/null || true
                fi
                rm -rf "$LOCK_DIR"
                mkdir "$LOCK_DIR"
                printf '%s\n' "$$" > "$LOCK_DIR/pid"
                trap 'rm -rf "$LOCK_DIR"' EXIT
                warn "Previous installer process was terminated; continuing with a fresh install run."
                return 0
            fi
            err "Installation aborted because another installer is still running."
            exit 1
        fi

        warn "A stale installation lock exists at $LOCK_DIR."
        if prompt_yes_no "Remove the stale lock and continue? [y/N]: "; then
            rm -rf "$LOCK_DIR"
            mkdir "$LOCK_DIR"
            printf '%s\n' "$$" > "$LOCK_DIR/pid"
            trap 'rm -rf "$LOCK_DIR"' EXIT
            warn "Removed stale install lock; continuing."
            return 0
        fi
        err "Installation aborted because the existing install lock was not cleared."
        exit 1
    fi
}

sync_source() {
    if [ -d "$SOURCE_DIR/.git" ]; then
        log "Updating existing SheriffClaw source checkout..."
        git -C "$SOURCE_DIR" fetch --quiet origin
        git -C "$SOURCE_DIR" checkout -q main || true
        git -C "$SOURCE_DIR" reset --hard -q origin/main
    else
        rm -rf "$SOURCE_DIR"
        log "Cloning SheriffClaw..."
        git clone --quiet "$REPO_URL" "$SOURCE_DIR"
    fi
}

setup_venv_and_install() {
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        log "Creating virtual environment..."
        python3 -m venv "$VENV_DIR"
    else
        log "Reusing existing virtual environment..."
    fi

    # shellcheck disable=SC1090
    source "$VENV_DIR/bin/activate"

    # macOS can deny os.getcwd() for protected/unavailable paths, and pip calls
    # os.getcwd() on startup. Force a known-safe working directory first.
    if ! cd "$SOURCE_DIR" 2>/dev/null; then
        cd "$INSTALL_DIR"
    fi

    log "Installing SheriffClaw package..."
    export PIP_CACHE_DIR="$INSTALL_DIR/.cache/pip"
    mkdir -p "$PIP_CACHE_DIR"
    python -m pip install --upgrade pip --quiet
    python -m pip install "$SOURCE_DIR" --quiet
}

repair_install_dir_ownership() {
    local sudo_cmd=""
    [ "$(id -u)" -ne 0 ] && sudo_cmd="sudo"
    $sudo_cmd mkdir -p "$INSTALL_DIR"
    $sudo_cmd chown -R "$INVOKING_USER" "$INSTALL_DIR"
}

sync_agent_workspace_template() {
    local src="$SOURCE_DIR/agents/codex"
    local dst="$INSTALL_DIR/agents/codex"
    mkdir -p "$dst"
    if [ -d "$src" ]; then
        # Seed only missing files; preserve user auth/session state.
        cp -R -n "$src"/. "$dst"/ 2>/dev/null || true
        log "Agent workspace template synced to $dst"
    else
        warn "Agent workspace template not found at $src; created empty $dst"
    fi
}

setup_alias() {
    local shell_cfg=""
    if [ -f "$INVOKING_HOME/.zshrc" ]; then
        shell_cfg="$INVOKING_HOME/.zshrc"
    elif [ -f "$INVOKING_HOME/.bashrc" ]; then
        shell_cfg="$INVOKING_HOME/.bashrc"
    elif [ -f "$INVOKING_HOME/.bash_profile" ]; then
        shell_cfg="$INVOKING_HOME/.bash_profile"
    fi

    if [ -z "$shell_cfg" ]; then
        return 0
    fi

    # Never persist aliases pointing to temporary/custom test install dirs.
    local canonical_venv="$INVOKING_HOME/.sheriffclaw/venv"

    # Replace any previous sheriff aliases with canonical target.
    local tmpf
    tmpf="$(mktemp)"
    grep -vE "^alias sheriff=|^alias sheriff-ctl=" "$shell_cfg" > "$tmpf" || true
    mv "$tmpf" "$shell_cfg"

    echo "alias sheriff='$canonical_venv/bin/sheriff'" >> "$shell_cfg"
    echo "alias sheriff-ctl='$canonical_venv/bin/sheriff-ctl'" >> "$shell_cfg"
    log "Updated aliases in $shell_cfg"
}

run_onboarding_if_needed() {
    local state_dir="$INSTALL_DIR/gw/state"

    local existing_install=0
    if [ -d "$state_dir" ]; then
        # Legacy vault markers (pre-sqlite)
        if [ -f "$state_dir/master.json" ] || [ -f "$state_dir/secrets.enc" ]; then
            existing_install=1
        fi
        # Current vault marker (sqlite-backed)
        if [ -f "$state_dir/secrets.db" ]; then
            existing_install=1
        fi
        # Fallback: any persisted runtime state means this is not a first install
        if [ "$existing_install" = "0" ] && [ -n "$(find "$state_dir" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null || true)" ]; then
            existing_install=1
        fi
    fi

    local interactive=0
    if [ "${SHERIFF_NON_INTERACTIVE:-0}" != "1" ] && [ -r /dev/tty ] && [ -w /dev/tty ]; then
        interactive=1
    fi

    echo -e "${BLUE}=========================================${NC}"
    echo -e "${BLUE}           Interactive Setup             ${NC}"
    echo -e "${BLUE}=========================================${NC}"
    echo ""

    if [ "$interactive" = "1" ]; then
        local skip_onboarding=0
        local ENABLE_DEBUG_MODE=0
        local KEEP_UNCHANGED=0
        if [ "$existing_install" = "1" ]; then
            echo -e "${YELLOW}Existing installation detected.${NC}"
            echo "Choose action:"
            echo "  1) Start onboarding"
            echo "  2) Update existing install"
            echo "  3) Factory reset (wipe ALL Sheriff/Agent data), then onboarding"
            echo "  4) Factory reset + onboarding in DEBUG mode"
            while true; do
                if [ -t 0 ]; then
                    read -r -p "Select [1/2/3/4]: " SETUP_CHOICE
                else
                    read -r -p "Select [1/2/3/4]: " SETUP_CHOICE < /dev/tty
                fi
                case "$SETUP_CHOICE" in
                    1|2|3|4)
                        break
                        ;;
                    *)
                        echo "Please enter 1, 2, 3, or 4."
                        ;;
                esac
            done

            case "$SETUP_CHOICE" in
                2)
                    if [ -t 0 ]; then
                        run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" update
                    else
                        run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" update < /dev/tty > /dev/tty 2>&1
                    fi
                    skip_onboarding=1
                    ;;
                3)
                    if [ -t 0 ]; then
                        run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" factory-reset || true
                    else
                        run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" factory-reset < /dev/tty > /dev/tty 2>&1 || true
                    fi
                    ;;
                4)
                    ENABLE_DEBUG_MODE=1
                    if [ -t 0 ]; then
                        run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" factory-reset || true
                    else
                        run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" factory-reset < /dev/tty > /dev/tty 2>&1 || true
                    fi
                    ;;
                1|*)
                    KEEP_UNCHANGED=1
                    ;;
            esac
        fi

        if [ "$skip_onboarding" = "1" ]; then
            return 0
        fi

        local DEBUG_MODE_FLAG=""
        if [ "${ENABLE_DEBUG_MODE:-0}" = "1" ] || [ "${SHERIFF_DEBUG_MODE:-0}" = "1" ]; then
            DEBUG_MODE_FLAG="--debug-mode"
            warn "Debug mode requested: onboarding will enable deterministic debug mode after setup."
        fi
        local KEEP_FLAG=""
        if [ "${KEEP_UNCHANGED:-0}" = "1" ]; then
            KEEP_FLAG="--keep-unchanged"
        fi

        if [ -t 0 ]; then
            if ! run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" onboarding ${KEEP_FLAG:+$KEEP_FLAG} ${DEBUG_MODE_FLAG:+$DEBUG_MODE_FLAG}; then
                echo -e "${YELLOW}Onboarding exited.${NC}"
                read -r -p "Do factory reset now? (wipe all data) [y/N]: " RI
                RI_LC="$(lower "$RI")"
                if [[ "$RI_LC" == "y" || "$RI_LC" == "yes" ]]; then
                    run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" factory-reset
                fi
                return 1
            fi
        else
            if ! run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" onboarding ${KEEP_FLAG:+$KEEP_FLAG} ${DEBUG_MODE_FLAG:+$DEBUG_MODE_FLAG} < /dev/tty > /dev/tty 2>&1; then
                echo -e "${YELLOW}Onboarding exited.${NC}"
                read -r -p "Do factory reset now? (wipe all data) [y/N]: " RI < /dev/tty
                RI_LC="$(lower "$RI")"
                if [[ "$RI_LC" == "y" || "$RI_LC" == "yes" ]]; then
                    run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" factory-reset < /dev/tty > /dev/tty 2>&1 || run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" factory-reset
                fi
                return 1
            fi
        fi
        return 0
    fi

    if [ "$existing_install" = "1" ] && [ "${SHERIFF_FORCE_ONBOARDING:-0}" != "1" ]; then
        log "Existing install detected in non-interactive mode; running update (no reset)."
        run_as_invoking_user "$VENV_DIR/bin/sheriff" update --no-pull || true
        return 0
    fi

    MP="${SHERIFF_MASTER_PASSWORD:-local-dev-master-password}"
    LLM_PROVIDER="${SHERIFF_LLM_PROVIDER:-stub}"
    LLM_API_KEY="${SHERIFF_LLM_API_KEY:-}"
    LLM_BOT_TOKEN="${SHERIFF_LLM_BOT_TOKEN:-}"
    GATE_BOT_TOKEN="${SHERIFF_GATE_BOT_TOKEN:-}"

    TELEGRAM_FLAG="--deny-telegram"
    if [ "${SHERIFF_ALLOW_TELEGRAM_UNLOCK:-0}" = "1" ]; then
        TELEGRAM_FLAG="--allow-telegram"
    fi

    DEBUG_FLAG=""
    if [ "${SHERIFF_DEBUG_MODE:-0}" = "1" ]; then
        DEBUG_FLAG="--debug-mode"
    fi

    run_as_invoking_user "$VENV_DIR/bin/sheriff-ctl" onboarding \
        --master-password "$MP" \
        --llm-provider "$LLM_PROVIDER" \
        --llm-api-key "$LLM_API_KEY" \
        --llm-bot-token "$LLM_BOT_TOKEN" \
        --gate-bot-token "$GATE_BOT_TOKEN" \
        $TELEGRAM_FLAG \
        $DEBUG_FLAG
}

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}       SheriffClaw Installer Setup       ${NC}"
echo -e "${BLUE}=========================================${NC}"

require_root
export HOME="$INVOKING_HOME"
trap 'reset_terminal_state' EXIT

acquire_lock
ensure_system_dependencies
ensure_sandbox_dependencies
sync_source
print_install_version
sync_agent_workspace_template
setup_venv_and_install
repair_install_dir_ownership
setup_alias
setup_ai_worker_user

run_onboarding_if_needed

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}       Installation Complete!            ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo "Use 'sheriff' to send a one-shot message or open menu/onboarding."
echo "Use 'sheriff-ctl chat' for terminal chat mode."
echo "Use '/status' inside chat for on-demand health checks."
echo "Restart your terminal to use 'sheriff' and 'sheriff-ctl' directly."
