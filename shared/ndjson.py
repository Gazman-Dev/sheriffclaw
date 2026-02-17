from __future__ import annotations

import json
from collections.abc import AsyncIterator


async def read_frames(reader) -> AsyncIterator[dict]:
    while True:
        line = await reader.readline()
        if not line:
            break
        if not line.strip():
            continue
        yield json.loads(line)


def encode_frame(frame: dict) -> bytes:
    return (json.dumps(frame, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
