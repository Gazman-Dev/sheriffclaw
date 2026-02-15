from pathlib import Path

from python_openclaw.llm.providers import AnthropicProvider, OpenAIProvider, provider_from_ref
from python_openclaw.llm.registry import ModelResolver, OpenClawConfig


def test_provider_resolver_by_prefix():
    assert isinstance(provider_from_ref("openai/best", api_keys={"openai": "k"}), OpenAIProvider)
    assert isinstance(provider_from_ref("anthropic/claude-best", api_keys={"anthropic": "k"}), AnthropicProvider)


def test_model_config_loader_and_chain(tmp_path: Path):
    cfg_path = tmp_path / "openclaw.json"
    cfg_path.write_text(
        '{"agents":{"defaults":{"model":{"primary":"openai/best","fallbacks":["anthropic/flash"]}}}}',
        encoding="utf-8",
    )
    config = OpenClawConfig.load(cfg_path)
    resolver = ModelResolver(config, api_keys={"openai": "a", "anthropic": "b"})
    chain = resolver.resolve_chain()
    assert len(chain) == 2
