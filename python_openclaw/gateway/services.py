from __future__ import annotations

import shlex
import subprocess
import uuid
from dataclasses import dataclass

from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore

TAINTED_TOOLS = {"gh"}


@dataclass
class ToolsResult:
    status: str
    code: int
    stdout: str
    stderr: str


class ToolsService:
    def __init__(self, permissions: PermissionStore, secrets: SecretStore):
        self.permissions = permissions
        self.secrets = secrets

    def execute(self, payload: dict, *, principal_id: str) -> dict:
        command = payload.get("command")
        argv = payload.get("argv")
        stdin = payload.get("stdin")

        if not command and not argv:
            return {"status": "error", "error": "command or argv is required"}

        parts = shlex.split(command) if command else [str(p) for p in argv]
        if not parts:
            return {"status": "error", "error": "empty command"}

        if any(_contains_secret_placeholder(part) for part in parts):
            return {"status": "error", "error": "secret placeholders are not supported in tool calls"}
        if isinstance(stdin, str) and _contains_secret_placeholder(stdin):
            return {"status": "error", "error": "secret placeholders are not supported in tool stdin"}

        binary = parts[0]
        self._ensure_tool_allowed(principal_id, binary)

        proc = subprocess.run(
            parts,
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )
        tainted = bool(payload.get("taint")) or binary in TAINTED_TOOLS
        run_id = payload.get("run_id") or uuid.uuid4().hex
        if tainted:
            return {
                "status": "executed",
                "code": proc.returncode,
                "tool": binary,
                "tainted": True,
                "run_id": run_id,
                "bytes_stdout": len(proc.stdout.encode("utf-8")),
                "bytes_stderr": len(proc.stderr.encode("utf-8")),
                "disclosure_available": True,
                "__captured_output": {"stdout": proc.stdout, "stderr": proc.stderr},
            }

        return {
            "status": "executed",
            "code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "tool": binary,
            "tainted": False,
            "run_id": run_id,
            "bytes_stdout": len(proc.stdout.encode("utf-8")),
            "bytes_stderr": len(proc.stderr.encode("utf-8")),
            "disclosure_available": False,
        }

    def _ensure_tool_allowed(self, principal_id: str, binary: str) -> None:
        decision = self.permissions.get_decision(principal_id, "tool", binary)
        if decision and decision.decision == "ALLOW":
            return
        raise PermissionDeniedException(principal_id, "tool", binary)


class RequestService:
    def __init__(self, permissions: PermissionStore, secrets: SecretStore):
        self.permissions = permissions
        self.secrets = secrets

    def resolve_permission(self, principal_id: str, target_type: str, target_value: str, approved: bool) -> None:
        self.permissions.set_decision(principal_id, target_type, target_value, "ALLOW" if approved else "DENY")

    def store_secret(self, key: str, value: str) -> None:
        self.secrets.set_secret(key, value)


def _contains_secret_placeholder(value: str) -> bool:
    return "{" in value and "}" in value
