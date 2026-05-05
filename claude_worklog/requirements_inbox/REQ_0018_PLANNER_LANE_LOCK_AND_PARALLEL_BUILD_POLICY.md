# Requirement 0018 - Planner Lane Lock and Parallel Build Policy

## Objective

Claude must stop drifting into broad infrastructure/scaffold work and must continue building the V2 system in parallel only through approved lanes.

## Prime directive

Until `V2_BACKTEST_AND_PAPER_MVP_READY` exists, every new task must directly advance one of the approved lanes below.

## Approved parallel lanes

### Lane A - Paper / Backtest MVP

Highest priority.

Allowed task categories:
- trainer prediction output MVP
- prediction_id / feature_snapshot_id emission
- confidence attribution output
- orchestrator decision MVP
- risk gateway default-deny MVP
- paper execution ledger MVP
- replay/backtest runner MVP
- paper mode MVP
- shadow-mode readiness

### Lane B - Explainability / Website Visibility

Allowed only when it exposes real system state from Lane A/C/D.

Allowed task categories:
- feature-to-confidence explanation contracts
- symbol selection explanation
- risk decision explanation
- open/close/hedge explanation
- audit timeline UI
- paper/shadow result UI
- trainer health UI
- Codex/Claude/Ollama activity UI
- live-blocked safety UI

Forbidden:
- cosmetic-only website work before data contracts exist
- fake/mock reasoning that is not backed by lineage IDs or real V2 contracts

### Lane C - Codex Watchdog / Quality

Allowed task categories:
- Codex review of latest committed milestone
- Codex autofix for non-live blockers
- test hardening
- safety scans
- stale status/evidence reconciliation
- dispatch bridge fixes
- safe path remap fixes

### Lane D - Legacy Preservation / Parity

Allowed task categories:
- preserve live_coinank.py as-is
- preserve config.py symbol behavior
- preserve GPU trainer assumptions
- preserve feature_pipeline parity
- ingestor adapter parity
- read-only legacy audit

## Forbidden drift

The planner must not create tasks for:
- generic scaffold expansion
- generic architecture docs
- general frontend polish
- new dashboards without real data contracts
- new automation framework work unless required to unblock Lane A/C
- deployment
- live trading
- exchange actions
- Redis writes/deletes
- live service restarts

## Lane selection rule

Every generated task must include:

- `lane`: one of `paper_backtest_mvp`, `explainability_ui`, `codex_watchdog`, `legacy_parity`
- `mvp_relevance`: short explanation of how the task advances paper/backtest MVP
- `blocked_by`: dependencies if any
- `next_gate`: validation/Codex marker expected

If a task cannot name its lane and MVP relevance, it must not be generated.

## Parallelism rule

Claude may build multiple lanes in parallel only if:
- Lane A remains active or unblocked
- no active child process conflict exists
- git is clean before dispatch
- Codex watchdog is active
- live gate remains blocked

## Enforcement

The master planner must refuse tasks outside approved lanes until:

`V2_BACKTEST_AND_PAPER_MVP_READY`

## Final target

The next measurable project target is:

`V2_BACKTEST_AND_PAPER_MVP_READY`

REQ_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY_READY
