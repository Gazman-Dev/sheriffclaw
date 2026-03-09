from __future__ import annotations


def principal_id_for_channel(channel: str, external_id: str) -> str:
    return f"{channel}:{external_id}"
