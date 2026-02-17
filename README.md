# SheriffClaw

## Quickstart

```bash
pip install -e .
sheriff-ctl start
sheriff-ctl onboard --master-password devpass
sheriff-ctl skill summarize --stdin "hello world"
sheriff-ctl status
```

## Services

- GW island: sheriff-secrets, sheriff-policy, sheriff-web, sheriff-tools, sheriff-gateway, sheriff-tg-gate, sheriff-ctl
- LLM island: ai-worker, ai-tg-llm

All service RPC is NDJSON over stdio.

## Debug call

```bash
sheriff-ctl call sheriff-gateway gateway.handle_user_message --json '{"channel":"cli","context":{"local_user":"x"},"principal_external_id":"x","text":"hi"}'
```
