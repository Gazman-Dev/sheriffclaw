# Task: Telegram-Simulated Unlock Hardening (2026-02-21)

Source: user request to implement all additional simulated unlock coverage suggestions.

## Scope

Implement and validate via local simulation (no live Telegram dependency):

- [x] Repeated wrong unlock attempts do not emit accepted event
- [x] Policy toggle behavior across boot checks (false -> true)
- [x] No master-password-required prompt when already unlocked
- [x] Gate event ordering (`required` before `accepted`)
- [x] Idempotent unlock behavior on repeated correct submissions
- [x] Principal/state isolation simulation (separate roots)

## Deliverables

- Unit tests where appropriate
- E2E script assertions in scenario runner
- Scenario pass/fail count reporting
