# Phase 2F.A.1 — GO / NO-GO Request

## Predecessor markers required

| Marker | File | Required value |
| --- | --- | --- |
| Phase 2F scope | `frontend_design/00_SCOPE.md` | `PHASE2F_FRONTEND_DESIGN_SCOPE_READY` |
| Phase 2F breakdown | `frontend_design/01_PHASE_BREAKDOWN.md` | `PHASE2F_FRONTEND_DESIGN_PHASE_BREAKDOWN_READY` |
| Phase 2F.A.0 task spec | `frontend_design/02_PHASE_2FA0_FRONTEND_INVENTORY_TASK_SPEC.md` | `PHASE2FA0_FRONTEND_INVENTORY_TASK_SPEC_READY` |
| Phase 2F.A.0 safety boundaries | `frontend_design/03_PHASE_2FA0_SAFETY_BOUNDARIES.md` | `PHASE2FA0_FRONTEND_INVENTORY_SAFETY_BOUNDARIES_READY` |
| Phase 2F.A.0 GO/NO-GO request | `frontend_design/04_PHASE_2FA0_GO_NO_GO_REQUEST.md` | `PHASE2FA0_GO_NO_GO_REQUEST_RECORDED` |
| Phase 2F.A.0 inventory pass | `frontend_design/07_FRONTEND_INVENTORY_GO_NO_GO.md` | `PHASE2FA0_FRONTEND_INVENTORY_PASSED` |
| Phase 2F.A.1 task spec | `frontend_design/08_PHASE_2FA1_DESIGN_SPEC_TASK_SPEC.md` | `PHASE2FA1_DESIGN_SPEC_TASK_SPEC_READY` |
| Phase 2F.A.1 safety boundaries | `frontend_design/09_PHASE_2FA1_SAFETY_BOUNDARIES.md` | `PHASE2FA1_DESIGN_SPEC_SAFETY_BOUNDARIES_READY` |

The supervisor MUST NOT dispatch task `067` until every marker file
above contains its required value.

## Dispatch chain

1. `agent_supervisor/tasks/067_frontend_design_2fa1_spec_author.json`
2. `agent_supervisor/tasks/068_frontend_design_2fa1_codex_review.json`

The supervisor executes 067, then 068 only after
`13_2FA1_GO_NO_GO.md` reads `PHASE2FA1_DESIGN_SPEC_PASSED`.

## Stop the chain immediately if

- any predecessor marker file does not contain its required value;
- a forbidden token (`redis`, `aioredis`, `subprocess`, `os.system`,
  `legacy_reference`, `/home/wali/Desktop/AI BOT`, `BINANCE_API_KEY`,
  `BINANCE_API_SECRET`, `live_trading_enabled = true`) is detected
  during self-grep on the authored spec files;
- a write outside `claude_worklog/phase2_core_rebuild/frontend_design/`
  is attempted;
- the 2F.A.0 inventory marker reads `PHASE2FA0_FRONTEND_INVENTORY_BLOCKED`
  (in which case 2F.A.1 must wait for the 2F.A.0 remediation cycle to
  re-pass);
- any Codex finding indicates live behavior, Redis writes, legacy
  mutation, or deployment intent;
- any directive that would weaken or remove the always-visible LIVE
  TRADING: BLOCKED banner contract is observed.

## Live-trading status

LIVE TRADING: BLOCKED. No phase 2F.A.1 artifact may change this.

PHASE2FA1_GO_NO_GO_REQUEST_RECORDED
