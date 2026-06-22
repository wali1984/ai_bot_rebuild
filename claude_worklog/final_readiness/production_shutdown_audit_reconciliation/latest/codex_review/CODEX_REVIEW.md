# Codex Review: Production Shutdown Audit Reconciliation

Generated: `2026-05-17T00:53:49Z`

GO/NO-GO: `PRODUCTION_SHUTDOWN_AUDIT_RECONCILIATION_CODEX_PASS_HARD_NO_GO`

## Decision

Codex confirms the production shutdown audit's hard NO-GO. The paper-only acceptance-file gate must not be treated as production shutdown readiness.

Legacy still owns production ingestion, feature assembly, trainer, orchestrator, and signal Redis output. V2 is running paper/shadow/observatory/control-plane processes and still self-declares paper-only, partial, missing, or fail-closed states.

This review does not approve live trading, canary trading, exchange mutation, leverage changes, margin changes, legacy shutdown, or Redis trim.

## Process Ownership

Current legacy production processes are still running. Codex observed `14` legacy core/monitoring processes matching production roles, including:

- `ingest/live_binance.py`
- `ingest/live_binance_liquidations.py`
- `ingest/live_coinank.py`
- `ingest/live_kucoin.py`
- `ingest/live_technical_analysis.py`
- `feature_pipeline.py`
- `rl.hybrid_trainer --mode hybrid`
- `trading/opportunity_tracker.py`
- `rl.orchestrator_worker`
- `ingest/live_coinapi_v1.py`
- `ingest/live_coinapi_wsds.py`
- trainer and portfolio monitors

Codex found `0` running V2 production-equivalent worker processes for:

- `v2_market_ingestor`
- `v2_rl_core_worker`
- `v2_orchestrator_arbitration_worker`
- `v2_trade_management_paper_worker`
- `v2_native_ingestors_worker`
- `v2_kucoin_ingestor_worker`

Running V2 processes are paper/shadow/watchdog/observatory/supervisor/frontend style processes, for example `paper_online_runtime`, `v2_feature_snapshot_builder`, Codex observatory/takeover daemons, and Vite.

## Redis Production Ownership

Redis read-only inspection supports HARD NO-GO:

- `v2:*` key count: `0`
- `prediction:*` key count: `151`
- `features:*` key count: `5838`
- `market:*` key count: `144`
- `trainer:*` key count: `27`
- `signals:*` key count: `8`
- `orchestrator:*` key count: `1`

Representative production key:

- `prediction:BTCUSDT:5m` exists as a Redis hash.
- It contains live-style prediction fields including `action`, `direction`, `confidence`, `ppo_confidence`, `masa_confidence`, `entry_price`, `timestamp`, `symbol`, and `timeframe`.
- `trainer:brain:status` reports `ppo_ready=1`, `masa_ready=1`, and a live heartbeat key `trainer:heartbeat:WALI-AMD:48623`, matching the legacy `rl.hybrid_trainer` PID.

Conclusion: production prediction/signal state is still legacy-owned. V2 is not writing production `v2:*` Redis state.

## V2 Self-Declarations

Codex scanned V2 source and public runtime payloads:

- `MISSING_IN_V2` occurrences: `28`
- `approves_legacy_shutdown=false` occurrences: `50`
- paper-only declarations: `5988`

Representative self-declarations:

- `v2/backend/app/cli/v2_owned_ingestors_runtime.py` says it does not open WebSocket or REST connections and does not write legacy Redis; it is a dry-run smoke.
- `v2/backend/app/cli/v2_owned_trainer_runtime.py` says it does not start training, initialize CUDA, or load model weights; it is a paper-only smoke.
- `v2/backend/app/services/rl_core/service.py` says it does not import Torch/SB3, write Redis, run a Gymnasium loop, train PPO/MASA, or approve shutdown.
- `v2/backend/app/services/rl_core/policy.py` uses `MODEL_SOURCE_CLASSIFICATION = "V2_NATIVE_CPU_DETERMINISTIC_INIT_NO_CHECKPOINT"` and lists multiple deferred/missing trainer pieces.
- `v2/backend/app/services/orchestrator_arbitration/service.py` declares the service informational/paper-only and lists missing live orchestration pieces including live order routing and live Redis proposal-bus integration.
- `v2/backend/app/services/trade_management_paper/hedge_engine.py` is paper-only and fail-closes on live posture leaks.

## Final Paper-Only Gate Reconciliation

The final paper-only shutdown decision packet does not currently mark production shutdown safe:

- Final decision packet: `OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN`
- Final Codex acceptance verification: `FINAL_PAPER_ONLY_SHUTDOWN_DECISION_CODEX_FAIL`
- Acceptance file: missing
- Frontend final decision payload: shutdown not safe

Even if a paper-only acceptance file appears later, it cannot be interpreted as production-equivalence readiness. Production shutdown remains blocked while legacy owns live ingestion, training, orchestration, feature Redis, and prediction Redis.

## Frontend Truth

The active frontend truth payload says:

- `shutdown_recommendation = BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`
- `approves_legacy_shutdown = false`
- `live_gate = blocked_human_only`
- current goal is to build the native V2 trading core before revisiting shutdown/live work

The final paper-only decision payload also does not claim safe shutdown. This is acceptable. No frontend payload reviewed approves live/canary/shutdown.

## Safety Validation

- Live/canary/shutdown approval scan over reviewed artifacts: PASS, no active approval found.
- Active final-decision/runtime old Redis write scan: PASS, no matches.
- Active final-decision/runtime exchange mutation scan: PASS, no matches.
- Redis inspection was read-only.
- No legacy process was stopped or modified.
- No old Redis write was performed.

Note: the final paper-only decision packet contains the string `SAFE_TO_SHUTDOWN_LEGACY_RUNTIME_FOR_V2_PAPER_ONLY` only as a documented possible future value. The active decision remains `OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN`, and this production review remains HARD NO-GO.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Final Verdict

`PRODUCTION_SHUTDOWN_AUDIT_RECONCILIATION_CODEX_PASS_HARD_NO_GO`

Do not shut down legacy production. V2 is not a production replacement yet.
