from __future__ import annotations

from pathlib import Path

from shared.worker import codex_cli


def test_resolve_codex_binary_prefers_env(monkeypatch):
    monkeypatch.setenv("CODEX_BIN", "/tmp/custom-codex")
    assert codex_cli.resolve_codex_binary() == "/tmp/custom-codex"


def test_resolve_codex_binary_uses_which(monkeypatch):
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.setattr(codex_cli.shutil, "which", lambda name: "/usr/bin/codex")
    assert codex_cli.resolve_codex_binary() == "/usr/bin/codex"


def test_resolve_codex_binary_falls_back_to_common_locations(monkeypatch, tmp_path):
    monkeypatch.delenv("CODEX_BIN", raising=False)
    monkeypatch.setattr(codex_cli.shutil, "which", lambda name: None)
    monkeypatch.setattr(codex_cli.Path, "home", lambda: tmp_path)

    target = tmp_path / ".npm" / "bin" / "codex"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("", encoding="utf-8")

    assert codex_cli.resolve_codex_binary() == str(target)


def test_augment_path_adds_common_locations(monkeypatch, tmp_path):
    monkeypatch.setattr(codex_cli.Path, "home", lambda: tmp_path)
    out = codex_cli.augment_path("/usr/bin:/bin")
    assert "/opt/homebrew/bin" in out
    assert str(tmp_path / ".npm" / "bin") in out
