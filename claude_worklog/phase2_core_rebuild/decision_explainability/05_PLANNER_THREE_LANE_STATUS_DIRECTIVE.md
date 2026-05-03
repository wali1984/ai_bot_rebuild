# Planner Directive — Three-Lane Status as of 2026-05-03

This is a Master Non-Live Rebuild Planner directive. It does not
execute code, write Redis, restart live services, or modify legacy. It
records the verified state of the three parallel non-live rebuild
lanes (REQ_0006, REQ_0008, REQ_0009) and orders the agent_supervisor
to dispatch only what is currently safe.

## Source of authority

- Active requirement set:
  - `claude_worklog/requirements_inbox/REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`
  - `claude_worklog/requirements_inbox/REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM.md`
  - `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`
- Allowed-write boundaries: `v2/`, `claude_worklog/`,
  `requirements/`, `.claude/`, `tools/`, `ollama/`, `raw_evidence/`
  (per CLAUDE.md "Read/Write Boundaries").
- Planner output policy: BEGIN_FILE / END_FILE blocks only; the
  harness materializes files. The planner does NOT itself run pytest,
  py_compile, rg, or import the V2 packages.
- Task granularity profile: Claude Code Max20 consolidated_default
  (per `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`).

## Lane A — REQ_0006 trainer parity (2E1.C.α validation chain)

Verified state (read at planner turn time):

| Artifact | Path | Verified value |
| --- | --- | --- |
| Alpha implementation report | `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/47_2E1C_ALPHA_IMPLEMENTATION_REPORT.md` | begins with `PHASE2E1C_ALPHA_IMPLEMENTATION_REPORT_READY` |
| Alpha implementation GO/NO-GO | `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/46_2E1C_ALPHA_GO_NO_GO.md` | `PHASE2E1C_ALPHA_TRAINER_LIVENESS_READY_FOR_LOCAL_VALIDATION` |
| Alpha source package | `v2/backend/app/domain/trainer_liveness/` | 6 files present |
| Alpha test package | `v2/backend/tests/unit/domain/trainer_liveness/` | 11 files present |
| Validation marker | `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/48_2E1C_ALPHA_VALIDATION_GO_NO_GO.md` | absent |
| Codex review markers | `…/50_2E1C_ALPHA_CODEX_REVIEW.md`, `…/51_2E1C_ALPHA_CODEX_GO_NO_GO.md` | absent |
| Beta specs | `…/52`–`…/55` | present, not yet dispatched |
| Beta tasks | `agent_supervisor/tasks/064`–`066` | defined, not yet dispatched |

The supervisor next action for Lane A is unchanged from
`trainer_gpu_parity_impl/70_PLANNER_2E1C_ALPHA_VALIDATION_DISPATCH_DIRECTIVE.md`:
dispatch `061_trainer_parity_2e1c_alpha_local_validation`. This
planner turn does NOT redefine that chain.

## Lane B — REQ_0008 frontend design (2F.A.0 inventory)

Verified state (read at planner turn time):

| Artifact | Path | Verified value |
| --- | --- | --- |
| Phase 2F scope | `claude_worklog/phase2_core_rebuild/frontend_design/00_SCOPE.md` | `PHASE2F_FRONTEND_DESIGN_SCOPE_READY` |
| Phase 2F breakdown | `…/01_PHASE_BREAKDOWN.md` | `PHASE2F_FRONTEND_DESIGN_PHASE_BREAKDOWN_READY` |
| Phase 2F.A.0 task spec | `…/02_PHASE_2FA0_FRONTEND_INVENTORY_TASK_SPEC.md` | `PHASE2FA0_FRONTEND_INVENTORY_TASK_SPEC_READY` |
| Phase 2F.A.0 safety boundaries | `…/03_PHASE_2FA0_SAFETY_BOUNDARIES.md` | `PHASE2FA0_FRONTEND_INVENTORY_SAFETY_BOUNDARIES_READY` |
| Phase 2F.A.0 GO request | `…/04_PHASE_2FA0_GO_NO_GO_REQUEST.md` | `PHASE2FA0_GO_NO_GO_REQUEST_RECORDED` |
| Manual Claude Design brief | `…/05_CLAUDE_DESIGN_SESSION_BRIEF.md` | present (occupies slot 05) |
| Manual Claude Design output | `…/06_CLAUDE_DESIGN_OUTPUT.md` | `CLAUDE_DESIGN_OUTPUT_PENDING` (manual session not yet completed) |
| Manual handoff status | `…/CLAUDE_DESIGN_HANDOFF_STATUS.md` | `CLAUDE_DESIGN_HANDOFF_READY` |
| Automated 2F.A.0 task | `agent_supervisor/tasks/063_frontend_design_2fa0_inventory.json` | `pending`, requires output to slots `05_FRONTEND_INVENTORY_REPORT.md`, `06_FRONTEND_INVENTORY_GAP_MATRIX.md`, `07_FRONTEND_INVENTORY_GO_NO_GO.md` |
| 2F.A.1 spec author task | `agent_supervisor/tasks/067_frontend_design_2fa1_spec_author.json` | `pending`, predecessor marker `PHASE2FA0_FRONTEND_INVENTORY_PASSED` not present |
| 2F.A.1 Codex review task | `agent_supervisor/tasks/068_frontend_design_2fa1_codex_review.json` | `pending`, predecessor marker `PHASE2FA1_DESIGN_SPEC_PASSED` not present |

