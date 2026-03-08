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

    async def fake_send(text, session_handle, *, first_message):
        await _write_pending_after_delay(rt, session_handle, f"Debug Codex Response to: {text}", 0.01)

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)
    monkeypatch.setattr(rt, "_send_codex_stdin", fake_send)

    events =[]

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

    finals =[p for e, p in events if e == "assistant.final"]
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

    async def fake_send(text, session_handle, *, first_message):
        return None

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)
    monkeypatch.setattr(rt, "_send_codex_stdin", fake_send)

    events =[]

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

    async def fake_send(text, session_handle, *, first_message):
        session_dir = rt.conversations_dir / session_handle
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "agent_user_typing.tmd").touch()

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)
    monkeypatch.setattr(rt, "_send_codex_stdin", fake_send)

    events =[]

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
        self.writes =[]
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

    events =[]

    async def emit(event, payload):
        events.append((event, payload))

    h = await rt.session_open("s4")
    await rt.user_message(h, "hello stdin path", None, emit, channel="telegram", principal_external_id="u1")

    session_dir = rt.conversations_dir / h
    user_files = list(session_dir.glob("*_user_agent.tmd"))
    assert user_files
    assert user_files[0].read_text(encoding="utf-8") == "hello stdin path"
    assert len(fake_proc.stdin.writes) >= 1
    stdin_payload = b"".join(fake_proc.stdin.writes).decode("utf-8")
    assert "read agents.md." in stdin_payload.lower()
    assert "use only session files for replies. session: s4." in stdin_payload.lower()
    assert 'user json: "hello stdin path"' in stdin_payload.lower()
    assert stdin_payload.startswith("\x1b[200~")
    assert "\x1b[201~\r" in stdin_payload
    assert stdin_payload.endswith("\r")
    assert fake_proc.stdin.drains >= 1
    finals =[p for e, p in events if e == "assistant.final"]
    assert finals[-1]["text"] == "Agent background process response timed out."


@pytest.mark.asyncio
async def test_worker_followup_turn_uses_followup_stdin_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFF_DEBUG", "1")
    monkeypatch.setenv("SHERIFF_DEBUG_TIMEOUT_SEC", "0.1")
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    fake_proc = _FakeProc()

    async def fake_ensure():
        rt.codex_proc = fake_proc
        rt.codex_start_error = ""

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)

    async def emit(event, payload):
        return None

    session_dir = rt.conversations_dir / "s4b"
    session_dir.mkdir(parents=True, exist_ok=True)
    (session_dir / "111_user_agent.tmd").write_text("first", encoding="utf-8")

    await rt.user_message("s4b", "second", None, emit, channel="telegram", principal_external_id="u1")

    assert len(fake_proc.stdin.writes) >= 1
    stdin_payload = b"".join(fake_proc.stdin.writes).decode("utf-8")
    assert "same rules. reply only via session files. session: s4b." in stdin_payload.lower()
    assert 'user json: "second"' in stdin_payload.lower()
    assert stdin_payload.startswith("\x1b[200~")
    assert "\x1b[201~\r" in stdin_payload
    assert stdin_payload.endswith("\r")


