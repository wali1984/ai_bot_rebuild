# Requirement 0020 — Full Autonomous Legacy-Mapped Paper/Backtest Performance Target

## Objective

The V2 rebuild must remain aligned with the original goal:

Preserve the working legacy bot behavior, learn from legacy failures, rebuild a safer and more explainable V2 system, and prove whether aggressive equity-growth targets are possible through replay, backtest, paper, and shadow validation before any live approval.

## Performance target

Research target:
- 40–50% daily equity growth is an aspirational research target only.
- It must not be treated as guaranteed.
- It must not force overtrading, leverage escalation, DCA, rescue trades, or risk-gate bypasses.
- The system must prove any edge through replay/backtest/paper/shadow evidence.

## Required proof before live

Before any live approval request, V2 must show:

- replay/backtest results
- paper trading results
- shadow-mode results beside legacy
- daily PnL distribution
- max drawdown
- loss streaks
- win/loss by symbol
- win/loss by feature regime
- performance by confidence bucket
- risk-gateway blocks
- bad legacy trades avoided
- good legacy trades preserved/captured
- liquidation/exposure risk analysis
- stale-data blocked decisions
- feature attribution for winners and losers

## Hard live gate

Live trading remains blocked until explicit human approval.

No component may:
- enable live trading
- place/cancel orders
- change leverage/margin
- write/delete Redis live keys
- restart live services
- mutate `/home/wali/Desktop/AI BOT`
- deploy production changes

## Legacy mapping requirement

Claude must continuously map and use the actual legacy system:

- `scripts/start_all_services_production.sh`
- running process list
- ingestors
- `feature_pipeline.py`
- `rl.hybrid_trainer`
- `rl.orchestrator_worker`
- `trading/trader.py`
- portfolio monitors
- trainer prediction monitors
- `monitor_trainer_prices.py`
- Redis read-only evidence
- logs/audit packets
- config.py symbol behavior
- secret/config key names only, never values

## Mandatory legacy components to preserve/map

Ingestors / feature path:
- live_binance.py
- live_kucoin.py
- live_coinank.py
- live_binance_liquidations.py
- liquidation_bridge.py
- liquidation_levels_engine.py
- realtime_price_provider.py
- live_coinank_global_aggregator.py
- ingest.live_coinapi_wsds
- ingest.live_coinapi_v1
- ohlcv_resampler_hotfix.py
- feature_pipeline.py
- live_technical_analysis.py

Trainer/orchestrator/trader:
- rl.hybrid_trainer
- rl.orchestrator_worker
- trading/trader.py
- trading/trader-asjad.py if applicable
- monitor_portfolio_primary.py
- monitor_portfolio_asjad.py
- monitor_trainer_predictions.py
- monitor_trainer_prices.py

## Special preservation rules

### live_coinank.py

`live_coinank.py` must be copied as-is and never refactored by default.

Rules:
- no rewrite
- no refactor
- no field changes
- no timing changes
- no request/retry/parsing/output/symbol behavior changes
- wrapper/adapters only unless explicit parity tests + Codex review + human approval

### config.py symbols

Current legacy config symbols are the active legacy subset, not the full V2 universe.

V2 must:
- preserve the 25 active subset behavior
- support Binance USD-M as primary futures universe
- use CoinAnk as discovery/alias evidence
- normalize KuCoin/CoinAPI/Binance/CoinAnk symbols cautiously
- never confuse USD-M, COIN-M, USDC, dated contracts, or spot-like symbols

### GPU trainer

Trainer must not become a basic replacement.

V2 must preserve:
- GPU assumptions
- batching
- checkpoint/model loading
- hybrid trainer behavior
- prediction/proposal flow
- reward/confidence lessons
- worker liveness behavior

V2 must fix:
- process alive but prediction worker dead
- missing prediction_id
- missing feature_snapshot_id
- missing confidence attribution
- stale/missing feature awareness
- weak liveness monitoring

## Required MVP sequence

The planner must prioritize this exact MVP path:

1. `TRAINER_PREDICTION_OUTPUT_MVP`
2. `ORCHESTRATOR_DECISION_MVP`
3. `RISK_GATEWAY_DEFAULT_DENY_MVP`
4. `PAPER_EXECUTION_LEDGER_MVP`
5. `REPLAY_BACKTEST_RUNNER_MVP`
6. `PAPER_MODE_MVP`
7. `SHADOW_MODE_READINESS`
8. `V2_BACKTEST_AND_PAPER_MVP_READY`

## Approved parallel lanes

Claude/Codex may work in parallel only inside these lanes:

### Lane A — paper_backtest_mvp

Highest priority.

Allowed:
- trainer prediction output
- orchestrator decision
- risk gateway
- paper execution ledger
- replay/backtest runner
- paper mode
- shadow readiness

### Lane B — explainability_ui

Allowed only when tied to real data contracts.

Allowed:
- feature-to-confidence explanation
- trainer confidence UI
- symbol selection reason UI
- risk decision UI
- paper/shadow comparison UI
- audit timeline UI

Forbidden:
- cosmetic-only website work
- fake reasoning
- frontend polish without real backend contract

### Lane C — codex_watchdog

Allowed:
- diagnose/fix non-live blockers
- fix human_attention_required
- fix path/materialization errors
- fix stale queue/current_status
- fix evidence wires
- run Codex autofix/re-review
- harden tests

### Lane D — legacy_parity

Allowed:
- read-only legacy audit
- ingestor parity mapping
- trainer parity mapping
- config/symbol behavior mapping
- no mutation

## Task generation rule

Every generated task must include:

- lane
- mvp_relevance
- blocked_by
- next_gate

If a task cannot explain how it advances `V2_BACKTEST_AND_PAPER_MVP_READY`, it must be rejected as drift.

## Codex authority

Codex has full authority to fix all non-live blockers inside AI BOT REBUILD.

Codex may:
- inspect status
- inspect logs/stdout/stderr
- inspect task definitions
- recover path/materialization mismatches
- patch V2 code/tests/docs
- patch planner/supervisor/watchdog tools
- validate
- secret scan
- commit/push
- rerun Codex reviews
- restart planner when clean

Codex must stop only for:
- final live approval
- legacy mutation
- Redis write/delete
- live service restart
- exchange/order/leverage/margin action
- deployment/production migration
- secret exposure
- ambiguous trading/business decision

## Legacy monitor/audit usage

Every V2 build milestone must state:

- what legacy evidence was consulted
- what legacy behavior is preserved
- what legacy failure is being fixed
- what V2 proof will validate the fix

## Website visibility

The new website must eventually show:

- feature_snapshot_id
- prediction_id
- signal_id
- risk_decision_id
- execution_intent_id
- paper_trade_id
- shadow_decision_id
- confidence changes
- top positive/negative feature contributors
- stale/missing/unused feature flags
- why a symbol was selected
- why a trade was opened/closed/blocked/hedged
- risk checks
- paper/backtest/shadow PnL
- legacy vs V2 comparison
- live gate blocked status

## Stop condition

The normal automation endpoint is:

`FINAL_LIVE_GATE_REQUIRES_HUMAN_APPROVAL`

Until then, Codex/Claude must continue non-live build/review/recovery.

REQ_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET_READY
