import pytest
from shared.llm.providers import StubProvider, TestProvider
from shared.llm.registry import resolve_model

@pytest.mark.asyncio
async def test_stub_provider_echoes_input():
    provider = StubProvider()
    messages = [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi"},
        {"role": "user", "content": "test payload"}
    ]
    response = await provider.generate(messages)
    assert response == "Assistant: test payload"

@pytest.mark.asyncio
async def test_stub_provider_empty_history():
    provider = StubProvider()
    response = await provider.generate([])
    assert response == "Assistant: ready"

@pytest.mark.asyncio
async def test_test_provider_for_testing_channel():
    provider = TestProvider()
    response = await provider.generate([{"role": "user", "content": "ping"}], model="test/default")
    assert response == "TestBot[test/default]: ping"

def test_resolve_model_defaults():
    assert resolve_model(None) == "stub/default"
    assert resolve_model("gpt-4") == "gpt-4"