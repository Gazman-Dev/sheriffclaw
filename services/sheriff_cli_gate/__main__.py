from __future__ import annotations

import asyncio

from services.sheriff_cli_gate.service import SheriffCliGateService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


def main() -> None:
    svc = SheriffCliGateService()
    app = NDJSONService(name="gw.cli_gate", island="gw", kind="service", version=VERSION, ops=svc.ops())
    asyncio.run(app.run_stdio())


if __name__ == "__main__":
    main()
