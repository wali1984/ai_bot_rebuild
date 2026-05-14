# FULL_LEGACY_RL_RISK_FILE_INVENTORY — Phase A

Authoritative re-scan of the legacy repo's `rl/`, `risk/`, `services/`, `utils/`, `trading/`, top-level helpers, and `scripts/`. Confirms the prior startup-baseline copy under-scoped these trees by 6×.

## Top-level counts

| package | .py files (legacy) | KB | copied this turn |
|---|---|---|---|
| `rl/` | **121** | 13 622 | 121 |
| `trading/` | **35** | 4 665 | 35 |
| `risk/` | **22** | 933 | 22 |
| `utils/` | **21** | 255 | 21 |
| `services/` | **8** | 149 | 8 |
| `scripts/` (trainer/risk/trade/hedge/profit/position/orchestrator only) | **21** | varied | 21 |
| top-level helpers | 3 | (see below) | 3 |
| **total this phase** | **231 sources** | **~19.6 MB legacy** | **248** (includes some non-`.py` like shell scripts) |

Top-level helpers:
- `config.py` (407 KB) — copied
- `config_accounts.py` (10 KB) — copied
- `telegram_alerts.py` (111 KB) — copied

## What was already in the prior baseline copy

Prior Phase C copied 33 files focused on the startup script's direct invocations. That copy completely missed:

- `rl/*.py` package (121 files) except the entry points
- `risk/*.py` entire package (22 files)
- `services/*.py` entire package (8 files)
- `utils/*.py` entire package (21 files)
- 33 of 35 `trading/*.py`
- top-level `config_accounts.py`
- top-level `telegram_alerts.py`

This Phase A confirms the prior closure's blockers and resolves them by extending the preserved tree.

## Categories (per file) — top examples

For the full per-file inventory with sha256 + size + category + imports, see [full_runtime_copied_source_manifest.json](full_runtime_copied_source_manifest.json) (copier manifest) and [full_trainer_trader_dependency_closure.json](full_trainer_trader_dependency_closure.json) (closure profile).

### trainer_core / trainer_support (rl/)

- `rl/hybrid_trainer.py` — entry
- `rl/gpu_optimized_trainer.py`, `rl/stable_gpu_trainer.py`, `rl/gpu_cnn_policy.py`, `rl/gpu_saturation.py` — GPU runtime
- `rl/supervised_pretrainer.py`, `rl/warm_start.py` — pretraining
- `rl/checkpoint_manager.py`, `rl/promotion_controller.py` — checkpoint lifecycle
- `rl/confidence_gates.py`, `rl/threshold_ramper.py`, `rl/decision_trace.py` — confidence pipeline
- `rl/obs_schema.py`, `rl/unified_feature_builder.py` — feature contracts
- `rl/gymnasium_wrapper.py`, `rl/hedge_action_space.py`, `rl/fee_ratio_reward_shaping.py` — RL env
- `rl/moe_router.py`, `rl/scenario_engine.py`, `rl/walk_forward_validation.py` — multi-policy machinery
- `rl/replay_store.py`, `rl/trade_feedback.py` — feedback loop
- `rl/proposal_hedge_preflight.py`, `rl/global_safety_checks.py` — pre-publish gates

### orchestrator_core (rl/)

- `rl/orchestrator_worker.py` — entry
- `rl/decision_trace.py`, `rl/proposal_hedge_preflight.py` — proposal stage helpers

### risk_core / risk_assertion / halt_circuit (risk/)

- `risk/assertions.py` — entry referenced by closure
- `risk/halt_manager.py`, `risk/kill_switch.py` — halt / kill-switch
- `risk/risk_state_machine.py`, `risk/phase_controller.py` — state machinery
- `risk/intelligent_close_guard.py`, `risk/reduce_only_latch.py` — close-side safety
- `risk/auto_deleverager.py`, `risk/adaptive_gate.py`, `risk/risk_budget_allocator.py` — gating + budget
- `risk/trainer_intent.py`, `risk/trainer_alignment.py` — trainer↔risk handshake
- `risk/microstructure_toxicity.py`, `risk/margin_governor.py`, `risk/shared_risk_gate.py`

### trader_core / executor_core / hedge / dca / stop / take_profit / stealth (trading/)

