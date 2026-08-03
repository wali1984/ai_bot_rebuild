# API Contracts

Last verified timestamp: 2026-07-07T08:04:31Z

## Purpose
Define backend API contracts consumed by the website and iOS app, including paper session, governor, A+ rows, REDUCE_SIZE rows, live gate, and stale flags.

## Source Files
- `v2/backend/app/main.py`
- `v2/backend/app/api/v1/paper.py`
- `v2/backend/app/api/v1/derivatives.py`
- `v2/backend/app/api/v2/market_contracts.py`
- `v2/backend/app/api/v2/live_readiness.py`
- `v2/backend/app/api/v2/mobile.py`
- `v2/backend/app/cli/v2_trade_management_paper_loop.py`
- `v2/backend/app/cli/v2_runtime_drift_monitor.py`
- `v2/frontend/src/components/layout/RuntimeTruthStrip.tsx`
- `v2/mobile/Sources/AIBotV2/Views/Components/RuntimeTruthCard.swift`
- `v2/backend/tests/integration/api/v2/test_phase_h_route_alias_contracts.py`

## Runtime Redis Keys/API Routes
- Redis: v2:paper:performance_governor_status
- Redis: v2:paper:new_entry_emergency_halt_status
- Redis: v2:trainer:hybrid_cuda:status
- Redis: v2:monitor:runtime_drift
- Redis: v2:altdata:santiment:symbol:*
- API: /api/v2/paper/runtime-status
- API: /api/v2/live-readiness
- API: /api/v2/mobile/paper-summary
- Artifact: v2/frontend/public/operator_runtime/v2_runtime_drift/latest/status.json
- API: /api/v2/portfolio
- API: /api/v1/paper-trades
- API: /api/v2/signals
- API: /api/v2/markets
- API: /api/v2/derivatives
- API: /api/v2/risk
- API: /api/v2/orchestrator
- API: /api/v2/system/health

## Operator/Trader/Developer Meaning
- Operator: use this document to decide whether the current runtime is safe, current, and fail-closed.
- Trader: use this document to interpret paper performance, A+ readiness, REDUCE_SIZE bootstrap rows, live gate state, and why trades are blocked.
- Developer: use this document to find the source files, route contracts, Redis keys, tests, and evidence artifacts that must stay in sync.
- Primary audience for this page: operator, trader, and developer.

## Failure Modes
- Stale runtime payload labelled as current.
- `new_entries_allowed=true` while PF is below 1 or expectancy is non-positive.
- A+ shown when final A+ rows are zero, or REDUCE_SIZE rows shown as final A+.
- Live readiness shown without signed-read and pre-submit dry-run proof.
- Santiment or another paid data source expected for symbol selection but unused.
- Feature freshness or lineage missing around `available_at`, `feature_cutoff`, `decision_time`, or `execution_time`.
- `/api/v2/portfolio`, `/api/v2/mobile/paper-summary`, and `/api/v1/paper-trades` disagree on current-session PnL/equity source.
- Provider readiness showing Moralis green from health alone without `v2:provider:moralis:feature_bridge_status.feature_bridge_ready=true`.

## Debug Commands
- `systemctl --user list-units --type=service --all | rg "ai-bot-v2|paper|trainer"`
- `redis-cli GET v2:paper:performance_governor_status | python3 -m json.tool`
- `redis-cli GET v2:paper:new_entry_emergency_halt_status | python3 -m json.tool`
- `redis-cli GET v2:monitor:runtime_drift | python3 -m json.tool`
- `redis-cli --scan --pattern "v2:altdata:santiment:symbol:*" | wc -l`

## Validation Commands
- `python -m py_compile v2/backend/app/cli/v2_runtime_drift_monitor.py`
- `.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_runtime_drift_monitor.py`
- `npm --prefix v2/frontend run typecheck`
- `npm --prefix v2/frontend run build`
- `swift test --package-path v2/mobile`

## Evidence Artifacts
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_H_BACKEND_API_CONTRACT_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_I_FRONTEND_ROUTE_TRUTH_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_J_IOS_RUNTIME_TRUTH_STATUS.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/PHASE_K_RUNTIME_ALERT_MATRIX.json`
- `goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/RUNTIME_SNAPSHOTS/PHASE_K_RUNTIME_DRIFT_STATUS.json`

## Current Runtime Truth
- Paper state: `HALTED_PERFORMANCE`, PF about `0.4613`, expectancy about `-5.2575 bps`, and `new_entries_allowed=false`.
- Trainer state: `WEIGHTS_UPDATING` with feedback rows present.
- Live state: `blocked_human_only`; dry-run packets must not submit or mutate exchange state.
- Runtime drift: Phase K monitor reports `services_stale=0` after V2 restarts and the legacy comparator stop.
- Santiment: `v2:altdata:santiment:symbol:*` has runtime symbol-selection evidence and the paid-ingestor-unused alert is passing.
- Portfolio/PnL contract: current-session paper equity and PnL headline fields come from `v2:portfolio:state` and expose `pnl_source_key=v2:portfolio:state`, `pnl_source_route=/api/v2/portfolio`, and `pnl_source_type=CANONICAL_CURRENT_SESSION_RUNTIME`.
- Moralis contract: `/api/v2/provider-readiness` and mobile readiness fields consume `v2:provider:moralis:health`, which must be consistent with `v2:provider:moralis:feature_bridge_status`; heartbeat-only or required-feature-missing payloads are not green.
