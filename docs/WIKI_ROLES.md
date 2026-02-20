# SheriffClaw Wiki — LLM and Sheriff Roles

## Mental Model
SheriffClaw has two core actors:

1. **LLM (Agent)** — does the work you ask for.
2. **Sheriff** — enforces boundaries and asks for supervision when needed.

Think of it as **capability + control**:
- LLM = capability
- Sheriff = control

---

## LLM Role (What the Agent Is Responsible For)
The LLM is the execution brain. It:
- interprets user intent
- plans and performs steps
- requests tools/actions (web, shell, secrets, etc.)
- asks for access when blocked
- continues after approvals are resolved

The LLM should **not** be the authority for sensitive access decisions.

---

## Sheriff Role (What the Sheriff Is Responsible For)
The Sheriff is the policy and supervision layer. It:
- decides whether an action is allowed/denied
- validates domains/tools/output disclosure requests
- manages secure secret resolution flow
- keeps approval records and decisions
- acts as the firewall between agent intent and sensitive operations

Sheriff is primarily **agent-triggered**:
- Agent requests something
- Sheriff blocks/asks for approval if needed
- User responds to Sheriff
- Agent proceeds with updated permission state

---

## Design Boundary
### Sheriff channel should be for:
- permission review/approval
- secret resolution responses
- policy responses to agent-triggered requests

### Sheriff channel should not be for:
- routine chat
- general app setup UX
- login/auth provisioning flows

Credential/config setup belongs to explicit setup commands (outside Sheriff chat), while Sheriff remains focused on supervised runtime control.

---

## Why This Separation Matters
This split reduces risk:
- clearer audit trail
- fewer accidental privilege escalations
- easier to reason about trust boundaries
- better long-term maintainability

In short: **the LLM can ask; the Sheriff can allow.**
