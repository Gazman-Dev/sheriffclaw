from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from python_openclaw.common.models import Binding, Principal


@dataclass
class IdentityManager:
    principals: dict[str, Principal]
    bindings: dict[tuple[str, str], Binding]
    llm_allowed_telegram_user_ids: set[int]
    gate_bindings: dict[str, str]

    def __init__(self, on_change: Callable[[], None] | None = None) -> None:
        self.principals = {}
        self.bindings = {}
        self.llm_allowed_telegram_user_ids = set()
        self.gate_bindings = {}
        self._on_change = on_change

    def set_on_change(self, on_change: Callable[[], None] | None) -> None:
        self._on_change = on_change

    def add_principal(self, principal: Principal) -> None:
        self.principals[principal.principal_id] = principal

    def bind(self, binding: Binding) -> None:
        self.bindings[(binding.channel, binding.external_id)] = binding

    def principal_for(self, channel: str, external_id: str) -> Principal | None:
        b = self.bindings.get((channel, external_id))
        if not b:
            return None
        return self.principals.get(b.principal_id)

    def bind_gate_channel(self, principal_id: str, gate_session_key: str) -> None:
        self.gate_bindings[principal_id] = gate_session_key
        self._notify_change()

    def gate_for(self, principal_id: str, fallback_session_key: str | None = None) -> str | None:
        return self.gate_bindings.get(principal_id) or fallback_session_key

    def allow_llm_user(self, user_id: int) -> None:
        self.llm_allowed_telegram_user_ids.add(user_id)
        self._notify_change()

    def is_llm_user_allowed(self, user_id: int) -> bool:
        return user_id in self.llm_allowed_telegram_user_ids

    def load_from_dict(self, data: dict[str, Any]) -> None:
        self.llm_allowed_telegram_user_ids = {int(v) for v in data.get("llm_allowed_telegram_user_ids", [])}
        self.gate_bindings = {str(k): str(v) for k, v in dict(data.get("gate_bindings", {})).items()}

    def to_dict(self) -> dict[str, Any]:
        return {
            "llm_allowed_telegram_user_ids": sorted(self.llm_allowed_telegram_user_ids),
            "gate_bindings": dict(self.gate_bindings),
        }

    def _notify_change(self) -> None:
        if self._on_change:
            self._on_change()


def session_key(channel: str, context: dict[str, Any]) -> str:
    if channel == "telegram_dm":
        return f"tg:dm:{context['user_id']}"
    if channel == "telegram_group":
        return f"tg:group:{context['chat_id']}"
    if channel == "telegram_topic":
        return f"tg:group:{context['chat_id']}:{context['thread_id']}"
    if channel == "cli":
        return f"cli:{context['local_user']}"
    raise ValueError(f"unsupported channel: {channel}")
