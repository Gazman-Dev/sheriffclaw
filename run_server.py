from __future__ import annotations

import asyncio
from pathlib import Path

from python_openclaw.main import run_openclaw


if __name__ == "__main__":
    asyncio.run(run_openclaw(Path.cwd()))
