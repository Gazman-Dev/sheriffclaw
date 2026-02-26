from __future__ import annotations

import asyncio
import base64
import io
import os
import shutil
import subprocess
import tarfile
from pathlib import Path
from typing import Any

import requests  # backward-compatible import target for existing tests


class StubProvider:
    async def generate(self, messages: list[dict], model: str = "stub") -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"Assistant: {last}" if last else "Assistant: ready"


class TestProvider:
    async def generate(self, messages: list[dict], model: str = "test") -> str:
        last = next((m["content"] for m in reversed(messages) if m.get("role") == "user"), "")
        return f"TestBot[{model}]: {last}" if last else f"TestBot[{model}]: ready"


class _CodexCliBase:
    _codex_checked = False

    def __init__(self, codex_state_b64: str = ""):
        self.codex_state_b64 = codex_state_b64 or ""
        self.last_codex_state_b64 = self.codex_state_b64

    @classmethod
    def _ensure_codex_installed(cls) -> None:
        if shutil.which("codex"):
            cls._codex_checked = True
            return
        if cls._codex_checked:
            return
        cls._codex_checked = True
        npm = shutil.which("npm")
        if not npm:
            raise RuntimeError("codex CLI missing and npm not found; install @openai/codex manually")
        proc = subprocess.run([npm, "i", "-g", "@openai/codex"], capture_output=True, text=True, check=False)  # noqa: S603
        if proc.returncode != 0 or not shutil.which("codex"):
            msg = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"failed to lazy-install codex CLI: {msg}")

    @staticmethod
    def _render_prompt(messages: list[dict[str, Any]]) -> str:
        lines: list[str] = [
            "System: You are the AI Agent for Sheriff Claw.",
            "System: You are running inside a strict OS-level sandbox. Your entire file system access is restricted.",
            "System: You CANNOT read or write files in the user's home directory. You ONLY have access to your workspace.",
            "System: You HAVE outbound internet access to fetch docs, search the web, and download dependencies into your workspace.",
            "System: SECURITY POLICY: Do NOT attempt to install software globally or access personal files.",
            "System: If you need a secret (like an API key, DB credential, etc.), you MUST request it from the user via the Sheriff API.",
            "System: To request a secret via Sheriff API, execute: `sheriff-ctl call sheriff-requests requests.create_or_update --json '{\"type\": \"secret\", \"key\": \"<name_of_secret>\", \"one_liner\": \"<why you need it>\"}'`",
            "System: After requesting a secret, STOP and politely ask the user to approve it in their Sheriff channel.",
            "System: CORE COMMANDS ALWAYS AVAILABLE TO YOU (Run via `tools.exec`):",
            "System:   - `python skills/search_skills/run.py \"query\"`: Searches your available peripheral skills.",
            "System:   - `python skills/search_memory/run.py \"query\"`: Search past conversations you have had with the user.",
            "System:   - `python skills/search_topics/run.py \"query\"`: Search facts, rules, and concepts in your topic database.",
            "System: If a user asks you to do something you don't know how to do, use `search_skills` first.",
            "System: If the user refers to something you spoke about in the past, use `search_memory`.",
            "Conversation history:"
        ]
        for m in messages[-20:]:
            role = str(m.get("role", "user"))
            content = str(m.get("content", ""))
            lines.append(f"[{role}] {content}")
        lines.append("\nReply as the assistant to the last user message.")
        return "\n".join(lines)

    @staticmethod
    def _ensure_macos_ramdisk(mount_point: Path, size_mb: int = 64) -> None:
        mount_point.parent.mkdir(parents=True, exist_ok=True)
        if mount_point.exists() and any(mount_point.iterdir()):
            return
        mount_point.mkdir(parents=True, exist_ok=True)

        # Create a RAM disk and mount it at mount_point (best-effort idempotent).
        sectors = str(size_mb * 2048)
        dev = subprocess.run(["hdiutil", "attach", "-nomount", f"ram://{sectors}"], capture_output=True, text=True, check=True).stdout.strip()  # noqa: S603
        subprocess.run(["newfs_hfs", "-v", "SheriffCodexRAM", dev], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)  # noqa: S603
        subprocess.run(["mount", "-t", "hfs", dev, str(mount_point)], check=True)  # noqa: S603

    @staticmethod
    def _ram_codex_home() -> Path:
        # Linux: require tmpfs-backed /dev/shm.
        if Path("/dev/shm").exists():
            p = Path("/dev/shm") / "sheriff-codex-home"
            p.mkdir(parents=True, exist_ok=True)
            return p

        # macOS: create dedicated RAM disk mount.
        if os.uname().sysname.lower() == "darwin":
            # Place inside llm_root() so the OS sandbox naturally permits read/write
            p = Path(os.environ.get("SHERIFFCLAW_ROOT", Path.home() / ".sheriffclaw")).resolve() / "llm" / "run" / "codex-ram"
            _CodexCliBase._ensure_macos_ramdisk(p)
            return p

        raise RuntimeError("No RAM-backed filesystem available for CODEX_HOME")

    def _restore_codex_state(self, codex_home: Path) -> None:
        if not self.codex_state_b64:
            return
        raw = base64.b64decode(self.codex_state_b64.encode("utf-8"))
        with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as tf:
            tf.extractall(codex_home)

    def _snapshot_codex_state(self, codex_home: Path) -> str:
        bio = io.BytesIO()
        # macOS adds these root-owned directories to mounted volumes; skip them.
        skip_names = {".fseventsd", ".Trashes", ".Spotlight-V100", ".TemporaryItems"}

        with tarfile.open(fileobj=bio, mode="w:gz") as tf:
            for child in codex_home.iterdir():
                if child.name in skip_names:
                    continue
                try:
                    tf.add(child, arcname=child.name)
                except PermissionError:
                    pass  # Ignore unreadable files so the rest of the snapshot completes
        return base64.b64encode(bio.getvalue()).decode("utf-8")

    def _run_codex_exec(self, prompt: str, model: str, env_extra: dict[str, str] | None = None) -> str:
        self._ensure_codex_installed()
        codex_home = self._ram_codex_home()
        try:
            self._restore_codex_state(codex_home)
        except Exception:
            pass

        # Define the agent workspace explicitly
        workspace_dir = Path(os.environ.get("SHERIFFCLAW_ROOT", Path.home() / ".sheriffclaw")).resolve() / "agent_workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)
        # Force tools like npm and git to use the workspace as their home directory
        env["HOME"] = str(workspace_dir)
        if env_extra:
            env.update({k: v for k, v in env_extra.items() if v is not None})

        cmd = [
            "codex",
            "--search",
            "--dangerously-bypass-approvals-and-sandbox",
            "exec",
            "-C", str(workspace_dir),
            "--skip-git-repo-check",
            "--model",
            model,
            prompt,
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env, check=False)  # noqa: S603

        try:
            self.last_codex_state_b64 = self._snapshot_codex_state(codex_home)
        except Exception:
            self.last_codex_state_b64 = self.codex_state_b64

        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise RuntimeError(f"codex exec failed ({proc.returncode}): {err}")
        out = (proc.stdout or "").strip()
        if out:
            return out
        raise RuntimeError("codex exec returned empty stdout")


