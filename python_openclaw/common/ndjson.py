from __future__ import annotations

import json
from collections.abc import AsyncIterator, Iterator
from pathlib import Path


async def read_ndjson(reader) -> AsyncIterator[dict]:
    while True:
        line = await reader.readline()
        if not line:
            break
        yield json.loads(line.decode("utf-8"))


def encode_ndjson(message: dict) -> bytes:
    return (json.dumps(message, separators=(",", ":")) + "\n").encode("utf-8")


def append_jsonl(path: Path, event: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(event, ensure_ascii=False) + "\n")


def iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