def test_extract_menu_options_builds_option_payloads(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    options = rt._extract_menu_options([
        "choose how you'd like codex to proceed.",
        "1. try new model",
        "2. use existing model",
    ]
    )
    assert options ==[
        {"label": "try new model", "payload": b"\r"},
        {"label": "use existing model", "payload": b"\x1b[B\r"},
    ]


def test_extract_interactive_menu_prefers_choice_block_over_warning_list(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    lines =[
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
    assert options ==[
        {"label": "try new model", "payload": b"\r"},
        {"label": "use existing model", "payload": b"\x1b[B\r"},
    ]


def test_extract_interactive_menu_rejects_single_warning_path_option(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    lines =[
        "project config.toml files are disabled in the following folders.",
        "1. /users/ilyagazman/.sheriffclaw/agents/codex/.codex",
        "to load config.toml, add trusted project",
    ]
    context, options = rt._extract_interactive_menu(lines)
    assert context == []
    assert options ==[]


def test_extract_inline_interactive_menu_from_compacted_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    text = (
        "IntroducingGPT-5.4 "
        "Choose how you'd like Codex to proceed. "
        "1. Try new model "
        "2. Use existing model "
        "Use ↑/↓ to move, press enter to confirm"
    )
    context, options = rt._extract_inline_interactive_menu(text)
    assert context
    assert options == [
        {"label": "try new model", "payload": b"\r"},
        {"label": "use existing model", "payload": b"\x1b[B\r"},
    ]


@pytest.mark.asyncio
async def test_unknown_compacted_prompt_publishes_manual_selection_prompt(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    rt.active_session_handle = "s5b"
    await rt._handle_codex_stdout(
        "IntroducingGPT-5.4 Choose how you'd like Codex to proceed. "
        "1. Try new model 2. Use existing model Use ↑/↓ to move, press enter to confirm"
    )
    pending = (rt.conversations_dir / "s5b" / "agent_user_pending.tmd").read_text(encoding="utf-8")
    assert "/option1 - try new model" in pending
    assert "/option2 - use existing model" in pending


def test_normalized_codex_text_strips_ansi(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    raw = "\x1b[31mTrust the current folder?\x1b[0m\r\n"
    assert rt._normalized_codex_text(raw) == "trust the current folder?\n"


@pytest.mark.asyncio
async def test_codex_ready_is_marked_from_greeting(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    await rt._handle_codex_stdout("• Hey. What do you want to chat about?\n")
    assert rt.codex_ready_marked is True
    assert rt.codex_ready_event.is_set()


@pytest.mark.asyncio
async def test_codex_ready_is_marked_from_fragmented_greeting(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    await rt._handle_codex_stdout("H\ni\n.\nW\nh\na\nt\nd\no\ny\no\nu\nw\na\nn\nt\nt\no\nw\no\nr\nk\no\nn\n?\n")
    assert rt.codex_ready_marked is True
    assert rt.codex_ready_event.is_set()


@pytest.mark.asyncio
async def test_codex_prompt_is_not_ready_during_boot_after_placeholder_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    await rt._handle_codex_stdout("› Implement {feature}\n")
    assert rt.codex_ready_marked is False
    await rt._handle_codex_stdout("• Booting MCP server: codex_apps\n")
    assert rt.codex_ready_marked is False
    await rt._handle_codex_stdout("• Hey. I'm here and ready.\n")
    assert rt.codex_ready_marked is True
    assert rt.codex_ready_event.is_set()


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
        "options":[
            {"label": "try new model", "payload": b"\r"},
            {"label": "use existing model", "payload": b"\x1b[B\r"},
        ],
    }
    calls =[]

    async def fake_write(payload, *, reason, session=None):
        calls.append((payload, reason, session))

    monkeypatch.setattr(rt, "_write_codex_control", fake_write)
    events =[]

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
        "options":[
            {"label": "one", "payload": b"\r"},
            {"label": "two", "payload": b"\x1b[B\r"},
        ],
    }
    events =[]

    async def emit(event, payload):
        events.append((event, payload))

    await rt.user_message("s7", "hello", None, emit)
    assert events ==[
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
            "options":[
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
    events =[]

    async def emit(event, payload):
        events.append((event, payload))

    await rt.user_message("s8", "hi", None, emit)
    assert events ==[
        (
            "assistant.final",
            {
                "text": "Codex is waiting on an interactive selection.\n\nChoose one:\n/option1 - try new model\n/option2 - use existing model"
            },
        )
    ]


@pytest.mark.asyncio
async def test_worker_reports_ready_timeout_before_sending(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    monkeypatch.setenv("SHERIFF_CODEX_READY_TIMEOUT_SEC", "0.01")
    rt = WorkerRuntime()
    fake_proc = _FakeProc()

    async def fake_ensure():
        rt.codex_proc = fake_proc
        rt.codex_start_error = ""
        rt.codex_ready_marked = False
        rt.codex_ready_event = asyncio.Event()
        rt.codex_stdout_task = object()

    monkeypatch.setattr(rt, "_ensure_codex_active", fake_ensure)

    events = []

    async def emit(event, payload):
        events.append((event, payload))

    await rt.user_message("s9", "hi", None, emit)
    assert events == [("assistant.final", {"text": "Codex background process did not reach a ready state."})]
    session_dir = rt.conversations_dir / "s9"
    assert not list(session_dir.glob("*_user_agent.tmd"))


def test_worker_debug_log_ignores_permission_error(monkeypatch, tmp_path):
    monkeypatch.setenv("SHERIFFCLAW_ROOT", str(tmp_path))
    rt = WorkerRuntime()
    original_open = type(rt.debug_log_path).open

    def _open(self, *args, **kwargs):
        if self == rt.debug_log_path:
            raise PermissionError("denied")
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(type(rt.debug_log_path), "open", _open)

    rt._debug_log("test_event", x=1)


@pytest.mark.skipif(__import__("os").name == "nt", reason="pty sizing only applies on posix")
def test_posix_pty_sets_window_size(monkeypatch):
    import shared.worker.worker_runtime as wr

    calls = []

    def fake_ioctl(fd, op, packed):
        calls.append((fd, op, packed))

    monkeypatch.setattr(wr.fcntl, "ioctl", fake_ioctl)
    wr._PosixPtyProcess._set_winsize(7, rows=33, cols=99)

    assert calls
