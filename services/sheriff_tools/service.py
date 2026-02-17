from __future__ import annotations

import json
from pathlib import Path

from python_openclaw.gateway.secrets.store import SecretStore
from python_openclaw.gateway.services import ToolsService
from python_openclaw.security.permissions import PermissionStore
from shared.paths import gw_root


class SheriffToolsService:
    def __init__(self) -> None:
        root = gw_root()
        self.permissions = PermissionStore(root / "permissions.db")
        self.service = ToolsService(self.permissions, SecretStore(root / "secrets_service.enc"))
        self.audit_root = root / "audit"
        self.audit_root.mkdir(parents=True, exist_ok=True)
        self.outputs: dict[str, dict] = {}

    async def exec_tool(self, payload, emit_event, req_id):
        principal = payload.get("principal_id", "unknown")
        result = self.service.execute(payload, principal_id=principal)
        captured = result.pop("__captured_output", None)
        if captured:
            run_id = result["run_id"]
            self.outputs[run_id] = captured
            (self.audit_root / f"{run_id}.json").write_text(json.dumps(captured), encoding="utf-8")
        return result

    async def disclose_output(self, payload, emit_event, req_id):
        run_id = payload["run_id"]
        out = self.outputs.get(run_id)
        if not out:
            p = self.audit_root / f"{run_id}.json"
            if p.exists():
                out = json.loads(p.read_text(encoding="utf-8"))
        if not out:
            return {"status": "not_found"}
        return {"status": "disclosed", **out}

    async def get_output(self, payload, emit_event, req_id):
        return await self.disclose_output(payload, emit_event, req_id)

    def ops(self):
        return {"tools.exec": self.exec_tool, "tools.disclose_output": self.disclose_output, "tools.get_output": self.get_output}
