from __future__ import annotations

import asyncio

from services.ai_tg_llm.runner import TelegramLLMRunner


def main() -> None:
    asyncio.run(TelegramLLMRunner().run_forever())


if __name__ == "__main__":
    main()
