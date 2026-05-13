# V2_RUNTIME_WORKER_GAP_MATRIX

Brutal inventory: every legacy runtime responsibility → V2 equivalent (real code, not docs), with strict classification.

## Classifications (strict)

- **MIGRATED_AND_RUNNING** — V2 file exists, runnable CLI invocation exists, currently running or recently produced fresh runtime evidence.
- **MIGRATED_NOT_RUNNING** — V2 file exists with runnable CLI, but not currently executing.
- **MIGRATED_LIBRARY_ONLY** — V2 file fully implements the logic but only as a library; no standalone CLI worker.
- **WRAPPED_READONLY_ONLY** — V2 only observes legacy outputs (via Redis read, log read, etc.), does not own the production of those outputs.
- **PAPER_ONLY** — V2 implementation exists but only operates in paper/simulation mode.
- **BACKLOG_ONLY** — listed in plans/docs but no file.
- **MISSING_IN_V2** — no implementation.
- **LEGACY_ONLY** — runs only on the legacy system.
- **DEPRECATED_WITH_EVIDENCE** — removed intentionally, evidence on record.

## Matrix

### 1. V2 market ingestor (price/kline real-time feed → V2 stream/db)

| field | value |
|---|---|
| state | **MISSING_IN_V2** |
| legacy path | legacy `ingest/*` scripts under the frozen legacy root (operator-shut-down) |
| V2 path | none |
| V2 runnable command | none |
| inputs | Binance public REST/WS, V2-owned stream/db sink |
| outputs | V2 kline stream, mark-price stream |
| Redis/db namespace | V2-namespaced (must NOT write old Redis) |
| public payload | none |
| GUI route | none yet |
| tests | none |
| runtime status | not running |
| blocker | no service skeleton; paper online runtime hardcodes a Binance public REST fetch but does not persist |
| depends on frozen legacy? | no |

### 2. V2 CoinAnk / liquidation bridge worker

| field | value |
|---|---|
| state | **MISSING_IN_V2** (only a symbol-resolver adapter exists) |
| legacy path | legacy CoinAnk WS/REST ingestors (frozen) |
| V2 path | `v2/backend/app/adapters/symbol_sources/coinank.py` (read-only symbol alias resolver only) |
| V2 runnable command | none |
| inputs | CoinAnk REST/WS for liquidation/funding/OI data |
| outputs | `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json` |
| Redis/db namespace | V2-namespaced |
| public payload | path exists, currently empty/stale |
| GUI route | `/admin/market-intelligence` (proposed by parallel UI task) |
| tests | `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` (resolver tests only) |
| runtime status | not running |
| blocker | no liquidation watcher; no real-time event producer; no bridge worker |
| depends on frozen legacy? | no |

### 3. V2 feature pipeline / feature snapshot builder

| field | value |
|---|---|
| state | **MIGRATED_LIBRARY_ONLY** |
| V2 path | `v2/backend/app/services/feature_snapshots/service.py` |
| V2 runnable command | none (library service; invoked inside paper online runtime) |
| inputs | market data, trainer-readiness signals |
| outputs | feature_snapshot embedded in paper runtime payload |
| public payload | `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json` (feature_snapshot sub-object) |
| tests | composition unit tests (implied) |
| runtime status | runs only when the paper online runtime runs (currently down) |
| blocker | no standalone feature pipeline worker (snapshot building is embedded in paper online runtime loop, not a separate producer) — limits independent scaling and audit |
| depends on frozen legacy? | no |

### 4. V2 trainer bridge / service

| field | value |
|---|---|
| state | **WRAPPED_READONLY_ONLY** |
| V2 path | `v2/backend/app/composition/trainer_parity/runtime.py`, `v2/backend/app/services/trainer_parity/service.py` |
| V2 runnable command | none |
| inputs | legacy Redis streams `trainer:predictions`, `wma:proposals` (read-only); for paper mode, inline momentum wrapper in paper online runtime `build_trainer_prediction()` |
| outputs | trainer_prediction record |
| public payload | `v2/frontend/public/operator_runtime/paper_online/latest/trainer_prediction_current_record.json` |
| tests | composition unit tests (implied) |
| runtime status | trainer_parity monitor not running; paper inline wrapper runs only when the paper online runtime runs (currently down) |
| blocker | no subprocess wrapper around legacy trainer; V2 paper mode uses a hard-coded momentum wrapper, not the real legacy trainer. With legacy shut down, "trainer-parity" mode produces no current evidence. |
| depends on frozen legacy? | yes, for parity mode — classify as `MISSING_RUNTIME_EVIDENCE` until a real V2 trainer or legacy-trainer subprocess wrapper exists |

### 5. V2 orchestrator adapter

