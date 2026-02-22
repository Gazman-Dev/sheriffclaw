from pathlib import Path

from services.sheriff_ctl import ctl


def test_service_command_ai_worker_sandbox_on_darwin(monkeypatch, tmp_path):
    monkeypatch.setattr("services.sheriff_ctl.ctl.platform.system", lambda: "Darwin")
    monkeypatch.setattr("services.sheriff_ctl.ctl.shutil.which", lambda x: "/usr/bin/sandbox-exec")
    monkeypatch.setattr("services.sheriff_ctl.ctl.gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr("services.sheriff_ctl.ctl.llm_root", lambda: tmp_path / "llm")

    cmd = ctl._service_command("ai-worker")
    assert cmd[0].endswith("sandbox-exec")
    assert cmd[1] == "-f"
    assert Path(cmd[2]).exists()


def test_service_command_linux_bwrap(monkeypatch, tmp_path):
    monkeypatch.setattr("services.sheriff_ctl.ctl.platform.system", lambda: "Linux")
    monkeypatch.setattr("services.sheriff_ctl.ctl.shutil.which", lambda x: "/usr/bin/bwrap" if x == "bwrap" else None)
    monkeypatch.setattr("services.sheriff_ctl.ctl.gw_root", lambda: tmp_path / "gw")
    monkeypatch.setattr("services.sheriff_ctl.ctl.llm_root", lambda: tmp_path / "llm")

    cmd = ctl._service_command("ai-worker")
    assert cmd[0].endswith("bwrap")


def test_service_command_non_ai_worker_plain(monkeypatch):
    monkeypatch.setattr("services.sheriff_ctl.ctl.platform.system", lambda: "Darwin")
    monkeypatch.setattr("services.sheriff_ctl.ctl.shutil.which", lambda x: "/usr/bin/sandbox-exec")
    cmd = ctl._service_command("sheriff-gateway")
    assert "sandbox-exec" not in cmd[0]
