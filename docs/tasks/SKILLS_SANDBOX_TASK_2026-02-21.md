# Task: Skills Code-First + Agent Sandbox Boundaries (2026-02-21)

Source: user request.

## Scope
- [x] Introduce code-first skill shape: `interface.py` + `implementation.py`
- [x] Add system skill root (`system_skills`) and user skill root (`skills`)
- [x] Prevent user skill override of same-name system skills
- [x] Remove legacy `skill.py` fallback (new style only)
- [x] Add worker path sandbox helper for payload paths
- [x] Wire sheriff-call helper into skills context
- [ ] OS-level runtime sandboxing (separate user/container) (future)
