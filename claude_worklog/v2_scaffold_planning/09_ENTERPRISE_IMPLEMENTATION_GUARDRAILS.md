# 09 — Enterprise Implementation Guardrails

## 1) Mandatory fields for every implementation task
Every implementation task MUST include all of the following before execution:
- Architecture reference (exact source documents and sections)
- Required files to create/update
- Safety boundary (what cannot be touched)
- Observability fields (events, metrics, logs)
- Dashboard visibility (where status appears)
- Tests (unit/integration/contract/e2e as applicable)
- Rollback and failure behavior
- Audit evidence output
- GO/NO-GO marker

## 2) No "tiny fix" exceptions
No "tiny fix" is allowed without:
- Timeout handling
- State handling
- Error classification
- Dashboard/reporting implication
- Agent-supervisor implication
- Test/validation artifact

## 3) Mandatory contract block for every new service/module
Every new service/module MUST define:
- Owner component
- Input contracts
- Output contracts
- Failure modes
- Retry behavior
- Idempotency behavior
- Observability events
- Health/heartbeat semantics
- Configuration/hot-reload behavior

## 4) Mandatory definition for every website/admin feature
Every website/admin feature MUST define:
- Public vs admin visibility
- RBAC scope
- Audit logging
- Explanation text
- Approval requirements
- Animation/UX class
- Mobile/iPhone behavior
- Error/empty/loading states

## 5) Mandatory definition for every AI-agent action
Every AI-agent action MUST define:
- L0/L1/L2/L3/L4/L5 level
- Allowed autonomy
- Required approval
- Evidence packet input
- Output artifact
- Rollback plan
- Human-readable explanation

## 6) Legacy bot protection policy
Legacy bot remains:
- Read-only monitored
- Not mutated
- Not restarted
- Not reconfigured
- Not traded through by agents
Unless explicit emergency human approval is provided.

## 7) Claude/Codex/Ollama monitoring model
Operating model is mandatory:
- Local monitor runs 24/7
- Ollama compresses raw evidence
- Claude interprets evidence and plans/builds
- Codex adversarially reviews gates/code/contracts
- Dashboard displays agent state and system state
- Human approves L4/L5

## 8) Enforcement posture
- These guardrails are hard preconditions before any V2 scaffold implementation task enters execution.
- Any task missing required blocks is automatically BLOCKED by supervisor policy.
- Default-deny remains in force for live trading, dangerous runtime mutation, and legacy bot mutation.

ENTERPRISE_IMPLEMENTATION_GUARDRAILS_READY
