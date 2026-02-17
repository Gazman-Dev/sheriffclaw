from __future__ import annotations

import asyncio

from services.ai_worker.service import AIWorkerService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


def main() -> None:
    svc = AIWorkerService()
    app = NDJSONService(name="llm.ai_worker", island="llm", kind="service", version=VERSION, ops=svc.ops())
    asyncio.run(app.run_stdio())


if __name__ == "__main__":
    main()
