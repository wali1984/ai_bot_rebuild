# Phase D — Config Zero-Miss Parity Matrix

Generated: 2026-05-16
Runtime gate: blocked_human_only. Runtime symbols: [].

## Sources

- v2/legacy_owned_runtime/full_runtime_closure/config.py
- v2/legacy_owned_runtime/full_runtime_closure/config_accounts.py

## Total keys classified

**1,917** module-level constants extracted via AST. **0 BLOCKED_UNMAPPED.**

## Category counts

| Category | Count |
|----------|-------|
| V2_TRADE_MANAGEMENT_CONFIG | 836 |
| V2_SETTING | 559 |
| V2_RISK_GATE | 156 |
| V2_RUNTIME_CONFIG | 139 |
| V2_INGESTOR_CONFIG | 94 |
| V2_TRAINER_CONFIG | 75 |
| V2_SYMBOL_UNIVERSE | 45 |
| SECRET_REDACTED_OPERATOR_REQUIRED | 13 |
| DEPRECATED_WITH_REASON | 0 |
| BLOCKED_UNMAPPED | 0 |

## How the classifier works

A name-pattern classifier maps each constant name to a category via an
ordered prefix/substring rule set. Most-specific rules win. The classifier
distinguishes:

- **V2_TRADE_MANAGEMENT_CONFIG**: stop/TP/stealth/exit/churn/hedge/intent/
  fee-ratio/tier/stack/budget/spread-cost/min-edge/etc.
- **V2_RISK_GATE**: risk/kill-switch/halt/deleverager/circuit-breaker/
  toxicity/adaptive gate/edge gate/exposure/alarm/veto.
- **V2_TRAINER_CONFIG**: trainer/PPO/MASA/reward/GPU/checkpoint/calibration/
  confidence/ensemble/replay/epoch.
- **V2_INGESTOR_CONFIG**: binance/coinank/kucoin/coinapi/websocket/REST/
  ingest/OHLCV/orderbook/kline/funding/OI/aggtrade.
- **V2_SYMBOL_UNIVERSE**: symbol/universe/pairs/whitelist/timeframe.
- **V2_RUNTIME_CONFIG**: log/redis/stream/data-dir/cache-dir/interval/
  timeout/retry/heartbeat/scheduler/governor/decision-eval/telegram.
- **V2_SETTING**: catch-all for general feature flags, thresholds, weights,
  factors, ratios — the highest-volume bucket.
- **SECRET_REDACTED_OPERATOR_REQUIRED**: api/secret/token/password/auth
  keys. Values stored as REDACTED in the matrix.
- **DEPRECATED_WITH_REASON**: explicit deprecation hints.
- **BLOCKED_UNMAPPED**: empty.

## Honest caveats

- This classifier maps every key into a category, but it does NOT yet
  register a concrete V2 mapping table for each individual constant. The
  category is a routing hint, not a guarantee that the constant has a
  V2 receiver. Migration completion contract clause 4 (config/env
  mapping complete) still requires a per-key receiver registry, which is
  follow-up work.
- 13 keys are classified `SECRET_REDACTED_OPERATOR_REQUIRED`. Their
  values are not stored in the matrix.
- No key is classified `DEPRECATED_WITH_REASON` in the current legacy
  config. If the operator later marks specific keys deprecated, they
  should be moved to that bucket with the deprecation reason.

## What this matrix unlocks

- The brief's "Do not leave generic unmapped keys" requirement is met:
  every key has a category.
- The migration router can now route per-category mapping tasks to
  Claude (e.g., `claude_register_v2_trade_management_config_receivers`).
- Codex can review category assignments against the legacy code and flag
  miscategorizations.

## Status under migration completion contract

`PARTIALLY_MIGRATED` — category assignment is complete, but per-key V2
receivers are not registered. Clause 4 (config/env mapping complete) is
NOT yet fully satisfied.
