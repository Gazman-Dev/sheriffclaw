from __future__ import annotations

import argparse

from services.sheriff_ctl import doctor
from services.sheriff_ctl.ctl import build_parser


def test_doctor_parses():
    parser = build_parser()
    args = parser.parse_args(["doctor", "--clipboard", "--tail", "12"])
    assert args.clipboard is True
    assert args.tail == 12


def test_copy_to_clipboard_uses_platform_tool(monkeypatch):
    calls = []

    def fake_run(cmd, input=None, text=None, capture_output=None, check=None):
        calls.append((cmd, input))

        class P:
            returncode = 0

        return P()

    monkeypatch.setattr(doctor.subprocess, "run", fake_run)
    monkeypatch.setattr(doctor.sys, "platform", "darwin")
    ok, method = doctor._copy_to_clipboard("hello")
    assert ok is True
    assert method == "pbcopy"
    assert calls[0][0] == ["pbcopy"]
    assert calls[0][1] == "hello"


def test_cmd_doctor_prints_and_copies(monkeypatch, capsys):
    async def fake_report(_tail):
        return "Doctor body\n"

    monkeypatch.setattr(doctor, "_report_async", fake_report)
    monkeypatch.setattr(doctor, "_copy_to_clipboard", lambda text: (True, "pbcopy"))
    doctor.cmd_doctor(argparse.Namespace(clipboard=True, tail=5))
    out = capsys.readouterr().out
    assert "Doctor body" in out
    assert "copied report to clipboard via pbcopy" in out


def test_redact_masks_common_secret_patterns():
    text = "api_key=sk-abc123 token: 123456789:ABCDEFGHIJKLMNOPQRSTUV master_password=secret"
    redacted = doctor._redact(text)
    assert "sk-abc123" not in redacted
    assert "123456789:ABCDEFGHIJKLMNOPQRSTUV" not in redacted
    assert "master_password=secret" not in redacted


def test_health_summary_uses_short_timeout(monkeypatch):
    seen = {}

    class FakeClient:
        def __init__(self, service):
            self.service = service
            self.request_timeout_sec = None

        async def request(self, op, payload, stream_events=False):
            seen["timeout"] = self.request_timeout_sec
            return [], {"result": {"status": "ok"}}

        async def close(self):
            seen["closed"] = True

    monkeypatch.setattr(doctor, "ProcClient", FakeClient)
    result = doctor.asyncio.run(doctor._health_summary("sheriff-gateway"))
    assert result == "ok"
    assert seen["timeout"] == doctor.DOCTOR_RPC_TIMEOUT_SEC
    assert seen["closed"] is True
