#!/bin/bash
set -e

# Configuration
REPO_URL="https://github.com/Gazman-Dev/sheriffclaw.git"
INSTALL_DIR="$HOME/.sheriffclaw"
SOURCE_DIR="$INSTALL_DIR/source"
VENV_DIR="$INSTALL_DIR/venv"

# Colors
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}       SheriffClaw Installer Setup       ${NC}"
echo -e "${BLUE}=========================================${NC}"

# Check Python Version
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}[!] Python 3 is required but not found.${NC}"
    exit 1
fi

# Ensure git is installed
if ! command -v git &> /dev/null; then
    echo -e "${RED}[!] Git is required but not found.${NC}"
    exit 1
fi

echo -e "${GREEN}[+] Setting up installation directory at $INSTALL_DIR...${NC}"
mkdir -p "$INSTALL_DIR"
rm -rf "$SOURCE_DIR"

echo -e "${GREEN}[+] Cloning SheriffClaw...${NC}"
git clone --quiet "$REPO_URL" "$SOURCE_DIR"

echo -e "${GREEN}[+] Creating virtual environment...${NC}"
python3 -m venv "$VENV_DIR"
source "$VENV_DIR/bin/activate"

echo -e "${GREEN}[+] Installing dependencies...${NC}"
pip install --upgrade pip --quiet
# Installs dependencies defined in pyproject.toml (chromadb, cryptography, etc)
pip install "$SOURCE_DIR" --quiet

# Alias Setup
SHELL_CFG=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_CFG="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_CFG="$HOME/.bashrc"
elif [ -f "$HOME/.bash_profile" ]; then
    SHELL_CFG="$HOME/.bash_profile"
fi

if [ -n "$SHELL_CFG" ]; then
    if ! grep -q "alias sheriff-ctl=\|$VENV_DIR/bin/sheriff-ctl" "$SHELL_CFG"; then
        echo "alias sheriff-ctl='$VENV_DIR/bin/sheriff-ctl'" >> "$SHELL_CFG"
        echo -e "${GREEN}[+] Added alias 'sheriff-ctl' to $SHELL_CFG${NC}"
    fi
fi

if [ "${SHERIFF_START_DAEMONS:-0}" = "1" ]; then
    echo -e "${GREEN}[+] Starting Services...${NC}"
    "$VENV_DIR/bin/sheriff-ctl" start
    sleep 2
else
    echo -e "${GREEN}[+] Skipping daemon start (services are started on-demand).${NC}"
fi

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}           Interactive Setup             ${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# Run onboarding (interactive when TTY is available, non-interactive otherwise)
if [ -t 0 ]; then
    "$VENV_DIR/bin/sheriff-ctl" onboard
else
    MP="${SHERIFF_MASTER_PASSWORD:-}"
    if [ -z "$MP" ]; then
        MP="local-dev-master-password"
    fi
    LLM_PROVIDER="${SHERIFF_LLM_PROVIDER:-stub}"
    LLM_API_KEY="${SHERIFF_LLM_API_KEY:-}"
    LLM_BOT_TOKEN="${SHERIFF_LLM_BOT_TOKEN:-}"
    GATE_BOT_TOKEN="${SHERIFF_GATE_BOT_TOKEN:-}"

    TELEGRAM_FLAG="--deny-telegram"
    if [ "${SHERIFF_ALLOW_TELEGRAM_UNLOCK:-0}" = "1" ]; then
        TELEGRAM_FLAG="--allow-telegram"
    fi

    "$VENV_DIR/bin/sheriff-ctl" onboard \
        --master-password "$MP" \
        --llm-provider "$LLM_PROVIDER" \
        --llm-api-key "$LLM_API_KEY" \
        --llm-bot-token "$LLM_BOT_TOKEN" \
        --gate-bot-token "$GATE_BOT_TOKEN" \
        $TELEGRAM_FLAG
fi

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}       Installation Complete!            ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo "Use 'sheriff-ctl chat' to start interacting immediately."
echo "Use '/status' inside chat for on-demand health checks."
echo "Restart your terminal to use the 'sheriff-ctl' command directly."