Diagnosis: the manual Claude Design handoff occupies slots 05 and 06
that the automated task 063 expects to author. Dispatching 063 as
defined would require overwriting two human-curated handoff documents.
That is a destructive action with potential loss of human-prepared
content; it is therefore OUT OF planner unilateral authority per
CLAUDE.md "Executing actions with care".

Planner directive for Lane B (this turn):

- The agent_supervisor MUST NOT dispatch
  `063_frontend_design_2fa0_inventory.json` until the slot conflict
  is resolved.
- Resolution requires a human decision between two safe paths:
  - Path B1: human-driven completion of the manual Claude Design
    session, after which the manual output replaces the automated
    inventory and a planner re-spec turn redirects 067/068 to
    consume the manual artifacts.
  - Path B2: human-approved archival of `05_CLAUDE_DESIGN_SESSION_BRIEF.md`
    and `06_CLAUDE_DESIGN_OUTPUT.md` into a new
    `frontend_design/manual_handoff_archive/` subdirectory, after
    which the supervisor dispatches 063 as defined and the existing
    067/068 chain proceeds unchanged.
- Until the conflict is resolved, the Lane B downstream tasks
  `067` and `068` remain blocked. The planner does NOT advance Lane
  B this turn.
- This blocker is RECORDED for the `claude_worklog/agent_supervisor/AUTONOMOUS_AGENT_HANDOFF_STATUS.md`
  human-attention queue (the supervisor SHOULD surface a
  `human_attention_required` event with reason `lane_b_2fa0_slot_conflict`).

## Lane C — REQ_0009 decision explainability (2H.A.0 inventory) — opened this turn

Authored this planner turn:

- `claude_worklog/phase2_core_rebuild/decision_explainability/00_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/01_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/02_PHASE_2HA0_LINEAGE_INVENTORY_TASK_SPEC.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/03_PHASE_2HA0_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md`
- `agent_supervisor/tasks/069_decision_explainability_2ha0_lineage_inventory.json`
- `agent_supervisor/tasks/070_decision_explainability_2ha0_codex_review.json`

Supervisor next action for Lane C: dispatch
`069_decision_explainability_2ha0_lineage_inventory` once
`04_PHASE_2HA0_GO_NO_GO_REQUEST.md` materializes with the
`PHASE2HA0_GO_NO_GO_REQUEST_RECORDED` marker (it is authored above).

On
`07_DECISION_LINEAGE_GO_NO_GO.md` =
`PHASE2HA0_DECISION_LINEAGE_INVENTORY_PASSED`,
dispatch `070_decision_explainability_2ha0_codex_review`.

## Combined dispatch order (this planner turn)

The agent_supervisor SHOULD execute, in any order, the two
non-blocked lanes:

1. Lane A — `061` → `062` per the existing planner directive.
2. Lane C — `069` → `070` per this planner turn's outputs.

Lane B remains blocked pending human reconciliation.

## Stop conditions (planner-binding)

The supervisor MUST halt either active lane and surface to the
planner if any of:

- any FAIL marker is written by `061`/`062`/`069`/`070`;
- any forbidden-token hit (the per-lane lists are defined in each
  lane's task spec);
- any `END_FILE: <path>` marker leak inside any authored Python or
  Markdown file (the 2E1.B regression class);
- any write attempt outside the per-task `allowed_output_prefixes`;
- any L4/L5 escalation, live/legacy/Redis/exchange/deploy/secrets
  attempt, or Codex hard fail with no safe remediation.

## Live-trading status

LIVE TRADING: BLOCKED. No artifact in this directive may change this.

PHASE2H_THREE_LANE_STATUS_DIRECTIVE_RECORDED
