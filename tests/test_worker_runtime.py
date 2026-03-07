import asyncio

import pytest

from shared.worker.worker_runtime import WorkerRuntime


@pytest.mark.asyncio
async def test_worker_writes_inbox_file_and_receives_file_protocol_reply(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    fake_proc = _FakeProc()

    async def fake_ensure():
        rt.codex_proc = fake_proc
        rt.codex_start_error = ""

    async def fake_send(text, session_handle):
        await _write_pending_after_delay(rt, session_handle, f"Debug Codex Response to: {text}", 0.01)

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)
    monkeypatch.setattr(rt, "_send_codex_stdin", fake_send)

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    h = await rt.session_open("s1")
    await rt.user_message(h, "hello from test", None, emit, channel="telegram", principal_external_id="u1")

    session_dir = rt.conversations_dir / h
    user_files = list(session_dir.glob("*_user_agent.tmd"))
    assert user_files, "expected a user turn file"
    body = user_files[0].read_text(encoding="utf-8")
    assert "hello from test" in body

    agent_files = list(session_dir.glob("*_agent_user.tmd"))
    assert agent_files, "expected an agent reply file"
    agent_body = agent_files[0].read_text(encoding="utf-8")
    assert "Debug Codex Response to: hello from test" in agent_body

    finals = [p for e, p in events if e == "assistant.final"]
    assert finals
    assert finals[0]["text"] == "Debug Codex Response to: hello from test"


@pytest.mark.asyncio
async def test_worker_timeout_is_reproducible_via_codex_debug(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    monkeypatch.setenv("SHERIFF_DEBUG_TIMEOUT_SEC", "0.4")
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    fake_proc = _FakeProc()

    async def fake_ensure():
        rt.codex_proc = fake_proc
        rt.codex_start_error = ""

    async def fake_send(text, session_handle):
        return None

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)
    monkeypatch.setattr(rt, "_send_codex_stdin", fake_send)

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    h = await rt.session_open("s2")
    await rt.user_message(h, "trigger timeout", None, emit, channel="telegram", principal_external_id="u1")

    finals = [p for e, p in events if e == "assistant.final"]
    assert finals[-1]["text"] == "Agent background process response timed out."


@pytest.mark.asyncio
async def test_worker_typing_timeout_emits_delta_before_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    monkeypatch.setenv("SHERIFF_DEBUG_TIMEOUT_SEC", "0.5")
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    fake_proc = _FakeProc()

    async def fake_ensure():
        rt.codex_proc = fake_proc
        rt.codex_start_error = ""

    async def fake_send(text, session_handle):
        session_dir = rt.conversations_dir / session_handle
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "agent_user_typing.tmd").touch()

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)
    monkeypatch.setattr(rt, "_send_codex_stdin", fake_send)

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    h = await rt.session_open("s3")
    await rt.user_message(h, "trigger typing timeout", None, emit, channel="telegram", principal_external_id="u1")

    assert ("assistant.delta", {"text": "typing..."}) in events
    finals = [p for e, p in events if e == "assistant.final"]
    assert finals[-1]["text"] == "Agent background process response timed out."
    await rt.session_close(h)


class _FakeWriter:
    def __init__(self):
        self.writes = []
        self.drains = 0

    def write(self, payload):
        self.writes.append(payload)

    async def drain(self):
        self.drains += 1


class _FakeProc:
    def __init__(self):
        self.stdin = _FakeWriter()
        self.returncode = None

    def terminate(self):
        self.returncode = 0

    def kill(self):
        self.returncode = -9

    async def wait(self):
        return self.returncode


async def _write_pending_after_delay(rt: WorkerRuntime, session_handle: str, text: str, delay_sec: float) -> None:
    await asyncio.sleep(delay_sec)
    session_dir = rt.conversations_dir / session_handle
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "agent_user_pending.tmd").write_text(text, encoding="utf-8")


