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
            "System: You are running in an environment where you DO have outbound internet access. You can use curl, python, etc., to fetch data.",
            "System: To request secrets or permissions from the user, you can interact with the Sheriff API by executing the local `sheriff-ctl` command in your shell.",
            "System: Example to request a secret: `sheriff-ctl call sheriff-requests requests.create_or_update --json '{\"type\": \"secret\", \"key\": \"github_token\", \"one_liner\": \"Need token to clone repo\"}'`",
            "System: The user will approve or deny requests securely through their Sheriff channel.",
            "Conversation history:"
        ]
        for msg in messages[-20:]:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
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
            p = Path.home() / ".sheriffclaw" / "runtime" / "codex-ram"
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

        env = os.environ.copy()
        env["CODEX_HOME"] = str(codex_home)
        if env_extra:
            env.update({k: v for k, v in env_extra.items() if v is not None})

        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--full-auto",
            "--sandbox",
            "none",  # Disabled internal sandbox so OS-level Sheriff sandbox takes over
            "--search", # Enables live internet search capability for the agent
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