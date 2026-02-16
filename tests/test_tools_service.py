from pathlib import Path

import pytest

from python_openclaw.gateway.secrets.store import SecretNotFoundError, SecretStore
from python_openclaw.gateway.services import ToolsService
from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore


def test_tools_service_requires_tool_permission(tmp_path: Path):
    store = PermissionStore(tmp_path / "permissions.db")
    secrets = SecretStore(tmp_path / "secrets.enc")
    secrets.unlock("pw")
    tools = ToolsService(store, secrets)

    with pytest.raises(PermissionDeniedException):
        tools.execute({"command": "echo hello"}, principal_id="u1")


def test_tools_service_injects_secret_tokens(tmp_path: Path):
    store = PermissionStore(tmp_path / "permissions.db")
    store.set_decision("u1", "tool", "python3", "ALLOW")
    secrets = SecretStore(tmp_path / "secrets.enc")
    secrets.unlock("pw")
    secrets.set_secret("api_token", "abc123")
    tools = ToolsService(store, secrets)

    result = tools.execute(
        {
            "argv": ["python3", "-c", "import sys; print(sys.stdin.read())"],
            "stdin": "{api_token}",
        },
        principal_id="u1",
    )
    assert result["code"] == 0
    assert result["stdout"].strip() == "abc123"


def test_tools_service_returns_missing_secret_error(tmp_path: Path):
    store = PermissionStore(tmp_path / "permissions.db")
    store.set_decision("u1", "tool", "python3", "ALLOW")
    secrets = SecretStore(tmp_path / "secrets.enc")
    secrets.unlock("pw")
    tools = ToolsService(store, secrets)

    with pytest.raises(SecretNotFoundError):
        tools.execute({"command": "python3 -c 'print(1)' {missing}"}, principal_id="u1")
