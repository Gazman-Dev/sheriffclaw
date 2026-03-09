from __future__ import annotations

import asyncio
import os

from services.sheriff_scheduler.service import SheriffSchedulerService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


async def _run() -> None:
    svc = SheriffSchedulerService()
    app = NDJSONService(name="gw.sheriff_scheduler", island="gw", kind="service", version=VERSION, ops=svc.ops())
    host = os.environ.get("SHERIFF_RPC_HOST", "").strip()
    port = os.environ.get("SHERIFF_RPC_PORT", "").strip()
    scheduler_task = asyncio.create_task(svc.run_forever())
    try:
        if host and port:
            await app.run_tcp(host, int(port))
        else:
            await app.run_stdio()
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