- `trading/trader.py`, `trading/trader-asjad.py` — trader entries (NEVER started by V2)
- `trading/base_executor.py` — base executor
- `trading/execution_engine.py`, `trading/maker_execution.py` — execution
- `trading/depth_execution_gate.py`, `trading/fee_ratio_gate.py`, `trading/adaptive_edge_gate.py` — gates
- `trading/adaptive_hedge_builder.py`, `trading/dynamic_adaptive_hedge.py`, `trading/hedge_context.py`, `trading/hedge_intelligence_engine.py`, `trading/hedge_pair_coordinator.py` — hedge machinery
- `trading/dynamic_tp_engine.py`, `trading/dynamic_adaptive_stops.py` — TP/SL
- `trading/dynamic_margin_manager.py`, `trading/leg_manager.py` — margin + leg
- `trading/churn_prevention.py`, `trading/opportunity_tracker.py`, `trading/lifecycle_controller.py`, `trading/exit_coordinator.py` — lifecycle

### service_helper (services/)

`portfolio_state`, `portfolio_publisher`, `onchain_analyzer`, `liquidation_intelligence`, `data_archiver`, `live_decision_evaluator`, `service_monitor`.

### utility_helper (utils/)

`logger`, `metrics`, `healthbeat`, `redis_client`, `redis_hardening`, `redis_key_audit`, `binance_rate_limiter`, `websocket_limits`, `symbol_manager`, `ai_coins_manager`, `decision_bus`, `signal_publish`, `signal_schema`, `preflight`, `runtime_flags`, `interpreter_guard`, `interrupt_lock`, `data_normalizer`, `data_manager`, `ensemble_diagnostics`, `unified_position_loader`.

### scripts (21 helper scripts)

`start_trainer.sh`, `stop_trainer.sh`, `nightly_restart_trainer.sh`, `soak_test_trainer.sh`, `integration_test_trainer.sh`, `logrotate_hybrid_trainer.conf`, `monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `check_trainer_signal_health.py`, `verify_trader_consumption.py`, `validate_trader_alignment.py`, `audit_trade_attribution.py`, `trace_trade_lifecycle.py`, `start_trader.sh`, `stop_trader.sh`, `stop_trader_asjad.sh`, `why_hedged_timeline.py`, `validate_flash_hedge_system.sh`, `test_hedge_build.py`, `close_all_positions.py`, `audit_orchestrator_last30m.py`, `monitor_orchestrator_shadow.py`.

`close_all_positions.py` is treated as **DO_NOT_RUN_FROM_V2** — action-side; only P2 fail-closed stub may reference it.

## Closure scan profile of the preserved tree (Phase C output)

| metric | value |
|---|---|
| files analyzed | 231 |
| parse errors | 2 (non-blocking for inventory) |
| files using Redis | **49** |
| files using exchange API | **43** |
| files using subprocess | 6 |
| files importing `config` | 100 |
| files with unresolved local imports (after expanded copy) | 79 |

External-dep profile across the 231 files:

| count | external | notes |
|---|---|---|
| 58 | `numpy` | RL/feature math everywhere |
| 43 | `redis` | legacy stack is Redis-pervasive (V2 reads only) |
| 34 | `torch` | trainer + RL policies + tools |
| 10 | `binance` | python-binance SDK in trading/ + utils/ |
| 9 | `stable_baselines3` | RL framework |
| 5 | `requests` | HTTP |
| 3 | `psutil`, `pandas`, `pynvml` | telemetry/utils |
| 1 | `aiohttp` | async HTTP |

## Remaining unresolved imports (down from prior 79)

A handful of stdlib modules (`__future__`, `atexit`, `faulthandler`, `statistics`, `secrets`) are not yet in the closure scanner's `STDLIB_GUESS` set and show as "unresolved" — that is a scanner-precision issue, not a missing-file issue. The actual missing modules requiring attention:

| unresolved | classification | next step |
|---|---|---|
| `binance_websocket` | local helper file likely under a sub-package; verify if present | scan for it across legacy |
| `cloudpickle`, `gymnasium`, `dotenv`, `urllib3` | external pip packages | install per-port under operator approval |
| `hybrid_rule_based_signals` | likely local file at legacy root | check for missing top-level file |
| `ingest` | namespace package; trader imports `from ingest import …` | preserve cross-link to startup_baseline/ingest |

## Forbidden during this phase (verified)

- No edits to legacy bot root — verified (copier uses `.read_bytes()` only).
- No copies of `.env`, secrets, credentials, private keys — path filter + content heuristics.
- No binary checkpoints, model weights, archives, images — extension allow-list (139 files skipped, inventoried separately).
- No Redis writes from V2 — copier has no Redis client.
- No exchange / leverage / margin codepath — copier has no exchange SDK.
- Live gate untouched.
