# Task: Updater Service + Update E2E (2026-02-21)

Source: user request for simple/password-based updater orchestration via sheriff.

## Scope

- [x] Add dedicated updater service (`sheriff-updater`)
- [x] Route `sheriff-ctl update` through updater service
- [x] Use master password argument (`--master-password`) with in-memory pass-through
- [x] Stop services before update, start after update
- [x] Add unit tests for updater service
- [x] Add E2E update flow test
- [ ] Add cron/launchd auto-update wrappers (next)
