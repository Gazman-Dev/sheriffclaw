from __future__ import annotations

import json
from collections.abc import AsyncIterator


async def read_ndjson(reader) -> AsyncIterator[dict]:
    while True:
        line = await reader.readline()
        if not line:
            break
        yield json.loads(line.decode("utf-8"))


def encode_ndjson(message: dict) -> bytes:
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")
