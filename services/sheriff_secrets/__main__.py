from __future__ import annotations

import asyncio

from services.sheriff_secrets.service import SheriffSecretsService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


def main() -> None:
    svc = SheriffSecretsService()
    app = NDJSONService(name="gw.secrets", island="gw", kind="service", version=VERSION, ops=svc.ops())
    asyncio.run(app.run_stdio())


if __name__ == "__main__":
    main()
