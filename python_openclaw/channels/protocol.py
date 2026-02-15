from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class ChannelContent:
    text: str | None = None
    image_url: str | None = None
    image_base64: str | None = None
    file_url: str | None = None


@dataclass
class InboundEvent:
    principal_external_id: str
    channel: str
    session_key: str
    text: str | None = None
    callback_data: dict | None = None
    raw_payload: dict | None = None


class ChannelAdapter(Protocol):
    async def send_message(self, session_key: str, content: ChannelContent) -> None: ...

    async def send_approval_request(self, approval_id: str, context: dict) -> None: ...

    def parse_inbound(self, raw_payload: dict) -> InboundEvent: ...
