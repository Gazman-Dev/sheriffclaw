from __future__ import annotations

import asyncio

from services.telegram_webhook.service import TelegramWebhookService


def main() -> None:
    svc = TelegramWebhookService()
    asyncio.run(svc.run_forever())


if __name__ == "__main__":
    main()
