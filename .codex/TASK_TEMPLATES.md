# Task Templates For Future Codex Sessions

## 1) Bug Fix

Use this prompt:
`Investigate and fix <bug>. Keep changes minimal, add regression tests, and run relevant pytest targets. Report root cause, patch, and verification.`

## 2) New Service Operation

Use this prompt:
`Add operation <op_name> to <service>. Update caller(s), keep protocol compatibility, add tests for success and failure paths, and document the new contract.`

## 3) Security Hardening

Use this prompt:
`Harden <component> against <threat>. Prioritize deny-by-default behavior, add tests for blocked scenarios, and explain any compatibility tradeoffs.`

## 4) CLI Improvement

Use this prompt:
`Improve sheriff-ctl <command/flow>. Keep UX deterministic, preserve existing flags unless explicitly deprecated, and update CLI tests.`

## 5) Skill Addition

Use this prompt:
`Add a new skill <skill_id> under skills/. Include manifest.json, runnable entry if needed, loader compatibility, and tests for discovery/routing.`

## 6) Refactor With Safety

Use this prompt:
`Refactor <module> for readability/maintainability without behavior change. Prove parity with existing tests and add targeted tests for edge cases.`
