from __future__ import annotations

import asyncio

from services.telegram_listener.service import TelegramListenerService


def main() -> None:
    svc = TelegramListenerService()
    asyncio.run(svc.run_forever())


if __name__ == "__main__":
    main()
