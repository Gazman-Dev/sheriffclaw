from __future__ import annotations

import asyncio
import os

from shared.service_base import NDJSONService


def run_service(app: NDJSONService) -> None:
    host = os.environ.get("SHERIFF_RPC_HOST", "").strip()
    port = os.environ.get("SHERIFF_RPC_PORT", "").strip()
    if host and port:
        asyncio.run(app.run_tcp(host, int(port)))
        return
    asyncio.run(app.run_stdio())
