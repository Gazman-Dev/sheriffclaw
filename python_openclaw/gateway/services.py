from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass

from python_openclaw.gateway.secrets.store import SecretNotFoundError, SecretStore
from python_openclaw.security.permissions import PermissionDeniedException, PermissionStore


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

        binary = parts[0]
        self._ensure_tool_allowed(principal_id, binary)

        try:
            resolved_parts = [self.secrets.inject_references(str(part)) for part in parts]
            resolved_stdin = self.secrets.inject_references(stdin) if isinstance(stdin, str) else stdin
        except SecretNotFoundError:
            raise

        proc = subprocess.run(
            resolved_parts,
            input=resolved_stdin,
            capture_output=True,
            text=True,
            check=False,
        )
        return {
            "status": "executed",
            "code": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
            "tool": binary,
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
