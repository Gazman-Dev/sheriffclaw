# File: services/sheriff_ctl/onboard.py

from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from shared.paths import gw_root
from shared.proc_rpc import ProcClient
from services.sheriff_ctl.service_runner import MANAGED_SERVICES, SERVICE_MANAGER
from services.sheriff_ctl.utils import (
    OPLOG,
    _clear_telegram_unlock_channel,
    _gw_secrets_call,
    _is_onboarded,
    _save_telegram_unlock_channel,
)


def cmd_onboard(args):
    print("=== SheriffClaw Onboarding ===")
    debug_mode = os.environ.get("SHERIFF_DEBUG", "").strip().lower() in {"1", "true", "yes"}

    mp = args.master_password
    if mp is None:
        if _is_onboarded():
            if bool(getattr(args, "keep_unchanged", False)):
                mp = getpass.getpass("Current Master Password (keep unchanged mode): ")
            else:
                choice = input("Master password: [K]eep current / [N]ew? (default K): ").strip().lower()
                if choice in {"", "k", "keep"}:
                    mp = getpass.getpass("Current Master Password: ")
                else:
                    while True:
                        a = getpass.getpass("Set New Master Password: ")
                        b = getpass.getpass("Confirm New Master Password: ")
                        if a and a == b:
                            mp = a
                            break
                        print("Passwords do not match. Please try again.")
        else:
            while True:
                a = getpass.getpass("Set Master Password: ")
                b = getpass.getpass("Confirm Master Password: ")
                if a and a == b:
                    mp = a
                    break
                print("Passwords do not match. Please try again.")

    if debug_mode and mp != "debug":
        print("Debug mode active: master password forced to 'debug'.")
        mp = "debug"

    llm_prov = args.llm_provider
    llm_key = args.llm_api_key
    llm_auth = None
    codex_state_b64 = ""
    keep_unchanged = bool(getattr(args, "keep_unchanged", False))
    existing: dict[str, str] = {}

    if keep_unchanged and _is_onboarded():
        async def _load_existing() -> dict[str, str]:
            gw = ProcClient("sheriff-gateway")
            ok = await _gw_secrets_call("secrets.unlock", {"master_password": mp}, gw=gw)
            if not ok.get("ok"):
                raise RuntimeError("failed to unlock with provided master password")
            p = await _gw_secrets_call("secrets.get_llm_provider", {}, gw=gw)
            k = await _gw_secrets_call("secrets.get_llm_api_key", {}, gw=gw)
            la = await _gw_secrets_call("secrets.get_llm_auth", {}, gw=gw)
            lb = await _gw_secrets_call("secrets.get_llm_bot_token", {}, gw=gw)
            gb = await _gw_secrets_call("secrets.get_gate_bot_token", {}, gw=gw)
            return {
                "llm_provider": p.get("provider") or "",
                "llm_api_key": k.get("api_key") or "",
                "llm_auth": la.get("auth") or {},
                "llm_bot_token": lb.get("token") or "",
                "gate_bot_token": gb.get("token") or "",
            }

        try:
            existing = asyncio.run(_load_existing())
            policy_path = gw_root() / "state" / "master_policy.json"
            if policy_path.exists():
                policy = json.loads(policy_path.read_text(encoding="utf-8"))
                existing["allow_telegram_master_password"] = bool(policy.get("allow_telegram_master_password", False))
        except Exception as e:
            raise RuntimeError(f"keep-unchanged requested but could not load existing config: {e}")

    if llm_prov is None:
        while True:
            print("\nChoose your LLM:")
            print("1) OpenAI Codex (API key)")
            print("2) OpenAI Codex (ChatGPT subscription login)")
            print("3) Local stub (testing only)")
            default_choice = "1"
            if keep_unchanged and existing.get("llm_provider"):
                cur = existing.get("llm_provider")
                if cur == "openai-codex-chatgpt":
                    default_choice = "2"
                elif cur == "stub":
                    default_choice = "3"
            if keep_unchanged and existing.get("llm_provider"):
                choice = input("Select [1/2/3] or K to keep current provider: ").strip().lower()
                if not choice or choice == "k":
                    llm_prov = existing.get("llm_provider")
                    llm_key = existing.get("llm_api_key", "")
                    if llm_prov == "openai-codex-chatgpt":
                        llm_auth = existing.get("llm_auth") or None
                    break
            else:
                choice = input(f"Select [1/2/3] (default {default_choice}): ").strip() or default_choice

            if choice == "3":
                llm_prov = "stub"
                llm_key = ""
                break

            if choice == "1":
                llm_prov = "openai-codex"
                if keep_unchanged and existing.get("llm_api_key"):
                    entered = getpass.getpass("OpenAI API Key (Enter=keep unchanged): ").strip()
                    llm_key = entered or existing.get("llm_api_key", "")
                else:
                    llm_key = getpass.getpass("OpenAI API Key: ").strip()
                break

            if choice == "2":
                print("Starting Codex CLI login...")
                try:
                    from shared.llm.providers import _CodexCliBase

                    codex_home = _CodexCliBase._ram_codex_home()
                    env = os.environ.copy()
                    env["CODEX_HOME"] = str(codex_home)

                    proc = subprocess.Popen(["codex", "login"], env=env)  # noqa: S603
                    print("\nBrowser login in progress. Complete login, then press Enter here.")
                    input("Press Enter after finishing login in browser...")

                    st = subprocess.run(["codex", "login", "status"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)  # noqa: S603
                    if st.returncode != 0:
                        if proc.poll() is None:
                            proc.terminate()
                        print("codex login status is not authenticated. Please retry.")
                        continue

                    if proc.poll() is None:
                        proc.terminate()

                    # snapshot CODEX_HOME into encrypted vault state bundle
                    snap = _CodexCliBase(codex_state_b64="")._snapshot_codex_state(codex_home)
                    codex_state_b64 = snap
                except Exception as e:
                    print(f"Login cancelled/failed: {e}")
                    continue
                llm_prov = "openai-codex-chatgpt"
                llm_key = ""
                llm_auth = None
                break

    if llm_key is None:
        if llm_prov == "openai-codex":
            if keep_unchanged and existing.get("llm_api_key"):
                entered = getpass.getpass("OpenAI API Key (Enter=keep unchanged): ").strip()
                llm_key = entered or existing.get("llm_api_key", "")
            else:
                llm_key = getpass.getpass("OpenAI API Key: ").strip()
        else:
            llm_key = ""

    channel = "telegram"
    print("\nChannel setup:")
    print("- Telegram is currently the supported channel")

    llm_bot = args.llm_bot_token
    if llm_bot is None:
        if keep_unchanged and existing.get("llm_bot_token"):
            llm_bot = input("Telegram AI bot token (Enter=keep unchanged): ").strip() or existing.get("llm_bot_token", "")
        else:
            llm_bot = input("Telegram AI bot token (BotFather): ").strip()

    gate_bot = args.gate_bot_token

    allow_tg = False

    async def _telegram_activate_bot(gw: ProcClient, role: str, token: str, timeout_sec: int = 300) -> bool:
        import requests

        print(f"\n{role.upper()} bot activation:")
        print("1) Open Telegram and send any message to the bot.")
        print("2) The bot will reply with an activation code.")
        print("3) Paste that code here.")

        # If webhook is currently set for this token, getUpdates will not deliver messages.
        # Best-effort disable webhook during activation polling.
        try:
            r = requests.post(
                f"https://api.telegram.org/bot{token}/deleteWebhook",
                json={"drop_pending_updates": False},
                timeout=15,
            )
            OPLOG.info("activation[%s] deleteWebhook status=%s body=%s", role, r.status_code, (r.text or "")[:300])
        except Exception as e:
            OPLOG.exception("activation[%s] deleteWebhook failed: %s", role, e)

        offset = 0
        sent_codes: dict[str, str] = {}
        user_chat: dict[str, int] = {}
        start = time.time()
        wait_ticks = 0

        while time.time() - start < timeout_sec:
            # Already activated?
            st = await _gw_secrets_call("secrets.activation.status", {"bot_role": role}, gw=gw)
            if st.get("user_id"):
                return True

            try:
                resp = requests.get(
                    f"https://api.telegram.org/bot{token}/getUpdates",
                    params={"timeout": 20, "allowed_updates": '["message"]', "offset": offset},
                    timeout=30,
                )
                data = resp.json()
                updates = data.get("result", []) if isinstance(data, dict) else[]
                OPLOG.info("activation[%s] getUpdates status=%s count=%s offset=%s", role, resp.status_code, len(updates), offset)
            except Exception as e:
                OPLOG.exception("activation[%s] getUpdates failed: %s", role, e)
                updates =[]

            for upd in updates:
                update_id = int(upd.get("update_id", 0))
                offset = max(offset, update_id + 1)
                msg = upd.get("message") or {}
                from_user = msg.get("from") or {}
                chat = msg.get("chat") or {}
                user_id = str(from_user.get("id") or "")
                chat_id = chat.get("id")
                text_in = (msg.get("text") or "").strip()
                OPLOG.info(
                    "activation[%s] update id=%s has_message=%s user_id=%s chat_id=%s has_text=%s",
                    role,
                    update_id,
                    bool(msg),
                    bool(user_id),
                    chat_id,
                    bool(text_in),
                )
                if not user_id or chat_id is None:
                    OPLOG.info("activation[%s] skip update id=%s reason=missing_user_or_chat", role, update_id)
                    continue

                bound = await _gw_secrets_call("secrets.activation.status", {"bot_role": role}, gw=gw)
                bound_uid = bound.get("user_id")
                if bound_uid and str(bound_uid) == user_id:
                    OPLOG.info("activation[%s] skip update id=%s reason=already_bound user_id=%s", role, update_id, user_id)
                    continue

                code = sent_codes.get(user_id)
                if not code:
                    c = await _gw_secrets_call("secrets.activation.create", {"bot_role": role, "user_id": user_id}, gw=gw)
                    code = c.get("code")
                    if not code:
                        OPLOG.warning("activation[%s] failed to create code user_id=%s response=%s", role, user_id, c)
                        continue
                    sent_codes[user_id] = code
                    user_chat[user_id] = int(chat_id)

                    text = f"Your activation code is: {code}"
                    try:
                        s = requests.post(
                            f"https://api.telegram.org/bot{token}/sendMessage",
                            json={"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
                            timeout=15,
                        )
                        OPLOG.info("activation[%s] send code chat_id=%s status=%s body=%s", role, chat_id, s.status_code, (s.text or "")[:300])
                    except Exception as e:
                        OPLOG.exception("activation[%s] send code failed chat_id=%s err=%s", role, chat_id, e)

            if sent_codes:
                try:
                    code_in = input(f"Enter {role} activation code: ").strip().upper()
                except KeyboardInterrupt:
                    return False
                if not code_in:
                    continue
                claim = await _gw_secrets_call("secrets.activation.claim", {"bot_role": role, "code": code_in}, gw=gw)
                if claim.get("ok"):
                    ok_user = str(claim.get("user_id") or "")
                    ok_chat = user_chat.get(ok_user)
                    OPLOG.info("activation[%s] claim success user_id=%s chat_id=%s", role, ok_user, ok_chat)
                    if ok_chat:
                        try:
                            s = requests.post(
                                f"https://api.telegram.org/bot{token}/sendMessage",
                                json={"chat_id": ok_chat, "text": "✅ Activated. You can chat now.", "disable_web_page_preview": True},
                                timeout=15,
                            )
                            OPLOG.info("activation[%s] send success message chat_id=%s status=%s", role, ok_chat, s.status_code)
                        except Exception as e:
                            OPLOG.exception("activation[%s] send success message failed chat_id=%s err=%s", role, ok_chat, e)
                    return True
                print("Invalid code, try again.")
            else:
                wait_ticks += 1
                if wait_ticks % 5 == 1:
                    OPLOG.info("activation[%s] waiting for DM... elapsed=%ss", role, int(time.time() - start))
                print("Waiting for a Telegram DM to the bot...")
                await asyncio.sleep(2)

        OPLOG.warning("activation[%s] timed out after %ss", role, timeout_sec)
        return False

    async def _run():
        gw = ProcClient("sheriff-gateway")
        # Give services a moment to be ready if we just started them
        for _ in range(5):
            try:
                await gw.request("health", {})
                break
            except Exception:
                await asyncio.sleep(1)

        await _gw_secrets_call(
            "secrets.initialize",
            {
                "master_password": mp,
                "llm_provider": llm_prov,
                "llm_api_key": llm_key,
                "llm_bot_token": llm_bot,
                "gate_bot_token": "",
                "allow_telegram_master_password": False,
            },
            gw=gw,
        )
        unlock_res = await _gw_secrets_call("secrets.unlock", {"master_password": mp}, gw=gw)
        if not unlock_res.get("ok"):
            OPLOG.error("onboard unlock failed after initialize: %s", unlock_res)
            raise RuntimeError("failed to unlock vault after onboarding initialize")
        st_unlock = await _gw_secrets_call("secrets.is_unlocked", {}, gw=gw)
        if not st_unlock.get("unlocked"):
            OPLOG.error("onboard unlock check failed after initialize: %s", st_unlock)
            raise RuntimeError("vault is still locked after unlock")

        if llm_auth:
            await _gw_secrets_call("secrets.set_llm_auth", {"auth": llm_auth}, gw=gw)
        if codex_state_b64:
            await _gw_secrets_call("secrets.codex_state.set", {"bundle_b64": codex_state_b64}, gw=gw)
            # Subscription auth now lives in codex CLI state bundle.
            await _gw_secrets_call("secrets.clear_llm_auth", {}, gw=gw)

        interactive = sys.stdin.isatty()

        if llm_bot:
            await _gw_secrets_call("secrets.set_llm_bot_token", {"token": llm_bot}, gw=gw)
            if interactive:
                ok = await _telegram_activate_bot(gw, "llm", llm_bot)
                if ok:
                    print("AI bot activated.")
                else:
                    print("AI bot activation timed out/cancelled.")

        gate_tok = gate_bot
        if gate_tok is None:
            if keep_unchanged and existing.get("gate_bot_token"):
                gate_tok = input("Telegram Sheriff bot token (Enter=keep unchanged): ").strip() or existing.get("gate_bot_token", "")
            else:
                gate_tok = input("Telegram Sheriff bot token (BotFather): ").strip()

        if gate_tok:
            await _gw_secrets_call("secrets.set_gate_bot_token", {"token": gate_tok}, gw=gw)
            if interactive:
                ok = await _telegram_activate_bot(gw, "sheriff", gate_tok)
                if ok:
                    print("Sheriff bot activated.")
                else:
                    print("Sheriff bot activation timed out/cancelled.")

        if (llm_bot or gate_tok) and not interactive:
            print("Skipping activation wait in non-interactive mode.")

        # Ask unlock policy only after activation phase
        nonlocal allow_tg
        if args.allow_telegram:
            allow_tg = True
        elif args.deny_telegram:
            allow_tg = False
        else:
            if keep_unchanged and "allow_telegram_master_password" in existing:
                cur = "Y" if existing.get("allow_telegram_master_password") else "N"
                ans = input(f"Allow sending master password via Telegram to unlock?[y/N] (Enter=keep {cur}): ").strip().lower()
                if not ans:
                    allow_tg = bool(existing.get("allow_telegram_master_password"))
                else:
                    allow_tg = ans in ("y", "yes")
            else:
                ans = input("Allow sending master password via Telegram to unlock? [y/N]: ").strip().lower()
                allow_tg = ans in ("y", "yes")

        master_policy = gw_root() / "state" / "master_policy.json"
        master_policy.parent.mkdir(parents=True, exist_ok=True)
        master_policy.write_text(json.dumps({"allow_telegram_master_password": allow_tg}), encoding="utf-8")

        # Optional: allow proactive lock/unlock notifications via Sheriff channel only.
        if allow_tg and gate_tok:
            bound = await _gw_secrets_call("secrets.activation.status", {"bot_role": "sheriff"}, gw=gw)
            bound_uid = str(bound.get("user_id") or "")
            if bound_uid:
                _save_telegram_unlock_channel(token=gate_tok, user_id=bound_uid)
            else:
                _clear_telegram_unlock_channel()
        else:
            _clear_telegram_unlock_channel()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nOnboarding cancelled.")
        return

    # Keep edge listener services alive after onboarding so Telegram replies work immediately.
    SERVICE_MANAGER.start_many(MANAGED_SERVICES)

    if mp:
        async def _post_unlock() -> bool:
            gw = ProcClient("sheriff-gateway")
            for _ in range(20):
                try:
                    await gw.request("health", {})
                    break
                except Exception:
                    await asyncio.sleep(0.2)
            st = await _gw_secrets_call("secrets.is_unlocked", {}, gw=gw)
            if st.get("unlocked"):
                return True
            res = await _gw_secrets_call("secrets.unlock", {"master_password": mp}, gw=gw)
            return bool(res.get("ok"))

        ok_unlock = asyncio.run(_post_unlock())
        if not ok_unlock:
            print("Warning: services started, but vault unlock failed in running secrets service.")

    print("Onboarding complete. Services started and secrets unlocked.")


def cmd_configure_llm(args):
    provider = args.provider or "openai-codex"
    api_key = args.api_key
    if api_key is None:
        api_key = getpass.getpass(f"API key for {provider}: ").strip()

    async def _run():
        gw = ProcClient("sheriff-gateway")
        unlocked = await _gw_secrets_call("secrets.is_unlocked", {}, gw=gw)
        if not unlocked.get("unlocked"):
            if not args.master_password:
                raise RuntimeError("vault is locked; pass --master-password to configure llm")
            res = await _gw_secrets_call("secrets.unlock", {"master_password": args.master_password}, gw=gw)
            if not res.get("ok"):
                raise RuntimeError("failed to unlock vault with provided master password")

        await _gw_secrets_call("secrets.set_llm_provider", {"provider": provider}, gw=gw)
        await _gw_secrets_call("secrets.set_llm_api_key", {"api_key": api_key}, gw=gw)

    asyncio.run(_run())
    print(f"LLM provider configured: {provider}")


def cmd_logout_llm(args):
    async def _run():
        gw = ProcClient("sheriff-gateway")
        unlocked = await _gw_secrets_call("secrets.is_unlocked", {}, gw=gw)
        if not unlocked.get("unlocked"):
            if not args.master_password:
                raise RuntimeError("vault is locked; pass --master-password")
            res = await _gw_secrets_call("secrets.unlock", {"master_password": args.master_password}, gw=gw)
            if not res.get("ok"):
                raise RuntimeError("failed to unlock vault with provided master password")
        await _gw_secrets_call("secrets.set_llm_api_key", {"api_key": ""}, gw=gw)
        await _gw_secrets_call("secrets.clear_llm_auth", {}, gw=gw)

    asyncio.run(_run())
    print("LLM auth cleared from vault.")
