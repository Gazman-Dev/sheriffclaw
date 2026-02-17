import json

import pytest
from unittest.mock import AsyncMock

from services.sheriff_requests.service import SheriffRequestsService


class FakeSemanticEmbedding:
    def __call__(self, input):
        vectors = []
        for text in input:
            low = text.lower()
            githubish = 1.0 if any(token in low for token in ["github", "git", "gh", "repo", "repository"]) else 0.0
            tokenish = 1.0 if any(token in low for token in ["token", "credential", "secret", "auth"]) else 0.0
            domainish = 1.0 if any(token in low for token in ["domain", "host", "api."]) else 0.0
            toolish = 1.0 if any(token in low for token in ["tool", "cli", "command", "exec"]) else 0.0
            vectors.append([githubish, tokenish, domainish, toolish])
        return vectors

    def embed_documents(self, input):
        return self(input)

    def embed_query(self, input):
        return self(input)

    @staticmethod
    def name():
        return "default"

    @staticmethod
    def is_legacy():
        return False

    @staticmethod
    def default_space():
        return "l2"

    @staticmethod
    def supported_spaces():
        return ["l2"]

    @staticmethod
    def get_config():
        return {}


@pytest.fixture
def requests_svc(tmp_path, monkeypatch):
    monkeypatch.setattr("services.sheriff_requests.service.gw_root", lambda: tmp_path)
    monkeypatch.setattr("services.sheriff_requests.service.SheriffRequestsService._embedding_function", staticmethod(lambda: FakeSemanticEmbedding()))
    svc = SheriffRequestsService()
    svc.tg_gate = AsyncMock()
    svc.secrets = AsyncMock()
    svc.secrets.request.return_value = (None, {"result": {"unlocked": True}})
    svc.policy = AsyncMock()
    svc.gateway = AsyncMock()
    return svc


@pytest.mark.asyncio
async def test_fuzzy_semantic_search_uses_chroma(requests_svc):
    await requests_svc.create_or_update(
        {"type": "secret", "key": "gh_token", "one_liner": "Need GitHub credential for repo sync", "context": {"feature": "sync"}},
        None,
        "r1",
    )
    await requests_svc.create_or_update(
        {"type": "domain", "key": "api.example.com", "one_liner": "Allow example API host", "context": {}},
        None,
        "r2",
    )

    out = await requests_svc.search({"query": "git token for repository", "k": 3}, None, "r3")
    assert out["matches"]
    assert out["matches"][0]["type"] == "secret"
    assert out["matches"][0]["key"] == "gh_token"


@pytest.mark.asyncio
async def test_mutable_entry_update_refreshes_semantic_search(requests_svc):
    await requests_svc.create_or_update(
        {"type": "tool", "key": "git", "one_liner": "Need CLI execution", "context": {"phase": "initial"}}, None, "r1"
    )
    await requests_svc.resolve_tool({"key": "git", "action": "deny"}, None, "r2")

    before = await requests_svc.search({"query": "repository command", "types": ["tool"], "k": 5}, None, "r3")
    assert before["matches"]

    await requests_svc.create_or_update(
        {
            "type": "tool",
            "key": "git",
            "one_liner": "Need repository command execution for github",
            "context": {"phase": "updated"},
        },
        None,
        "r4",
    )

    after = await requests_svc.search({"query": "repository command", "types": ["tool"], "k": 5}, None, "r5")
    assert after["matches"]
    assert after["matches"][0]["key"] == "git"
    got = await requests_svc.get({"type": "tool", "key": "git"}, None, "r6")
    assert json.loads(got["context_json"]) == {"phase": "updated"}


@pytest.mark.asyncio
async def test_approved_entry_is_immutable_but_resilient(requests_svc):
    # 1. Create and approve
    await requests_svc.create_or_update(
        {"type": "secret", "key": "gh_token", "one_liner": "Need GitHub token"},
        None,
        "r1",
    )
    await requests_svc.resolve_secret({"key": "gh_token", "value": "top-secret"}, None, "r2")

    # 2. Simulate resilience: Ensure immutable entry doesn't error on update, content remains
    await requests_svc.create_or_update(
        {"type": "secret", "key": "gh_token", "one_liner": "Different text"},
        None,
        "r3",
    )

    got = await requests_svc.get({"type": "secret", "key": "gh_token"}, None, "r4")
    assert got["status"] == "approved"
    assert got["one_liner"] == "Need GitHub token" # Unchanged

    # 3. Verify spam reduction: tg_gate.request should have been called only once (for r1)
    # The subsequent call (r3) should not trigger a notification because it's immutable.
    notify_calls = [
        c for c in requests_svc.tg_gate.request.call_args_list
        if c[0][0] == "gate.notify_request"
    ]
    assert len(notify_calls) == 1

    # 4. Verify force_notify works
    await requests_svc.create_or_update(
        {"type": "secret", "key": "gh_token", "one_liner": "Ignored", "force_notify": True},
        None,
        "r5",
    )
    notify_calls_forced = [
        c for c in requests_svc.tg_gate.request.call_args_list
        if c[0][0] == "gate.notify_request"
    ]
    assert len(notify_calls_forced) == 2


@pytest.mark.asyncio
async def test_boot_check_uses_master_policy_file(requests_svc, tmp_path):
    requests_svc.secrets.request.return_value = (None, {"result": {"unlocked": False}})
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "master_policy.json").write_text(json.dumps({"allow_telegram_master_password": True}), encoding="utf-8")

    out = await requests_svc.boot_check({}, None, "r1")
    assert out["status"] == "master_password_required"