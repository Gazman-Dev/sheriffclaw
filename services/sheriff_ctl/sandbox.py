# File: services/sheriff_ctl/sandbox.py

from __future__ import annotations

import os
import sys
from pathlib import Path

from shared.paths import agent_root, gw_root, llm_root


def _strict_sandbox_required() -> bool:
    v = os.environ.get("SHERIFF_STRICT_SANDBOX", "1").strip().lower()
    return v not in {"0", "false", "no"}


def _ai_worker_user() -> str:
    env_user = os.environ.get("SHERIFF_AI_WORKER_USER", "").strip()
    if env_user:
        return env_user
    p = gw_root() / "state" / "ai_worker_user.txt"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    return ""


def _network_allowed_for_ai_worker() -> bool:
    p = gw_root() / "state" / "ai_worker_allow_net.txt"
    if p.exists():
        v = p.read_text(encoding="utf-8").strip().lower()
        return v in {"1", "true", "yes"}
    v = os.environ.get("SHERIFF_AI_WORKER_ALLOW_NET", "1").strip().lower()
    return v not in {"0", "false", "no"}


def _set_ai_worker_user(user: str | None) -> None:
    p = gw_root() / "state" / "ai_worker_user.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    if user:
        p.write_text(user.strip(), encoding="utf-8")
    else:
        p.unlink(missing_ok=True)


def _set_ai_worker_allow_net(allow: bool) -> None:
    p = gw_root() / "state" / "ai_worker_allow_net.txt"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("1" if allow else "0", encoding="utf-8")


def _darwin_sandbox_profile_path() -> Path:
    return Path("/private/tmp/sheriffclaw") / "ai_worker.sb"


def _darwin_ai_worker_launcher_path() -> Path:
    return Path("/usr/local/bin/sheriff-ai-worker-launch")


def _darwin_ai_worker_runtime_root() -> Path:
    user = _ai_worker_user().strip() or "sheriffai"
    return Path("/Users") / user / "ai-runtime"


def _ai_worker_sandbox_profile() -> Path:
    if sys.platform == "darwin":
        p = _darwin_sandbox_profile_path()
    else:
        p = gw_root() / "state" / "ai_worker.sb"
    workspace = gw_root().parent.resolve()
    agent_ws = agent_root().resolve()
    agent_ws.mkdir(parents=True, exist_ok=True)

    net_rule = "(allow network-outbound) (allow network-inbound)" if _network_allowed_for_ai_worker() else ""
    gw = gw_root().resolve()
    llm = llm_root().resolve()
    runtime_root = _darwin_ai_worker_runtime_root().resolve()

    profile = f'''(version 1)
(allow default)
{net_rule}

; Allow reading the application source code (read-only)
(allow file-read* (subpath "{workspace}"))

; EXPLICITLY DENY the gateway directory where Sheriff secrets are kept
(deny file-read* file-write* (subpath "{gw}"))

; Allow full access to the designated agent workspace
(allow file-read* file-write* (subpath "{agent_ws}"))

; Allow full access to LLM logs and state
(allow file-read* file-write* (subpath "{llm}"))

; Allow the dedicated ai-worker runtime under the service user's home.
(allow file-read* file-write* (subpath "{runtime_root}"))

; Allow temp directories needed by node/npm/python
(allow file-read* file-write* (subpath "/private/tmp"))
(allow file-read* file-write* (subpath "/private/var/folders"))
'''
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(profile, encoding="utf-8")
    try:
        p.chmod(0o644)
    except OSError:
        pass
    return p


def _linux_sandbox_profile() -> Path:
    p = gw_root() / "state" / "ai_worker.bwrap.args"
    workspace = gw_root().parent.resolve()
    agent_ws = agent_root().resolve()
    skill_root = (workspace / "skills").resolve()
    system_skill_root = (workspace / "system_skills").resolve()
    gw = gw_root().resolve()
    llm = llm_root().resolve()
    sys_prefix = Path(sys.prefix).resolve()
    home = Path.home().resolve()

    agent_ws.mkdir(parents=True, exist_ok=True)
    (llm / "logs").mkdir(parents=True, exist_ok=True)

    args = [
        "--die-with-parent",
        "--unshare-all",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind", "/bin", "/bin",
        "--ro-bind", "/lib", "/lib",
        "--ro-bind", "/lib64", "/lib64",
        "--ro-bind", "/etc", "/etc",
        "--proc", "/proc",
        "--dev", "/dev",
        "--tmpfs", "/tmp",

        # Hide the user's entire home directory by mounting an empty tmpfs over it
        "--tmpfs", str(home),
    ]
    if _network_allowed_for_ai_worker():
        args.insert(2, "--share-net")

    # Re-bind only what is needed from home
    if sys_prefix != Path("/usr"):
        args.extend(["--ro-bind", str(sys_prefix), str(sys_prefix)])

    args.extend([
        # Bind the sheriffclaw workspace read-only back into the hidden home dir
        "--ro-bind", str(workspace), str(workspace),

        # Overlay a tmpfs on the gateway directory so secrets db cannot be read
        "--tmpfs", str(gw),

        # Bind specific paths the agent is allowed to write to
        "--bind", str(agent_ws), str(agent_ws),
        "--bind", str(llm), str(llm),
        "--chdir", str(agent_ws),  # Force agent to start inside its sandbox jail
    ])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(args), encoding="utf-8")
    return p


def cmd_sandbox(args):
    if args.user is not None:
        _set_ai_worker_user(args.user if args.user else None)
    if args.allow_net is not None:
        _set_ai_worker_allow_net(bool(args.allow_net))

    current_user = _ai_worker_user()
    print(f"ai-worker user: {current_user or '(current user)'}")
    print(f"ai-worker network: {'allowed' if _network_allowed_for_ai_worker() else 'disabled'}")
