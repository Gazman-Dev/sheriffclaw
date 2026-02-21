# Task: E2E Test Matrix Expansion (2026-02-21)

Source: user request in chat to add broader end-to-end coverage and execute it.

## Scenario backlog

- [x] Fresh install → one-shot sheriff message
- [x] Fresh install → sheriff slash routing
- [ ] One-shot wait behavior (10s after last response, Esc cancel)
- [x] Onboarded no-arg menu flow branches
- [x] Restart auth gate (wrong vs correct master password)
- [x] Factory reset integrity (state wiped)
- [ ] Keep-unchanged onboarding mode
- [ ] Debug mode FIFO behavior (`debug.agent.jsonl`)
- [x] Installer idempotency (repeat install / aliases)
- [x] Docker matrix sanity (fresh container path)

## Initial implementation plan

1. Add executable E2E script focused on `sheriff` entrypoint semantics (one-shot, slash, menu/restart/factory-reset).
2. Extend Docker fresh-install E2E to run real `sheriff` one-shot + slash commands.
3. Keep one-shot wait/Esc as manual/interactive validation for now; automate later via PTY harness.

## Progress notes

- 2026-02-21: Task created.
