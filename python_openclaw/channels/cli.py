from __future__ import annotations

import getpass


class CLIChannel:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def send_stream(self, session_key: str, event: dict) -> None:
        self.events.append({"session_key": session_key, **event})
        if event["stream"] == "assistant.delta":
            print(event["payload"]["delta"], end="", flush=True)
        elif event["stream"] == "assistant.final":
            print("\n" + event["payload"]["content"])


def cli_identity() -> dict:
    return {"local_user": getpass.getuser()}
