from pathlib import Path


def test_installer_shebang_is_plain_bash():
    first_line = Path("sheriffclaw.sh").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/bin/bash"


def test_installer_sets_up_macos_codex_mcp_host_launcher():
    text = Path("sheriffclaw.sh").read_text(encoding="utf-8")
    assert "require_root()" in text
    assert 'Example: curl -fsSL <installer-url> | sudo bash' in text
    assert 'INSTALL_DIR="${SHERIFF_INSTALL_DIR:-$INVOKING_HOME/.sheriffclaw}"' in text
    assert 'export HOME="$INVOKING_HOME"' in text
    assert "trap 'reset_terminal_state' EXIT" in text
    assert 'stty sane < /dev/tty 2>/dev/null || true' in text
    assert "printf '\\033[0m' > /dev/tty 2>/dev/null || true" in text
    assert 'log "Starting services..."' in text
    assert '"$VENV_DIR/bin/sheriff" start' in text
    assert 'export PIP_CACHE_DIR="$INSTALL_DIR/.cache/pip"' in text
    assert "print_install_version()" in text
    assert 'installer version: sheriff=${sheriff_version} commit=${source_commit}' in text
    assert "install_macos_ai_worker_launcher" in text
    assert "/usr/local/bin/sheriff-codex-mcp-host-launch" in text
    assert 'sudoers_file="$sudoers_dir/sheriffclaw-codex-mcp-host"' in text
    assert 'export PYTHONHOME="$runtime_root"' in text
    assert 'runtime_root="/Users/$worker_user/ai-runtime"' in text
    assert 'pidfile="/private/tmp/sheriffclaw/ai_worker.pid"' in text
    assert '"/private/tmp/sheriffclaw/ai_worker.sb" "$runtime_root/bin/python$py_ver" -m services.ai_worker.__main__ </dev/null &' in text
    assert 'case "\\${1:-run}" in' in text
    assert 'stop_worker' in text
    assert "repair_ai_worker_shared_paths" in text
    assert '"$INSTALL_DIR/llm"' in text
    assert '"$INSTALL_DIR/agents/codex"' in text
    assert '"$INSTALL_DIR/agent_repo"' in text
    assert 'chown -R "$owner_user":"$worker_group" "$p"' in text
    assert 'mkdir -p "/private/tmp/sheriffclaw"' in text
    assert 'chgrp "$worker_group" "/private/tmp/sheriffclaw"' in text
    assert 'chmod 2775 "/private/tmp/sheriffclaw"' in text
    assert 'for p in "/private/tmp/sheriffclaw/ai_worker.sb" "/private/tmp/sheriffclaw/ai_worker.pid"; do' in text
    assert 'printf \'%s\\n\' "$$" > "$LOCK_DIR/pid"' in text
    assert 'Kill the other installation and start fresh? [y/N]:' in text
    assert 'Remove the stale lock and continue? [y/N]:' in text
    assert "reset_terminal_state" in text
