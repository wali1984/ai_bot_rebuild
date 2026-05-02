```
# Phase 2E Trainer GPU Parity Rebuild Plan Scope

Phase 2E opens the non-live planning surface required before any V2 trainer
parity service is scaffolded. This phase produces only planning, evidence, and
contract documents. No trainer code is written or executed. No Redis state is
modified. No live services are restarted. No exchange-side actions are
proposed.

## Goal

Reconstruct the legacy hybrid trainer behavior from atlas evidence, document
the GPU / batching / checkpoint preservation rules, specify the prediction
worker liveness fix, define the trainer output and lineage contract, and
specify the subprocess boundary that V2 must use to call the legacy trainer
runtime.

## In scope (this phase, planning only)

- Behavior inventory grounded in `claude_worklog/trainer_atlas/`.
- GPU and batching parity requirements.
- Checkpoint and model loading parity rules.
- Reward and confidence parity map referencing atlas paths.
- Prediction worker liveness fix specification (process-alive / worker-dead).
- Trainer output and lineage contract aligned to
  `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md` and
  `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`.
- Process boundary and subprocess adapter specification.
- Non-live validation plan (replay / paper / shadow only).
- Codex review of this plan.

## Out of scope (this phase)

- Any executable V2 trainer code.
- Any modification of `legacy_reference/**`.
- Any modification of `/home/wali/Desktop/AI BOT`.
- No Redis-state modifications (no writes, no entry removals, no namespace
  clears) — see CLAUDE.md write boundaries.
- No restart of the legacy trainer or any other live service.
- No exchange order submission or cancel — see CLAUDE.md hard stops.
- No leverage configuration change or margin-mode configuration change — see
  CLAUDE.md hard stops.
- No switch from non-live to live mode — CLAUDE.md default operational
  status remains LIVE TRADING: BLOCKED.
- Any deployment or production migration.
- Any change to `v2/legacy_preserved/ingestors/live_coinank.py`.
- Any change to `legacy_reference/feature_pipeline.py`.

## Safety boundaries

- Read-only against `legacy_reference/**` and `/home/wali/Desktop/AI BOT`.
- All artifacts written under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/`
  and `claude_worklog/agent_supervisor/tasks/`.
- No secrets included.
- No `.env` files modified.

## Inputs of record

- `claude_worklog/trainer_atlas/HYBRID_TRAINER_ATLAS.md`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_COVERAGE_REPORT.md`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_REWARD_PATHS.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_CONFIDENCE_PATHS.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_SIGNAL_PATHS.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_FEATURE_PATHS.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_CHECKPOINT_PATHS.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_USAGE.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_REDIS_WRITE_CLASSIFICATION.md`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_RUNTIME_ENTRYPOINTS.json`
- `claude_worklog/trainer_atlas/HYBRID_TRAINER_TIER_A_REVIEW_PLAN.md`
- `claude_worklog/trainer_atlas/TRAINER_SIZE_RECONCILIATION.md`
- `claude_worklog/legacy_preservation/03_TRAINER_TRADER_PARITY_REQUIREMENTS.md`
- `claude_worklog/v2_requirements/09_TRAINER_INTERNAL_WORKER_SUPERVISION_REQUIREMENT.md`
- `claude_worklog/v2_requirements/02_FEATURE_SNAPSHOT_SCHEMA.md`
- `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md`
- `claude_worklog/phase2_core_rebuild/legacy_service_map/06_TRAINER_ORCHESTRATOR_TRADER_MAP.md`
- `claude_worklog/phase2_core_rebuild/feature_snapshots/04_TRAINER_INPUT_CONTRACT.md`
- `claude_worklog/requirements_inbox/REQ_0004_TRAINER_GPU_PARITY.md`
- `CLAUDE.md`

PHASE2_TRAINER_GPU_PARITY_SCOPE_READY
```
