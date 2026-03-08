from pathlib import Path


def test_installer_shebang_is_plain_bash():
    first_line = Path("sheriffclaw.sh").read_text(encoding="utf-8").splitlines()[0]
    assert first_line == "#!/bin/bash"


def test_installer_sets_up_macos_ai_worker_launcher():
    text = Path("sheriffclaw.sh").read_text(encoding="utf-8")
    assert "install_macos_ai_worker_launcher" in text
    assert "/usr/local/bin/sheriff-ai-worker-launch" in text
    assert 'sudoers_file="$sudoers_dir/sheriffclaw-ai-worker"' in text
    assert 'export PYTHONHOME="$runtime_root"' in text
    assert 'runtime_root="/Users/$worker_user/ai-runtime"' in text
    assert "repair_ai_worker_shared_paths" in text
    assert '"$INSTALL_DIR/llm"' in text
    assert '"$INSTALL_DIR/agents/codex"' in text
