from __future__ import annotations

import asyncio

from services.sheriff_gateway.service import SheriffGatewayService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


def main() -> None:
    svc = SheriffGatewayService()
    app = NDJSONService(name="gw.gateway", island="gw", kind="service", version=VERSION, ops=svc.ops())
    asyncio.run(app.run_stdio())


if __name__ == "__main__":
    main()
