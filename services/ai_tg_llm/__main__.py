from __future__ import annotations

from services.ai_tg_llm.service import AITgLlmService
from shared.protocol import VERSION
from shared.service_base import NDJSONService
from shared.service_boot import run_service


def main() -> None:
    svc = AITgLlmService()
    app = NDJSONService(name="llm.tg_llm", island="llm", kind="service", version=VERSION, ops=svc.ops())
    run_service(app)


if __name__ == "__main__":
    main()
