from pathlib import Path

import pytest

from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.services import ToolsService
from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore


def _tools(tmp_path: Path) -> ToolsService:
    store = PermissionStore(tmp_path / "permissions.db")
    store.set_decision("u1", "tool", "python3", "ALLOW")
    secrets = SecretStore(tmp_path / "secrets.enc")
    secrets.unlock("pw")
    secrets.set_secret("api_token", "abc123")
    return ToolsService(store, secrets)


def test_tools_service_requires_tool_permission(tmp_path: Path):
    store = PermissionStore(tmp_path / "permissions.db")
    secrets = SecretStore(tmp_path / "secrets.enc")
    secrets.unlock("pw")
    tools = ToolsService(store, secrets)

    with pytest.raises(PermissionDeniedException):
        tools.execute({"command": "echo hello"}, principal_id="u1")


def test_tools_service_no_secret_substitution(tmp_path: Path):
    tools = _tools(tmp_path)
    result = tools.execute(
        {
            "argv": ["python3", "-c", "import sys; print(sys.stdin.read())"],
            "stdin": "{api_token}",
        },
        principal_id="u1",
    )
    assert result["status"] == "error"
    assert "placeholders" in result["error"]


def test_tools_service_rejects_placeholder_in_command(tmp_path: Path):
    tools = _tools(tmp_path)
    result = tools.execute({"command": "python3 -c 'print(1)' {missing}"}, principal_id="u1")
    assert result["status"] == "error"


def test_tainted_tool_output_is_suppressed(tmp_path: Path):
    tools = _tools(tmp_path)
    result = tools.execute({"argv": ["python3", "-c", "print(42)"], "taint": True}, principal_id="u1")
    assert result["status"] == "executed"
    assert result["tainted"] is True
    assert "stdout" not in result and "stderr" not in result
    assert result["disclosure_available"] is True
    assert "run_id" in result
