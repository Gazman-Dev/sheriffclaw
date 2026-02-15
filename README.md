# Python OpenClaw clone

Local-first prototype gateway + untrusted worker architecture for `sheriffclaw.dev`.

## Features
- Trusted Gateway Core with policy engine, approvals, encrypted secrets store, transcript store, and audit records.
- Untrusted LLM Worker emitting streaming assistant/tool events.
- Generic secure HTTP tool (`secure.web.request`) with host allowlists, HTTPS-only behavior, and auth header injection from encrypted secret handles.
- Two Telegram adapters (LLM bot + Secure bot) plus CLI adapter.
- Async-first structure and comprehensive pytest coverage.

## Threat model and limitations
- Secrets are encrypted at rest with passphrase-derived keys and only decrypted in memory while unlocked.
- Gateway and worker are separated by interfaces/IPC abstraction. Worker never receives secret values.
- This does **not** protect against a fully compromised OS/root attacker, memory scraping, or malware running as the same user.
- Telegram transport security, token management, and operational hardening remain your responsibility.

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e . pytest
```

## Run tests
```bash
pytest
```

## Minimal runtime wiring
Instantiate:
1. `SecretStore` at `~/.python_openclaw/secrets.enc`
2. `GatewayPolicy` with explicit `allowed_hosts`
3. `SecureWebConfig` with `header_allowlist` and `auth_host_permissions`
4. `GatewayCore` with `IPCClient(Worker())`
5. Channel adapters (`TelegramLLMBotAdapter`, `TelegramSecureBotAdapter`, `CLIChannel`)

Then:
- Use Secure Bot `/unlock <passphrase>` and `/setsecret github`
- Allow users via `/allow <telegram_user_id>`
- LLM user asks “call github” and request enters approval workflow.

## Config notes
- To add allowed destinations, add exact hostnames to `GatewayPolicy.allowed_hosts`.
- To allow auth handle on host, set `auth_host_permissions = {"github": {"api.github.com"}}`.
- Redirects are disabled by default; if enabled, redirect hosts are re-validated through the same allowlist policy.

## Approval workflow
1. Worker requests `secure.web.request` with `auth_handle`.
2. Gateway emits approval request (principal/method/host/path/handle/body summary).
3. Secure operator approves/denies in secure bot.
4. Approval mints one-time capability token with TTL.
5. Gateway verifies token and executes request.
