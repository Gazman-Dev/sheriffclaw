from __future__ import annotations

import asyncio

from services.ai_tg_llm.service import AITgLlmService
from shared.protocol import VERSION
from shared.service_base import NDJSONService


def main() -> None:
    svc = AITgLlmService()
    app = NDJSONService(name="llm.tg_llm", island="llm", kind="service", version=VERSION, ops=svc.ops())
    asyncio.run(app.run_stdio())


if __name__ == "__main__":
    main()
