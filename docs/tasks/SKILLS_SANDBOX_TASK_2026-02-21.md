# Task: Skills Code-First + Agent Sandbox Boundaries (2026-02-21)

Source: user request.

## Scope
- [x] Introduce code-first skill shape: `interface.py` + `implementation.py`
- [x] Add system skill root (`system_skills`) and user skill root (`skills`)
- [x] Prevent user skill override of same-name system skills
- [x] Remove legacy `skill.py` fallback (new style only)
- [x] Add worker path sandbox helper for payload paths
- [x] Wire sheriff-call helper into skills context
- [x] Add platform sandbox wrapper for ai-worker process launch (Darwin `sandbox-exec`)
- [x] Add Linux sandbox wrapper for ai-worker launch (`bwrap` when available)
- [ ] OS-level runtime sandboxing (separate user/container/jail) (future hardening)
