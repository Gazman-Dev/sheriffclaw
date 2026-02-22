#!/bin/bash
set -euo pipefail

# Configuration
REPO_URL="${SHERIFF_REPO_URL:-https://github.com/Gazman-Dev/sheriffclaw.git}"
INSTALL_DIR="${SHERIFF_INSTALL_DIR:-$HOME/.sheriffclaw}"
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

lower() {
    printf '%s' "$1" | tr '[:upper:]' '[:lower:]'
}

is_linux() { [ "$(uname -s)" = "Linux" ]; }
is_macos() { [ "$(uname -s)" = "Darwin" ]; }

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
            err "sandbox-exec is required for strict ai-worker sandbox on macOS."
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

setup_ai_worker_user() {
    local user="${SHERIFF_AI_WORKER_USER:-sheriffai}"
    local strict="${SHERIFF_SETUP_AI_WORKER_USER:-1}"
    if [ "$strict" = "0" ]; then
        return 0
    fi

    if ! is_linux && ! is_macos; then
        return 0
    fi

    if id "$user" >/dev/null 2>&1; then
        log "Using existing ai-worker user: $user"
    else
        log "Creating dedicated ai-worker user: $user"
        if is_linux; then
            if command -v useradd >/dev/null 2>&1; then
                if [ "$(id -u)" -eq 0 ]; then
                    useradd -m -s /usr/sbin/nologin "$user" || true
                else
                    sudo useradd -m -s /usr/sbin/nologin "$user" || true
                fi
            fi
        elif is_macos; then
            warn "Auto-creating users on macOS is not enabled. Create user '$user' manually if needed."
        fi
    fi

    "$VENV_DIR/bin/sheriff-ctl" sandbox --user "$user" --deny-net || true
}

acquire_lock() {
    mkdir -p "$INSTALL_DIR"
    if mkdir "$LOCK_DIR" 2>/dev/null; then
        trap 'rm -rf "$LOCK_DIR"' EXIT
    else
        err "Another installation appears to be running (lock: $LOCK_DIR)."
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

    log "Installing SheriffClaw package..."
    python -m pip install --upgrade pip --quiet
    python -m pip install "$SOURCE_DIR" --quiet
}

setup_alias() {
    local shell_cfg=""
    if [ -f "$HOME/.zshrc" ]; then
        shell_cfg="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        shell_cfg="$HOME/.bashrc"
    elif [ -f "$HOME/.bash_profile" ]; then
        shell_cfg="$HOME/.bash_profile"
    fi

    if [ -n "$shell_cfg" ]; then
        if ! grep -q "alias sheriff=\|$VENV_DIR/bin/sheriff" "$shell_cfg"; then
            echo "alias sheriff='$VENV_DIR/bin/sheriff'" >> "$shell_cfg"
            log "Added alias 'sheriff' to $shell_cfg"
        fi
        if ! grep -q "alias sheriff-ctl=\|$VENV_DIR/bin/sheriff-ctl" "$shell_cfg"; then
            echo "alias sheriff-ctl='$VENV_DIR/bin/sheriff-ctl'" >> "$shell_cfg"
            log "Added alias 'sheriff-ctl' to $shell_cfg"
        fi
    fi
}

run_onboarding_if_needed() {
    local master_file="$INSTALL_DIR/gw/state/master.json"
    local secrets_file="$INSTALL_DIR/gw/state/secrets.enc"

    local existing_install=0
    if [ -f "$master_file" ] && [ -f "$secrets_file" ]; then
        existing_install=1
    fi

    local interactive=0
    if [ "${SHERIFF_NON_INTERACTIVE:-0}" != "1" ] && { [ -t 0 ] || [ -r /dev/tty ]; }; then
        interactive=1
    fi

    echo -e "${BLUE}=========================================${NC}"
    echo -e "${BLUE}           Interactive Setup             ${NC}"
    echo -e "${BLUE}=========================================${NC}"
    echo ""

    if [ "$interactive" = "1" ]; then
        if [ "$existing_install" = "1" ]; then
            echo -e "${YELLOW}Existing installation detected.${NC}"
            if [ -t 0 ]; then
                read -r -p "Factory reset from scratch (wipe ALL Sheriff/Agent data)? [y/N]: " REINSTALL_ANS
            else
                read -r -p "Factory reset from scratch (wipe ALL Sheriff/Agent data)? [y/N]: " REINSTALL_ANS < /dev/tty
            fi
            REINSTALL_ANS_LC="$(lower "$REINSTALL_ANS")"
            if [[ "$REINSTALL_ANS_LC" == "y" || "$REINSTALL_ANS_LC" == "yes" ]]; then
                "$VENV_DIR/bin/sheriff-ctl" factory-reset < /dev/tty > /dev/tty 2>&1 || "$VENV_DIR/bin/sheriff-ctl" factory-reset
            fi
        fi

        if [ -t 0 ]; then
            if ! "$VENV_DIR/bin/sheriff-ctl" onboarding; then
                echo -e "${YELLOW}Onboarding exited.${NC}"
                read -r -p "Do factory reset now? (wipe all data) [y/N]: " RI
                RI_LC="$(lower "$RI")"
                if [[ "$RI_LC" == "y" || "$RI_LC" == "yes" ]]; then
                    "$VENV_DIR/bin/sheriff-ctl" factory-reset
                fi
                return 1
            fi
        else
            if ! "$VENV_DIR/bin/sheriff-ctl" onboarding < /dev/tty > /dev/tty 2>&1; then
                echo -e "${YELLOW}Onboarding exited.${NC}"
                read -r -p "Do factory reset now? (wipe all data) [y/N]: " RI < /dev/tty
                RI_LC="$(lower "$RI")"
                if [[ "$RI_LC" == "y" || "$RI_LC" == "yes" ]]; then
                    "$VENV_DIR/bin/sheriff-ctl" factory-reset < /dev/tty > /dev/tty 2>&1 || "$VENV_DIR/bin/sheriff-ctl" factory-reset
                fi
                return 1
            fi
        fi
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

    "$VENV_DIR/bin/sheriff-ctl" onboarding \
        --master-password "$MP" \
        --llm-provider "$LLM_PROVIDER" \
        --llm-api-key "$LLM_API_KEY" \
        --llm-bot-token "$LLM_BOT_TOKEN" \
        --gate-bot-token "$GATE_BOT_TOKEN" \
        $TELEGRAM_FLAG
}

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}       SheriffClaw Installer Setup       ${NC}"
echo -e "${BLUE}=========================================${NC}"

acquire_lock
ensure_system_dependencies
ensure_sandbox_dependencies
sync_source
setup_venv_and_install
setup_alias
setup_ai_worker_user

if [ "${SHERIFF_START_DAEMONS:-0}" = "1" ]; then
    log "Starting services..."
    "$VENV_DIR/bin/sheriff-ctl" start
    sleep 2
else
    log "Skipping daemon start (services are started on-demand)."
fi

run_onboarding_if_needed

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}       Installation Complete!            ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo "Use 'sheriff' to send a one-shot message or open menu/onboarding."
echo "Use 'sheriff-ctl chat' for terminal chat mode."
echo "Use '/status' inside chat for on-demand health checks."
echo "Restart your terminal to use 'sheriff' and 'sheriff-ctl' directly."