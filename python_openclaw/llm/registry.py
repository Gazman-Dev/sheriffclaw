from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from python_openclaw.llm.providers import ModelProvider, provider_from_ref


@dataclass
class AgentModelDefaults:
    primary: str
    fallbacks: list[str]
    aliases: dict[str, str] = field(default_factory=dict)


@dataclass
class OpenClawConfig:
    agent_defaults: AgentModelDefaults

    @classmethod
    def load(cls, path: Path) -> "OpenClawConfig":
        raw = json.loads(path.read_text(encoding="utf-8"))
        defaults = raw.get("agents", {}).get("defaults", {}).get("model", {})
        aliases = defaults.get("aliases", {})
        if "best" not in aliases:
            aliases["best"] = defaults.get("primary", "openai/best")
        if "flash" not in aliases:
            aliases["flash"] = "openai/flash"
        return cls(
            agent_defaults=AgentModelDefaults(
                primary=defaults.get("primary", "openai/best"),
                fallbacks=list(defaults.get("fallbacks", [])),
                aliases={str(k).lower(): str(v) for k, v in aliases.items()},
            )
        )


class ModelResolver:
    def __init__(self, config: OpenClawConfig, *, api_keys: dict[str, str] | None = None):
        self.config = config
        self.api_keys = api_keys or {}

    def _expand_alias(self, model_ref: str | None) -> str:
        if not model_ref:
            return self.config.agent_defaults.primary
        key = model_ref.lower()
        return self.config.agent_defaults.aliases.get(key, model_ref)

    def resolve(self, model_ref: str | None = None) -> ModelProvider:
        chosen = self._expand_alias(model_ref)
        return provider_from_ref(chosen, api_keys=self.api_keys)

    def resolve_chain(self, model_ref: str | None = None) -> list[ModelProvider]:
        primary_ref = self._expand_alias(model_ref)
        refs = [primary_ref, *self.config.agent_defaults.fallbacks]
        return [provider_from_ref(self._expand_alias(ref), api_keys=self.api_keys) for ref in refs]
