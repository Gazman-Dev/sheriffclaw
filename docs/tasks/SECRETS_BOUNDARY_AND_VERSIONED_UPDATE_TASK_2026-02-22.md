# Secrets boundary + versioned update refactor (2026-02-22)

## User request (verbatim intent)
- Master password / secrets service / update mechanism are not working well.
- Refactor into three projects/components: **agent**, **sheriff**, **secrets**.
- Only the **sheriff** service should talk to **secrets** service.
- Secrets service should keep master password in memory.
- Introduce versions for all three components and skip update when versions are not increased.
- Support force update to override skip behavior.
- Only updates to **secrets** should require re-entering master password.

## Plan
1. Add explicit component version manifest (`agent`, `sheriff`, `secrets`).
2. Add update planner that compares target versions with last-applied versions.
3. Update flow behavior:
   - skip by default when no version increase
   - allow `--force`
   - only request/verify master password when `secrets` version increases
4. Start enforcing secrets boundary by routing verification via sheriff service.
5. Migrate remaining services away from direct `sheriff-secrets` access (phased).

## Completed in this iteration
- Added `versions.json` with component versions.
- Added shared version diff/persistence helpers (`shared/component_versions.py`).
- Updated `sheriff-updater`:
  - new `updater.plan`
  - `updater.run` now skips when versions are not increased
  - supports force update
  - persists applied component versions in `~/.sheriffclaw/gw/state/update_versions.json`
  - master password is only required when secrets version increases
- Updated `sheriff-ctl update`:
  - consults `updater.plan` first
  - prompts for master password only when needed
  - added `--force` flag
- Added gateway proxy op `gateway.verify_master_password` and switched CLI verification to gateway path.

## Remaining work
- Enforce strict boundary for *all* services (currently many services still call `sheriff-secrets` directly).
- Add gateway-owned secret proxy ops and migrate clients (`telegram_*`, `ai_tg_llm`, `sheriff_requests`, `sheriff_tg_gate`, `sheriff_web`, etc.).
- Add tests:
  - update skip when versions unchanged
  - force update path
  - secrets-version bump requires password
  - non-secrets bump does not require password
- Define operational release process for bumping only relevant component versions.
- Consider signing/version provenance for safer update decisions.
