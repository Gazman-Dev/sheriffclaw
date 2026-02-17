from __future__ import annotations

import asyncio

from services.sheriff_tg_gate.runner import TelegramGateRunner


def main() -> None:
    asyncio.run(TelegramGateRunner().run_forever())


if __name__ == "__main__":
    main()
