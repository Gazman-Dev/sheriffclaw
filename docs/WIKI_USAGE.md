# SheriffClaw Wiki — How to Use the System

## 1) Install
```bash
./install_sheriffclaw.sh
```

For non-interactive installs:
```bash
SHERIFF_MASTER_PASSWORD='your-password' SHERIFF_LLM_PROVIDER='stub' SHERIFF_NON_INTERACTIVE=1 ./install_sheriffclaw.sh
```

---

## 2) Configure LLM Credentials (outside Sheriff chat)
Use explicit config command:

```bash
sheriff-ctl configure-llm --provider openai-codex --api-key <OPENAI_API_KEY> --master-password <MASTER_PASSWORD>
```

This stores provider/api key in encrypted Sheriff secrets storage.

---

## 3) Start a Terminal Session
```bash
sheriff-ctl chat
```

Routing behavior:
- message starting with `/` -> Sheriff
- everything else -> Agent

Examples:
- `/status` -> Sheriff health
- `summarize the repo` -> Agent
- `what / do?` -> Agent (does not start with `/`)

---

## 4) Runtime Flow (Typical)
1. You ask Agent for a task.
2. Agent requests a sensitive action (tool/domain/secret/output).
3. Sheriff blocks and requires approval/resolution.
4. You respond in Sheriff channel (`/allow-*`, `/deny-*`, `/secret`, etc.).
5. Agent continues with updated permissions.

---

## 5) Useful Commands
### System
```bash
sheriff-ctl status
sheriff-ctl start
sheriff-ctl stop
sheriff-ctl logs sheriff-gateway
```

### Setup
```bash
sheriff-ctl onboard
sheriff-ctl configure-llm --provider openai-codex --api-key <KEY> --master-password <MASTER>
```

### Chat
```bash
sheriff-ctl chat
sheriff-ctl chat --model-ref test/default
sheriff-ctl chat --model-ref scenario/default
```

---

## 6) Validation / Testing
### Unit tests
```bash
pytest -q
```

### CLI simulation E2E
```bash
./scripts/e2e_cli_simulation.sh
```

### Installation E2E
```bash
./scripts/e2e_installation_check.sh
```

### Reinstall idempotency
```bash
./scripts/e2e_reinstall_idempotency.sh
```

### Linux docker suite
```bash
./scripts/test_linux_docker.sh
```

---

## 7) Troubleshooting
- **Vault locked errors**: run `/unlock <master_password>` in Sheriff chat or supply `--master-password` where supported.
- **No response from service**: check `sheriff-ctl status` and `sheriff-ctl logs <service>`.
- **Install issues on fresh machine**: rerun installer; it is designed to be idempotent and dependency-aware.
