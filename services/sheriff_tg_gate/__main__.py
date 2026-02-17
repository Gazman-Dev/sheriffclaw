from __future__ import annotations

import asyncio

from services.sheriff_tg_gate.service import SheriffTgGateService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


def main() -> None:
    svc = SheriffTgGateService()
    app = NDJSONService(name="gw.tg_gate", island="gw", kind="service", version=VERSION, ops=svc.ops())
    asyncio.run(app.run_stdio())


if __name__ == "__main__":
    main()
