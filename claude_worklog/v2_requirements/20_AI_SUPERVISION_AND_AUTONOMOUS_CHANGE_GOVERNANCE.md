# AI Supervision and Autonomous Change Governance

## Requirement ID
V2-AI-SUPERVISION-GOVERNANCE-001

## Scope
Claude Code, Codex, and Ollama are used for:
- continuous monitoring review
- issue detection
- root-cause analysis
- code/spec generation
- validation
- recommendations
- safe self-healing proposals

But changes must be governed by risk level.

## Action levels (mandatory)

### Level 0 — observe only
- read logs
- read Redis
- read monitor packets
- summarize evidence
- no mutation

### Level 1 — safe documentation/report updates
- write audit reports
- update evidence packets
- update dashboards/reports in rebuild workspace

### Level 2 — safe V2 non-live config changes
- change UI preferences
- change dashboard thresholds
- change monitor display config
- requires audit log

### Level 3 — operational non-trading changes
- restart monitor
- rotate logs
- regenerate evidence packets
- must be approved or policy-preapproved

### Level 4 — trading-impacting changes
- symbol train/trade eligibility
- confidence thresholds
- strategy config
- risk limits
- trader assignment
- requires staged change + validation + human approval

### Level 5 — dangerous live changes
- enable live trading
- increase leverage
- enable cross margin
- change margin mode
- increase position size
- disable stops
- disable kill switch
- place/cancel live orders
- must never be autonomous
- human approval required

## Mandatory AI change ledger schema
Every AI action/change must have:
- change_id
- actor: Claude/Codex/Ollama/human/system
- reason
- evidence pointers
- before value
- after value
- risk level
- validation result
- rollback plan
- GUI explanation
- timestamp
- approval state

## GUI requirement (mandatory)
Admin page must show every AI recommendation/action.
User must see:
- what was wrong
- why AI proposed action
- what evidence it used
- what it changed
- expected effect
- rollback option
- validation result

## Role-specific policy
### Ollama policy
- local summarization only
- never final authority
- cannot approve risk/live changes

### Claude policy
- can propose fixes
- can generate code/specs
- can apply safe rebuild changes
- cannot autonomously approve dangerous live actions

### Codex policy
- adversarial reviewer
- schema/code correctness
- can block changes if evidence incomplete

## Governance and safety constraints
- Risk level must be computed and attached before any mutation attempt.
- Level 4 and 5 changes require explicit human approval workflows.
- Level 5 actions are permanently non-autonomous by policy.
- All actions must be auditable and rollback-capable.

## Pre-architecture acceptance
- Action-level matrix (L0-L5) is locked and enforceable.
- AI change ledger schema is included in core governance baseline.
- GUI transparency and approval workflow requirements are complete.
