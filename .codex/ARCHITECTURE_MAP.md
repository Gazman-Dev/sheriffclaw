# Architecture Map

## Service Topology

- Sheriff control/orchestration:
- `services/sheriff_ctl/*`
- Core Sheriff services:
- `sheriff-secrets`
- `sheriff-policy`
- `sheriff-requests`
- `sheriff-web`
- `sheriff-tools`
- `sheriff-gateway`
- `sheriff-tg-gate`
- `sheriff-cli-gate`
- `sheriff-updater`
- Agent side:
- `ai-worker`
- `ai-tg-llm`
- `telegram-listener`
- Optional adapter:
- `telegram-webhook`

## Shared Primitives

- RPC framing/client: `shared/proc_rpc.py`, `shared/ndjson.py`, `shared/service_base.py`
- Service lifecycle: `shared/service_manager.py`
- Secrets state: `shared/secrets_state.py`, crypto in `shared/crypto.py`
- Policy/approvals: `shared/policy.py`, `shared/permissions_store.py`, `shared/approvals.py`
- Tool execution: `shared/tools_exec.py`
- Memory/runtime: `shared/memory/*`, `shared/worker/worker_runtime.py`
- LLM providers: `shared/llm/providers.py`

## Important Control Flows

- User input -> CLI/Telegram gate -> `sheriff-gateway` -> worker/tool/request services.
- Secret/tool/domain approvals -> `sheriff-requests` and policy services -> persisted decisions.
- Vault unlock:
- driven by master password verification in secrets service/state.
- Update flow:
- `sheriff-ctl update` -> updater plan/run -> optional restart/unlock based on version deltas.

## Skills Model

- Skills live under `skills/<skill_id>/`.
- Contract expects `manifest.json` (and `run.py` when executable).
- Loader logic: `shared/skills/loader.py`.

## Test Surface (Representative)

- CLI and control logic: `tests/test_ctl_*.py`
- Gateway and approvals: `tests/test_gateway_*.py`, `tests/test_policy*.py`, `tests/test_requests_service.py`
- Secrets and security: `tests/test_secrets_*.py`, `tests/test_secure_web.py`, `tests/test_tools_exec.py`
- Worker/runtime/memory: `tests/test_worker_*.py`, `tests/test_memory*.py`
- Skills: `tests/test_skills_contract.py`, `tests/test_skill_loader_sandbox.py`, `tests/test_skill_routing_phase3.py`
