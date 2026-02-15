from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from python_openclaw.llm.providers import ModelProvider, provider_from_ref


@dataclass
class AgentModelDefaults:
    primary: str
    fallbacks: list[str]


@dataclass
class OpenClawConfig:
    agent_defaults: AgentModelDefaults

    @classmethod
    def load(cls, path: Path) -> "OpenClawConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        defaults = raw.get("agents", {}).get("defaults", {}).get("model", {})
        return cls(
            agent_defaults=AgentModelDefaults(
                primary=defaults.get("primary", "openai/best"),
                fallbacks=list(defaults.get("fallbacks", [])),
            )
        )


class ModelResolver:
    def __init__(self, config: OpenClawConfig, *, api_keys: dict[str, str] | None = None):
        self.config = config
        self.api_keys = api_keys or {}

    def resolve(self, model_ref: str | None = None) -> ModelProvider:
        chosen = model_ref or self.config.agent_defaults.primary
        return provider_from_ref(chosen, api_keys=self.api_keys)

    def resolve_chain(self, model_ref: str | None = None) -> list[ModelProvider]:
        primary_ref = model_ref or self.config.agent_defaults.primary
        refs = [primary_ref, *self.config.agent_defaults.fallbacks]
        return [provider_from_ref(ref, api_keys=self.api_keys) for ref in refs]
