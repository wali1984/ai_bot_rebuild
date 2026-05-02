# Phase 2E1 Trainer Parity Service Implementation — Scope

Phase 2E (planning) closed with
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/19_CODEX_GO_NO_GO_RERUN2.md`
=> `PHASE2_TRAINER_GPU_PARITY_PLAN_CODEX_RERUN2_PASS`.

REQ_0006 (`claude_worklog/requirements_inbox/REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`)
opens the executable surface for V2 trainer parity. Phase 2E1 is the
implementation phase. This scope binds Phase 2E1 to the contracts already
ratified by Phase 2E and breaks Phase 2E1 into four Codex-gated sub-phases
so no large blast radius lands behind a single review.

## Sub-phase breakdown

- Phase 2E1.A — Subprocess adapter foundation. Implements
  `v2/backend/app/adapters/trainer/subprocess_adapter.py`,
  `modes.py`, `audit_emitter.py`, `errors.py`, plus unit tests.
  Subprocess boundary only. Argv vocabulary restricted to
  `read_only|status|export`. No legacy trainer module is imported into
  the FastAPI process. No legacy trainer is actually spawned in tests
  (an injected runner double is used). No Redis touch.
- Phase 2E1.B — Trainer output contract dataclasses and validators.
  Implements V2-side Stage A and Stage B record shapes plus integrity
  validators that enforce the lineage tuple from
  `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`
  and the full legacy-preservation explainability field set bound by
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/04_REWARD_AND_CONFIDENCE_PARITY_MAP.md`.
- Phase 2E1.C — Prediction worker liveness monitor (read-only).
  Implements the V2-side liveness ingestion and alert-shape per
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/05_PREDICTION_WORKER_LIVENESS_FIX_SPEC.md`.
  No Redis writes. Alert shape is constructed but is delivered to a
  pluggable sink (in-memory fake in tests). No legacy Redis ingestion
  yet — only the contract and signal envelope. Real read-only Redis
  observation is gated to a follow-on phase.
- Phase 2E1.D — Trainer parity service composition. Wires the adapter,
  the contract validators, and the liveness sink into a single service
  module with an explicit non-live mode flag and integration tests.

This document only opens Phase 2E1 and authorizes the dispatch of
Phase 2E1.A. Phase 2E1.B, C, and D each require a separate planner
cycle and a separate Codex review pass.

## In scope (this scope document only)

- Authorize Phase 2E1.A implementation under
  `v2/backend/app/adapters/trainer/` and tests under
  `v2/backend/tests/unit/adapters/trainer/`.
- Enqueue supervisor tasks `053` (Claude implementation) and `054`
  (Codex review of `053` outputs).
- Bind every Phase 2E1.A safety boundary to the Phase 2E plan
  contracts already Codex-passed.

## Out of scope (this scope document)

- Any Phase 2E1.B / 2E1.C / 2E1.D implementation work.
- Any modification of `legacy_reference/**`.
- Any access to `/home/wali/Desktop/AI BOT`.
- Any Redis-state modification.
- Any Redis-state observation that touches the legacy bot — a future
  phase opens the read-only legacy Redis observation surface.
- Any restart of legacy services.
- Any exchange-side action.
- Any leverage- or margin-config-write action.
- Any switch from non-live to live mode.
- Any deployment or production migration.
- Any legacy trainer process actually being spawned by the V2 process
  in tests; tests use an injected fake runner.
- Any change to `v2/legacy_preserved/ingestors/live_coinank.py`.
- Any change to `legacy_reference/feature_pipeline.py`.

## Inputs of record (Phase 2E1.A)

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/00_SCOPE.md`
  through `09_GO_NO_GO.md` (Phase 2E plan, Codex rerun2 PASS).
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/07_PROCESS_BOUNDARY_AND_SUBPROCESS_ADAPTER_SPEC.md`.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/06_TRAINER_OUTPUT_CONTRACT_AND_LINEAGE_IDS.md`.
- `claude_worklog/legacy_preservation/03_TRAINER_TRADER_PARITY_REQUIREMENTS.md`.
- `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`.
- `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`.
- `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`.
- `claude_worklog/requirements_inbox/REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md`.
- `CLAUDE.md`.

PHASE2E1_TRAINER_PARITY_IMPL_SCOPE_READY
