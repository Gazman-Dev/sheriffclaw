# Task: Skills Code-First + Agent Sandbox Boundaries (2026-02-21)

Source: user request.

## Scope
- [x] Introduce code-first skill shape: `interface.py` + `implementation.py`
- [x] Add system skill root (`system_skills`) and user skill root (`skills`)
- [x] Prevent user skill override of same-name system skills
- [x] Keep legacy `skill.py` compatibility for migration
- [x] Add worker path sandbox helper for payload paths
- [ ] Wire sheriff-call helper into skills context (future)
- [ ] OS-level runtime sandboxing (separate user/container) (future)