@pytest.mark.asyncio
async def test_worker_writes_message_file_and_forwards_turn_to_codex_stdin(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    monkeypatch.setenv("SHERIFF_DEBUG_TIMEOUT_SEC", "0.1")
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    fake_proc = _FakeProc()

    async def fake_ensure():
        rt.codex_proc = fake_proc
        rt.codex_start_error = ""

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    h = await rt.session_open("s4")
    await rt.user_message(h, "hello stdin path", None, emit, channel="telegram", principal_external_id="u1")

    session_dir = rt.conversations_dir / h
    user_files = list(session_dir.glob("*_user_agent.tmd"))
    assert user_files
    assert user_files[0].read_text(encoding="utf-8") == "hello stdin path"
    assert fake_proc.stdin.writes == [b"hello stdin path\n"]
    assert fake_proc.stdin.drains == 1
    finals = [p for e, p in events if e == "assistant.final"]
    assert finals[-1]["text"] == "Agent background process response timed out."


def test_extract_menu_options_builds_option_payloads(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    options = rt._extract_menu_options(
        [
            "choose how you'd like codex to proceed.",
            "1. try new model",
            "2. use existing model",
        ]
    )
    assert options == [
        {"label": "try new model", "payload": b"\r"},
        {"label": "use existing model", "payload": b"\x1b[B\r"},
    ]


def test_extract_interactive_menu_prefers_choice_block_over_warning_list(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    lines = [
        "warning text",
        "1. /users/ilyagazman/.sheriffclaw/agents/codex/.codex",
        "to load config.toml, add trusted project",
        "choose how you'd like codex to proceed.",
        "1. try new model",
        "2. use existing model",
        "use ↑/↓ to move, press enter to confirm",
    ]
    context, options = rt._extract_interactive_menu(lines)
    assert "choose how you'd like codex to proceed." in context
    assert options == [
        {"label": "try new model", "payload": b"\r"},
        {"label": "use existing model", "payload": b"\x1b[B\r"},
    ]


def test_normalized_codex_text_strips_ansi(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    raw = "\x1b[31mTrust the current folder?\x1b[0m\r\n"
    assert rt._normalized_codex_text(raw) == "trust the current folder?\n\n"


@pytest.mark.asyncio
async def test_unknown_prompt_publishes_manual_selection_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    rt.active_session_handle = "s5"
    await rt._handle_codex_stdout("Choose how you'd like Codex to proceed.\n1. Try new model\n2. Use existing model\n")
    pending = (rt.conversations_dir / "s5" / "agent_user_pending.tmd").read_text(encoding="utf-8")
    assert "/option1 - try new model" in pending
    assert "/option2 - use existing model" in pending


@pytest.mark.asyncio
async def test_option_reply_sends_selected_control(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    rt.codex_prompt_state["s6"] = {
        "key": "generic_menu:try new model|use existing model",
        "message": "Codex is waiting on an interactive selection.",
        "details": "1. try new model\n2. use existing model",
        "options": [
            {"label": "try new model", "payload": b"\r"},
            {"label": "use existing model", "payload": b"\x1b[B\r"},
        ],
    }
    calls = []

    async def fake_write(payload, *, reason, session=None):
        calls.append((payload, reason, session))

    monkeypatch.setattr(rt, "_write_codex_control", fake_write)
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    handled = await rt._handle_prompt_selection("s6", "/option2", emit)
    assert handled is True
    assert calls == [(b"\x1b[B\r", "user_/option2", "s6")]
    assert ("assistant.final", {"text": "Sent /option2 to Codex."}) in events


@pytest.mark.asyncio
async def test_normal_message_is_blocked_while_prompt_is_pending(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    rt.codex_prompt_state["s7"] = {
        "key": "generic_menu:one|two",
        "message": "Codex is waiting on an interactive selection.",
        "details": "1. one\n2. two",
        "options": [
            {"label": "one", "payload": b"\r"},
            {"label": "two", "payload": b"\x1b[B\r"},
        ],
    }
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await rt.user_message("s7", "hello", None, emit)
    assert events == [
        (
            "assistant.final",
            {"text": "Codex is waiting on an interactive selection.\n\n1. one\n2. two\n\nChoose one:\n/option1 - one\n/option2 - two"},
        )
    ]


@pytest.mark.asyncio
async def test_prompt_pending_returns_prompt_without_timeout(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    monkeypatch.setenv("SHERIFF_DEBUG_TIMEOUT_SEC", "0.2")
    rt = WorkerRuntime()
    fake_proc = _FakeProc()

    async def fake_ensure():
        rt.codex_proc = fake_proc
        rt.codex_start_error = ""
        rt.codex_prompt_state["s8"] = {
            "key": "generic_menu:try new model|use existing model",
            "message": "Codex is waiting on an interactive selection.",
            "details": "choose how you'd like codex to proceed.\n1. try new model\n2. use existing model",
            "options": [
                {"label": "try new model", "payload": b"\r"},
                {"label": "use existing model", "payload": b"\x1b[B\r"},
            ],
        }
        session_dir = rt.conversations_dir / "s8"
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "agent_user_pending.tmd").write_text(
            "Codex is waiting on an interactive selection.\n\nChoose one:\n/option1 - try new model\n/option2 - use existing model",
            encoding="utf-8",
        )

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)
    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await rt.user_message("s8", "hi", None, emit)
    assert events == [
        (
            "assistant.final",
            {
                "text": "Codex is waiting on an interactive selection.\n\nChoose one:\n/option1 - try new model\n/option2 - use existing model"
            },
        )
    ]