| field | value |
|---|---|
| state | **MIGRATED_LIBRARY_ONLY** |
| V2 path | `v2/backend/app/composition/orchestrator_decision/runtime.py`, `v2/backend/app/services/orchestrator_decision/service.py` |
| V2 runnable command | none (library) |
| inputs | TrainerPredictionRecord |
| outputs | OrchestratorDecisionRecord |
| public payload | embedded in `current_signal_lineage.json` |
| tests | composition unit tests (implied) |
| runtime status | runs only when the paper online runtime runs (currently down) |
| blocker | no standalone CLI; deterministic routing only |
| depends on frozen legacy? | no |

### 6. V2 signal publisher / signal lineage worker

| field | value |
|---|---|
| state | **STUB / PLACEHOLDER** |
| V2 path | `v2/backend/app/services/signal_publisher.py` (1-line placeholder) |
| V2 runnable command | none |
| inputs | OrchestratorDecisionRecord, RiskDecisionRecord |
| outputs | signal_lineage record |
| public payload | `v2/frontend/public/operator_runtime/paper_online/latest/current_signal_lineage.json` (written by the paper online runtime, not by signal_publisher) |
| tests | none |
| runtime status | placeholder; lineage built inline in paper online runtime (currently down) |
| blocker | placeholder service with no implementation; signal lineage construction is hard-coded into the paper online runtime |
| depends on frozen legacy? | no |

### 7. V2 risk gateway runtime worker

| field | value |
|---|---|
| state | **MIGRATED_LIBRARY_ONLY** |
| V2 path | `v2/backend/app/composition/risk_gateway/runtime.py`, `v2/backend/app/services/risk_gateway/service.py` |
| V2 runnable command | none (library) |
| inputs | OrchestratorDecisionRecord |
| outputs | RiskDecisionRecord with fail-closed logic (gate always `blocked_human_only`; risk_action based on decision action with low-confidence/freshness denials) |
| public payload | `v2/frontend/public/operator_runtime/paper_online/latest/current_risk_decisions.json` |
| tests | composition unit tests (implied) |
| runtime status | runs only when the paper online runtime runs (currently down) |
| blocker | no standalone CLI; gate correctly always `blocked_human_only` |
| depends on frozen legacy? | no |

### 8. V2 paper execution worker (paper trader)

| field | value |
|---|---|
| state | **MIGRATED_LIBRARY_ONLY** (paper-only) |
| V2 path | `v2/backend/app/composition/paper_execution_ledger/runtime.py`, `v2/backend/app/services/paper_execution_ledger/service.py` |
| V2 runnable command | none (library) |
| inputs | RiskDecisionRecord |
| outputs | PaperExecutionLedgerEntry with simulated fills |
| public payload | `v2/frontend/public/operator_runtime/paper_online/latest/paper_ledger_tail.json` |
| tests | composition unit tests (implied) |
| runtime status | runs only when the paper online runtime runs (currently down) |
| blocker | no standalone CLI; paper-only — no real execution branch |
| depends on frozen legacy? | no |

### 9. V2 execution ledger worker