class OpenAICodexProvider(_CodexCliBase):
    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1", codex_state_b64: str = ""):
        super().__init__(codex_state_b64=codex_state_b64)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    def _generate_sync(self, messages: list[dict], model: str) -> str:
        if not self.api_key:
            raise ValueError("missing OpenAI API key")
        prompt = self._render_prompt(messages)
        return self._run_codex_exec(prompt, model, {"OPENAI_API_KEY": self.api_key})

    async def generate(self, messages: list[dict], model: str = "gpt-5.3-codex") -> str:
        return await asyncio.to_thread(self._generate_sync, messages, model)


class ChatGPTSubscriptionCodexProvider(_CodexCliBase):
    def __init__(self, access_token: str, base_url: str = "https://chatgpt.com/backend-api/codex", codex_state_b64: str = ""):
        super().__init__(codex_state_b64=codex_state_b64)
        self.access_token = access_token
        self.base_url = base_url.rstrip("/")

    def _generate_sync(self, messages: list[dict], model: str) -> str:
        prompt = self._render_prompt(messages)
        # Subscription auth should come from restored CODEX_HOME login state.
        return self._run_codex_exec(prompt, model)

    async def generate(self, messages: list[dict], model: str = "gpt-5.3-codex") -> str:
        return await asyncio.to_thread(self._generate_sync, messages, model)