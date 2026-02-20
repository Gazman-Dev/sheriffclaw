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

echo -e "${GREEN}[+] Starting Services...${NC}"
"$VENV_DIR/bin/sheriff-ctl" start

# Wait briefly for services to initialize
sleep 2

echo -e "${BLUE}=========================================${NC}"
echo -e "${BLUE}           Interactive Setup             ${NC}"
echo -e "${BLUE}=========================================${NC}"
echo ""

# Run interactive onboarding
"$VENV_DIR/bin/sheriff-ctl" onboard

echo ""
echo -e "${GREEN}=========================================${NC}"
echo -e "${GREEN}       Installation Complete!            ${NC}"
echo -e "${GREEN}=========================================${NC}"
echo "Use 'sheriff-ctl status' to check service health."
echo "Restart your terminal to use the 'sheriff-ctl' command directly."