| field | value |
|---|---|
| state | **MIGRATED_LIBRARY_ONLY** (shares code with #8) |
| V2 path | same as #8 |
| V2 runnable command | none |
| outputs | append-only `paper_events.jsonl` |
| public payload | `paper_ledger_tail.json` |
| tests | composition unit tests |
| runtime status | runs only when the paper online runtime runs |
| blocker | no real exchange-order ledger writer; paper-only |
| depends on frozen legacy? | no |

### 10. V2 account/position read-only monitor

| field | value |
|---|---|
| state | **MISSING_IN_V2** |
| V2 path | none |
| V2 runnable command | none |
| inputs | exchange read-only account/positions API (Binance `GET /fapi/v3/account`, `GET /fapi/v2/positionRisk`) |
| outputs | real account state, real positions, margin/leverage evidence |
| public payload | none real; `paper_positions.json` is paper-only simulated |
| tests | none |
| runtime status | not running |
| blocker | no real account monitor; paper online runtime simulates positions inline; `/api/v1/accounts` is skeleton |
| depends on frozen legacy? | no |

### 11. V2 PnL / accounting worker

| field | value |
|---|---|
| state | **MISSING_IN_V2** (paper-only inline simulation in paper online runtime) |
| V2 path | inline in paper online runtime `build_paper_ledger_entry()` |
| V2 runnable command | none separate |
| outputs | equity, pnl in `paper_runtime_status.json` |
| tests | none |
| runtime status | runs only when the paper online runtime runs |
| blocker | no durable accounting ledger; no journal entries; paper-mode simulated PnL only |
| depends on frozen legacy? | no |

### 12. V2 replay / backtest runner

| field | value |
|---|---|
| state | **MIGRATED_LIBRARY_ONLY** |
| V2 path | `v2/backend/app/composition/replay_backtest_runner/runtime.py`, `v2/backend/app/services/replay_backtest_runner/service.py` |
| V2 runnable command | none (library); `/api/v1/replay` skeleton endpoints |
| outputs | replay step + summary records |
| public payload | none yet |
| tests | composition unit tests (implied) |
| runtime status | not running |
| blocker | library service only; no CLI entrypoint; `/api/v1/replay` is skeleton |
| depends on frozen legacy? | no |

### 13. V2 script monitor / Monitor Center worker

| field | value |
|---|---|
| state | **STUB / PLACEHOLDER** |
| V2 path | `v2/backend/app/services/monitor_runner.py` (1-line placeholder) |
| V2 runnable command | none |
| outputs | per-script status (last run, last success, last failure, metrics emitted, alerts) |
| public payload | none |
| tests | none |
| runtime status | not running |
| blocker | placeholder service; `/api/v1/monitor` skeleton-only |
| depends on frozen legacy? | no |

### 14. V2 config / admin manager (runtime config CRUD)

| field | value |
|---|---|
| state | **STUB / PLACEHOLDER** |
| V2 path | `v2/backend/app/api/v1/accounts.py`, `governance.py`, `claude_admin.py` (all OPTIONS skeletons) |
| V2 runnable command | none |
| outputs | runtime config records with staged/approval state |
| public payload | none |
| tests | none |
| runtime status | not running |
| blocker | all skeleton endpoints; no config manager service, no runtime CRUD |
| depends on frozen legacy? | no |

### 15. V2 Admin AI backend

| field | value |
|---|---|
| state | **STUB / PLACEHOLDER** |
| V2 path | `v2/backend/app/api/v1/claude_admin.py` (skeleton) |
| V2 runnable command | none |
| outputs | natural-language answers from real evidence |
| public payload | `v2/frontend/public/operator_runtime/paper_online/latest/admin_ai_status.json` (mocked by paper online runtime, labeled `NON_LIVE_QUERY_SURFACE_READY_FROM_OPERATOR_PAYLOADS` — note: no queries are actually answered) |
| tests | none |
| runtime status | not running |
| blocker | no Admin AI service; no Claude API integration; no query answer logic |
| depends on frozen legacy? | no |

### 16. V2 paper online runtime / paper-shadow entrypoint

| field | value |
|---|---|
| state | **MIGRATED_NOT_RUNNING** (was running earlier in this session; currently DOWN) |
| V2 path | `v2/backend/app/cli/paper_online_runtime.py` (full standalone CLI, ~1050 lines), `v2/backend/app/cli/paper_shadow_observation.py` |
| V2 runnable command | `python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30 --symbol BTCUSDT` |
| outputs | the entire `v2/frontend/public/operator_runtime/paper_online/latest/` payload set + `paper_events.jsonl` |
| tests | none specific to the CLI |
| runtime status | **not running** as of 2026-05-13 20:40 UTC |
| blocker | needs to be restarted; the runtime itself is operationally complete for paper mode |
| depends on frozen legacy? | no for paper mode (uses inline momentum wrapper for trainer) |

### 17. V2 default-blocked execution adapter stub

The default-blocked execution adapter is tracked as a P2 stub task descriptor. It is currently fail-closed via the `live_block_guard` middleware (HTTP 403 default-blocked for ALL gated requests). The explicit `BLOCKED_GATE_NOT_APPROVED`-raising worker stub is missing; only the middleware-level deny exists. See the P2 task descriptor for the explicit stub requirement. This row is excluded from the main worker-count summary below to keep the count focused on paper-shadow independence.

## Summary by classification

| classification | count | items |
|---|---|---|
| MIGRATED_NOT_RUNNING (standalone CLI exists) | 1 | paper online runtime (+ paper_shadow_observation) |
| MIGRATED_LIBRARY_ONLY (needs CLI extraction) | 6 | feature_snapshot_builder, orchestrator_adapter, risk_gateway_runtime, paper_execution_worker, execution_ledger_worker, replay_backtest_runner |
| WRAPPED_READONLY_ONLY | 1 | trainer_bridge (depends on frozen legacy) |
| STUB / PLACEHOLDER | 4 | signal_publisher, monitor_center, config_admin_manager, admin_ai_backend |
| MISSING_IN_V2 | 4 | market_ingestor, coinank_liquidation_bridge, account_position_monitor, pnl_accounting_worker |

**Total in matrix: 16 paper-shadow responsibilities** (the default-blocked execution adapter stub is P2, tracked separately). Independent V2 paper/shadow runtime is approximately 1 of 16 if measured strictly by "standalone runnable worker"; lifting the 6 library-only items into CLI wrappers immediately moves independence to ~7 of 16.
