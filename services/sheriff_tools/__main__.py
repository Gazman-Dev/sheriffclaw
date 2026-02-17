from __future__ import annotations

import asyncio

from services.sheriff_tools.service import SheriffToolsService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


def main() -> None:
    svc = SheriffToolsService()
    app = NDJSONService(name="gw.tools", island="gw", kind="service", version=VERSION, ops=svc.ops())
    asyncio.run(app.run_stdio())


if __name__ == "__main__":
    main()
