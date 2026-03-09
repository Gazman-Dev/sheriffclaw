from __future__ import annotations

import asyncio
import os

from services.sheriff_requests.service import SheriffRequestsService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


async def _run() -> None:
    svc = SheriffRequestsService()
    app = NDJSONService(name="gw.requests", island="gw", kind="service", version=VERSION, ops=svc.ops())
    await svc.boot_check({}, lambda _e, _p: asyncio.sleep(0), "boot")
    host = os.environ.get("SHERIFF_RPC_HOST", "").strip()
    port = os.environ.get("SHERIFF_RPC_PORT", "").strip()
    if host and port:
        await app.run_tcp(host, int(port))
    else:
        await app.run_stdio()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
