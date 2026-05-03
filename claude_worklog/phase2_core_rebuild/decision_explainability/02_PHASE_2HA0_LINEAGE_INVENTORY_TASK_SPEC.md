# Phase 2H.A.0 — Decision-Lineage Inventory and Gap Matrix Task Spec

This is the authoring spec for the local-Claude inventory task that
will produce a chain-by-chain inventory of REQ_0009's explainability
contract against the existing V2 backend domain layer, plus a gap
matrix. Phase 2H.A.0 is documentation only. The implementer MUST NOT
modify any file under `v2/`.

## Predecessor gates

- REQ_0009 in requirements inbox.
- `claude_worklog/phase2_core_rebuild/decision_explainability/00_SCOPE.md`
  ends with `PHASE2H_DECISION_EXPLAINABILITY_SCOPE_READY`.
- `claude_worklog/phase2_core_rebuild/decision_explainability/01_PHASE_BREAKDOWN.md`
  ends with `PHASE2H_DECISION_EXPLAINABILITY_PHASE_BREAKDOWN_READY`.
- `claude_worklog/phase2_core_rebuild/decision_explainability/03_PHASE_2HA0_SAFETY_BOUNDARIES.md`
  ends with `PHASE2HA0_DECISION_LINEAGE_SAFETY_BOUNDARIES_READY`.
- `claude_worklog/phase2_core_rebuild/decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md`
  ends with `PHASE2HA0_GO_NO_GO_REQUEST_RECORDED`.

## Inputs the implementer MUST read

- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/00_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/01_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/03_PHASE_2HA0_SAFETY_BOUNDARIES.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md`
- `CLAUDE.md` (sections: "Signal Explainability Rule", "Required V2
  GUI Pages", "Monitor Center Requirements", "Admin Control Rule",
  "Evidence Integrity Rule").
- every file under `v2/backend/app/domain/predictions/` (read-only)
- every file under `v2/backend/app/domain/decisions/` (read-only)
- every file under `v2/backend/app/domain/signals/` (read-only)
- every file under `v2/backend/app/domain/risk/` (read-only)
- every file under `v2/backend/app/domain/traders/` (read-only)
- every file under `v2/backend/app/domain/lineage/` (read-only)
- every file under `v2/backend/app/domain/governance/` (read-only)
- every file under `v2/backend/app/domain/execution/` (read-only)
- every file under `v2/backend/app/domain/monitor/` (read-only)
- every file under `v2/backend/app/domain/symbols/` (read-only)
- every file under `v2/backend/app/domain/features/` (read-only)
- every file under `v2/backend/app/domain/trainer_parity/` (read-only)
- every file under `v2/backend/app/domain/trainer_liveness/` (read-only)
- every file under `v2/backend/app/domain/universe/` (read-only)
- every file under `v2/backend/app/domain/connectors/` (read-only)
- every file under `v2/backend/app/domain/replay/` (read-only)
- every file under `v2/backend/app/domain/hot_reload/` (read-only)

## Outputs the implementer MUST author (exact set, no extras)

- `claude_worklog/phase2_core_rebuild/decision_explainability/05_DECISION_LINEAGE_INVENTORY_REPORT.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/06_DECISION_LINEAGE_GAP_MATRIX.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/07_DECISION_LINEAGE_GO_NO_GO.md`

The implementer authors these via `Write` (or BEGIN_FILE/END_FILE
blocks since the harness Markdown materialization is safe). The
implementer MUST NOT author any Python/TypeScript file under `v2/`.

## 05_DECISION_LINEAGE_INVENTORY_REPORT.md required structure

1. Heading "Phase 2H.A.0 — Decision-Lineage Inventory Report".
2. Section "Source authority" — cite REQ_0009 + CLAUDE.md sections.
3. Section "Per-stage chain inventory". One subsection per chain stage
   listed below. For each subsection, record: stage name, owning V2
   domain module(s) (path), exported types/classes/functions in that
   module that participate in the stage, what id the stage MUST mint
   or forward (e.g. `feature_snapshot_id`, `prediction_id`,
   `signal_id`, `decision_id`, `risk_decision_id`,
   `execution_intent_id`), what reason text or freshness flag the
   stage MUST surface, and an EVIDENCE pointer (file path + symbol
   name) for each claim. If a stage has no current code owner, mark
   it as "GAP — no V2 module owns this stage" and record under what
   sub-phase it would be authored. Stages (in order):
   - raw source data
   - feature snapshot construction
   - feature change detection
   - trainer prediction emission
   - confidence change packaging
   - signal emission
   - orchestrator decision
   - risk gateway decision
   - execution intent issuance
   - paper trader action
   - shadow trader action
   - live-blocked trader action
   - result / PnL attribution
4. Section "ID forwarding contract". Table with columns:
   id-name, minting module (path), forwarding modules (paths),
   persisting module (path), evidence pointer.
5. Section "Confidence-delta explanation source survey". For each of
   the elements REQ_0009 requires (previous confidence, new
   confidence, delta, contributing feature deltas, positive
   contributors, negative contributors, source freshness, regime
   context, model/checkpoint version, data-quality impact), record
   whether a current V2 module owns the element, the path, and the
   evidence pointer or "GAP".
6. Section "Symbol-state-change explanation source survey" (same
   structure, elements per REQ_0009).
7. Section "Risk-decision explanation source survey" (same structure).
8. Section "Trade open/close/hedge/block explanation source survey"
   (same structure).
9. Section "Audit-timeline source survey". Identify the current
   write-path for explanation records (or mark as GAP). Reference
   `v2/backend/app/domain/governance/audit_chain.py` if present.
10. Section "Read scope evidence ledger". For every file the
    implementer read, record path + sha256 or first-line excerpt
    proving it was read (this satisfies the CLAUDE.md "Evidence
    Integrity Rule" for inventory work).
11. Section "Forbidden-token grep results". One row per token in the
    forbidden-token list defined in Step 5 below; raw count and
    matching lines if any.
12. Final marker line MUST be exactly one of:
    - `PHASE2HA0_DECISION_LINEAGE_INVENTORY_REPORT_READY`
    - `PHASE2HA0_DECISION_LINEAGE_INVENTORY_BLOCKED`

## 06_DECISION_LINEAGE_GAP_MATRIX.md required structure

1. Heading "Phase 2H.A.0 — Decision-Lineage Gap Matrix".
2. Table A — Chain-stage gaps. Columns: stage, current owner module
   or "—", gap description, severity (P0 blocks frontend
   explainability page / P1 blocks audit-timeline UI / P2 polish),
   proposed owner sub-phase (e.g. 2H.B.1, 2H.B.2, 2H.B.3, 2H.B.4,
   2H.B.5).
3. Table B — ID-forwarding gaps. Columns: id-name, missing modules
   that should forward or persist, severity, proposed owner sub-phase.
4. Table C — Confidence-delta element gaps. Columns: element name,
   missing source, severity, proposed owner sub-phase.
5. Table D — Symbol-state-change element gaps. Same columns as C.
6. Table E — Risk-decision element gaps. Same columns as C.
7. Table F — Trade open/close/hedge/block element gaps. Same columns
   as C.
8. Table G — Audit-timeline gaps. Columns: requirement, current
   coverage, severity, proposed owner sub-phase.
9. Section "Cross-cutting concerns". Note any gaps that span more
   than one chain (e.g. missing `decision_id` minting that affects
   risk + execution + audit simultaneously).
10. Section "Suggested 2H.A.1 / 2H.A.2 / 2H.A.3 spec scope" —
    distill the gap matrix into the three follow-up documentation
    sub-phases per the Phase 2H breakdown.
11. Final marker line MUST be exactly one of:
    - `PHASE2HA0_DECISION_LINEAGE_GAP_MATRIX_READY`
    - `PHASE2HA0_DECISION_LINEAGE_INVENTORY_BLOCKED`

## 07_DECISION_LINEAGE_GO_NO_GO.md required structure

Exactly one line, no other content:

- `PHASE2HA0_DECISION_LINEAGE_INVENTORY_PASSED`
  — produced only when all of: 05 ends with
  `PHASE2HA0_DECISION_LINEAGE_INVENTORY_REPORT_READY`, 06 ends with
  `PHASE2HA0_DECISION_LINEAGE_GAP_MATRIX_READY`, and the forbidden-
  token grep across the entire `claude_worklog/phase2_core_rebuild/
  decision_explainability/` subtree returns zero hits for every
  token below.
- `PHASE2HA0_DECISION_LINEAGE_INVENTORY_BLOCKED`
  — otherwise.

## Forbidden-token list (case-sensitive unless noted)

`redis`, `aioredis`, `redis.asyncio`, `subprocess`, `os.system`,
`os.popen`, `pty`, `socket`, `urllib`, `requests`, `httpx`, `aiohttp`,
`torch`, `tensorflow`, `numpy`, `cuda`, `legacy_reference`,
`/home/wali/Desktop/AI BOT`, `BINANCE_API_KEY`, `BINANCE_API_SECRET`,
`live_trading_enabled = true`, `XLEN`, `xlen`, `time.time(`,
`datetime.now(`, `datetime.utcnow(`.

A non-zero count for any token is a hard fail and the implementer
MUST emit `PHASE2HA0_DECISION_LINEAGE_INVENTORY_BLOCKED`.

PHASE2HA0_DECISION_LINEAGE_INVENTORY_TASK_SPEC_READY
