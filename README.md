# Python OpenClaw clone

Local-first prototype gateway + untrusted worker architecture for `sheriffclaw.dev`.

## Features
- Trusted Gateway Core with policy engine, approvals, transcript store, and audit records.
- Unified encrypted `SecretsService` for master-password auth + secrets + identity state.
- Dual Telegram adapters (LLM bot + Secrets bot) plus CLI primitives.
- Async-first structure and pytest coverage.

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

## Onboarding v1 flow
`python -m python_openclaw.cli.onboard`

Flow:
1. Choose master password.
2. Choose LLM provider.
3. Provide LLM API token (stored encrypted).
4. Provide two Telegram bot tokens (LLM + Secrets channel).
5. Choose whether master password may be sent via Telegram.
   - **Yes**: Secrets channel config is stored plaintext for bootstrapping, LLM token remains encrypted.
   - **No**: Secrets channel token is encrypted and runtime unlock is CLI-only.
6. Send messages to both bots; onboarding echoes message candidates and confirmation binds trusted users.

## Runtime unlock modes
- **CLI mode**: start runtime and enter master password locally.
- **Telegram mode** (only if enabled during onboarding): start gate bot, then trusted user sends `/unlock <master_password>` in secrets channel.

There is no HTTPS unlock server in v1.
