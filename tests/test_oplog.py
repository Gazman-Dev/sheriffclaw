from __future__ import annotations

from shared.oplog import get_op_logger


def test_get_op_logger_uses_llm_island_when_requested(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    logger = get_op_logger("ai_worker_test", island="llm")

    assert logger.handlers
    assert (tmp_path / "llm" / "logs" / "ops" / "ai_worker_test.log").exists()


def test_get_op_logger_defaults_to_gateway_island(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))

    logger = get_op_logger("gateway_test")

    assert logger.handlers
    assert (tmp_path / "gw" / "logs" / "ops" / "gateway_test.log").exists()
