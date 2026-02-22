# Task: Permissions + Secrets + Unlock Test Coverage (2026-02-21)

Source: user request in chat.

## Goals

Validate end-to-end behavior for:
- agent -> sheriff permission asks
- secret request/approval flow
- master password unlock prompts/flows after restart
- unlock via Telegram policy gate (`allow_telegram_master_password`)
- unlock via CLI command after restart

## Unit-test checklist

- [x] CLI sheriff `/unlock` success/failure/usage behavior
- [x] requests.boot_check when telegram unlock policy disabled
- [x] requests.boot_check when already unlocked
- [x] requests.submit_master_password success sends notify events
- [x] requests.submit_master_password success gateway payload shape
- [x] requests.submit_master_password failure does not send notify events
- [ ] extra transcript/log redaction checks (future)

## E2E scenario checklist

- [x] permissions + secrets flow smoke (existing simulation)
- [x] master-policy gate behavior (`boot_check` => required/ok)
- [x] submit master password wrong/correct transitions
- [x] integrated into scenario runner (`permissions_unlock`)
- [ ] real Telegram delivery loop (requires external bot env)

## Reporting format

Always report scenario pass/fail counts.
