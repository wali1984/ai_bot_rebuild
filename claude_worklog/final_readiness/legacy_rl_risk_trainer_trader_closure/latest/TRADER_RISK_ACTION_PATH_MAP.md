# TRADER_RISK_ACTION_PATH_MAP — Phase E

File-level map of every legacy action path that can place, cancel, modify, hedge, DCA, stop, take-profit, reduce-only, flip, rebalance, adjust leverage, or change margin. **V2 must not execute any of these; this map is reference-only.**

## Trader entry points

| file | role | V2 stance |
|---|---|---|
| `trading/trader.py` | primary trader | NEVER started by V2; P2 fail-closed stub only |
| `trading/trader-asjad.py` | per-account trader (Asjad) | NEVER started by V2; same P2 fail-closed stub |

## Executor + execution gates

| file | action surface |
|---|---|
| `trading/base_executor.py` | base class for executors |
| `trading/execution_engine.py` | execution engine; orchestrates order placement |
| `trading/maker_execution.py` | maker-side order placement |
| `trading/depth_execution_gate.py` | depth-aware pre-execution gate |
| `trading/fee_ratio_gate.py` | fee-ratio pre-execution gate |
| `trading/adaptive_edge_gate.py` | adaptive-edge gate |

## Hedge logic

| file | action surface |
|---|---|
| `trading/adaptive_hedge_builder.py` | hedge proposal builder |
| `trading/dynamic_adaptive_hedge.py` | dynamic hedge sizing/adjustment |
| `trading/hedge_context.py` | hedge state context |
| `trading/hedge_intelligence_engine.py` | hedge decision engine |
| `trading/hedge_pair_coordinator.py` | per-pair hedge coordinator |
| `trading/leg_manager.py` | hedge leg manager |
| `rl/hedge_action_space.py` | hedge action enum used by trainer |
| `rl/hedge_budget_governor.py` | hedge budget |

## Stop loss / take profit / stealth

| file | action surface |
|---|---|
| `trading/dynamic_tp_engine.py` | dynamic take-profit |
| `trading/dynamic_adaptive_stops.py` | dynamic stops |

## Margin + leverage

| file | action surface |
|---|---|
| `trading/dynamic_margin_manager.py` | margin manager (CROSS / ISOLATED) |
| `risk/margin_governor.py` | margin governance |

## Lifecycle + exit + churn

| file | action surface |
|---|---|
| `trading/lifecycle_controller.py` | position lifecycle controller |
| `trading/exit_coordinator.py` | exit coordination |
| `trading/churn_prevention.py` | churn prevention |
| `trading/opportunity_tracker.py` | opportunity tracking |

## Risk gates (intersect with trading/)

| file | action surface |
|---|---|
| `risk/assertions.py` | risk assertion entry |
| `risk/halt_manager.py` | halt manager |
| `risk/kill_switch.py` | kill switch |
| `risk/intelligent_close_guard.py` | close-side guard |
| `risk/reduce_only_latch.py` | reduce-only latch |
| `risk/auto_deleverager.py` | auto-deleverage |
| `risk/shared_risk_gate.py` | shared risk gate |
| `risk/adaptive_gate.py` | adaptive gate |
| `risk/risk_state_machine.py` | risk state machine |
| `risk/phase_controller.py` | phase controller |
| `risk/risk_budget_allocator.py` | risk budget allocation |

## Per-action V2 mapping summary

Every action listed above falls into one of these V2 stances:

| legacy action | V2 stance |
|---|---|
| place / cancel / modify exchange order | **NEVER from V2**; P2 stub raises `BLOCKED_GATE_NOT_APPROVED` |
| reduce-only close | NEVER from V2; mirrored in P2 stub method that raises |
| increase position | NEVER from V2 |
| flip direction | NEVER from V2 |
| rebalance | NEVER from V2 |
| change leverage | NEVER from V2 |
| change margin (CROSS/ISOLATED) | NEVER from V2 |
| set / cancel / replace stop | NEVER from V2 |
| take profit / stealth profit | NEVER from V2 |
| reopen after close | NEVER from V2 |
| quarantine / external manual position | V2 `v2_external_manual_position_quarantine` composition already library-only; CLI port pending |

## Required classification snapshot

- `RISK_PATHS_MAPPED` — yes (file-level)
- `ACTION_PATHS_MAPPED` — yes (file-level)
- `HEDGE_PATHS_MAPPED` — yes
- `STOP_LOSS_TAKE_PROFIT_PATHS_MAPPED` — yes
- `STEALTH_PROFIT_PATHS_MAPPED` — pending verification of `trading/stealth_stops.py` existence in the legacy root (referenced by other files; not enumerated as a copied file)
- `MARGIN_LEVERAGE_PATHS_MAPPED` — yes
- `FUNCTION_LEVEL_MAPPING_PENDING` — yes; the per-worker port's `LEGACY_BASELINE_ANALYSIS.md` is the next granularity

## V2 risk gateway test expansion requirement

The V2 risk gateway runtime worker port (`claude_port_v2_risk_gateway_runtime_worker`) must extend its test suite to cover legacy-equivalent denials for every entry in this map. Specifically:

- `low_confidence_denied` (existing)
- `stale_feature_denied` (existing)
- `kill_switch_active_denies_everything`
- `halt_manager_active_denies_everything`
- `reduce_only_latch_denies_increase_position`
- `intelligent_close_guard_overrides_close_only_if_safety_holds`
- `auto_deleverager_triggered_position_reduce_only`
- `shared_risk_gate_denies_when_budget_exhausted`
- `margin_governor_denies_leverage_increase`
- `phase_controller_blocks_in_warmup_phase`
- `adaptive_gate_blocks_on_microstructure_toxicity`
