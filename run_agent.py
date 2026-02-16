from __future__ import annotations

import asyncio
from pathlib import Path

from python_openclaw.main import build_agent_runtime


async def _main() -> None:
    runner = build_agent_runtime(Path.cwd())
    await runner.run_polling()


if __name__ == "__main__":
    asyncio.run(_main())
