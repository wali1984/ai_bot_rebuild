# 06 AI Governance and Autonomy Review

## Scope
Verify Claude/Codex/Ollama supervision and L0–L5 action governance are complete and binding.

## Inputs
- Architecture: 06, 13, 14
- Requirements: 20

## L0–L5 levels
Architecture file 13 lists all six levels:
- L0 observe
- L1 docs/reports
- L2 safe V2 non-live config
- L3 operational non-trading
- L4 trading-impacting changes
- L5 dangerous live changes

Requirement 20 defines each level with explicit examples and policy. The level set matches.

## Mandatory AI change ledger fields
Required:
- `change_id`
- `actor` (Claude/Codex/Ollama/human/system)
- `reason`
- `evidence_pointers`
- `before_value`
- `after_value`
- `risk_level`
- `validation_result`
- `rollback_plan`
- `gui_explanation`
- `timestamp`
- `approval_state`

Architecture file 13 lists all 12 fields. Database schema 03 persists them via `ai_action_changes` (`change_id`, `actor`, `risk_level`, `reason`, `evidence_pointers_json`, `before_value_json`, `after_value_json`, `validation_result`, `rollback_plan`, `gui_explanation`, `approval_state`, `created_ts_ms`).

## Non-autonomous L5 hard rule
- Architecture 13: "Level 5 is never autonomous."
- Requirement 20: "Level 5 actions are permanently non-autonomous by policy."
- Architecture 06 binds this to GUI via AI Governance Console with mandatory human approval for dangerous levels.

## Role-specific policies
Requirement 20 specifies:
- Ollama: local summarization only; cannot approve risk/live changes.
- Claude: can propose fixes, generate code/specs, apply safe rebuild changes; cannot autonomously approve dangerous live actions.
- Codex: adversarial reviewer; can block changes if evidence incomplete.

These boundaries are reflected in architecture 13 and 14 (review packet types: Claude/Codex/Ollama).

## GUI transparency
Required GUI fields per requirement 20 ("what was wrong / why proposed / evidence used / what changed / expected effect / rollback / validation result"):
- AI Governance Console page (file 06 + requirement 16) requires every AI recommendation/action with `change_id`, actor, reason, evidence pointers, before/after, risk level, validation result, rollback plan, timestamp, approval state.
- Claude/Codex/Ollama Review Center extension (requirement 16) requires the explicit seven-bullet display.
- Both pages bind to `ai_action_changes` and `evidence_packets` stores.

## Safety constraints
- Risk level must be computed and attached before any mutation attempt — covered by `ai_action_changes.risk_level` non-null requirement.
- L4 and L5 require explicit human approval workflows — encoded via `approvals` table (03).
- All actions auditable and rollback-capable — encoded via `audit_events` + `rollback_plan` field.

## Verdict
AI governance is complete: L0–L5 matrix is locked, ledger schema is persisted, GUI transparency is bound to real APIs, L5 is permanently non-autonomous.
