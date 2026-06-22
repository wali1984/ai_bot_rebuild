# Publisher Proof Blockers: 20260612_215709

Generated: `2026-06-12`

Scope: paper-only trusted publisher proof attempt against current Redis.

## Result

| Field | Value |
|---|---:|
| Command | `./run_trusted_prediction_publisher_once --redis-url redis://127.0.0.1:6379/0 --paper-only --no-live` |
| Output directory | `publisher_proof/20260612_215709` |
| Proof exit | `1` |
| Status | `BLOCKED` |
| Block reason | `NO_SYMBOL_WITH_CANONICAL_CLOSED_CANDLE_COVERAGE` |
| Routes to live | `false` |
| Live order allowed | `false` |

## Redis keys checked

| Pattern | Count |
|---|---:|
| `v2:market:ohlcv_closed:binance:*:1m` | `0` |
| `v2:market:ohlcv_closed:binance:*:5m` | `0` |
| `v2:market:ohlcv_closed:binance:*:15m` | `0` |
| `v2:market:ohlcv_closed:binance:*:1h` | `0` |
| `v2:market:ohlcv_closed:binance:*:4h` | `0` |

Current aggregate checks:

| Pattern | Count |
|---|---:|
| `v2:market:ohlcv_closed:binance:*` | `0` |
| `v2:prediction:*` | `0` |
| `v2:signals:paper:*` | `0` |
| `v2:replay:snapshots:*` | `0` |
| `v2:market:mtf_snapshot:*` | `0` |
| `v2:decision:mtf_snapshot:*` | `0` |
| `v2:mtf_snapshot:*` | `0` |

## Diagnosis

| Question | Answer |
|---|---|
| Is the one-shot publisher command present? | Yes. `run_trusted_prediction_publisher_once` exists and is paper-only/no-live gated. |
| Is the trusted publisher path usable? | Yes in unit coverage. It writes an MTF snapshot, replay snapshot, and `v2:prediction:{symbol}:{timeframe}` when canonical closed-candle coverage exists. |
| Why is `v2:prediction:*` still `0`? | The proof command blocked before prediction construction because no canonical closed-candle keys exist. |
| Why is `v2:replay:snapshots:*` still `0`? | Replay snapshot writing occurs inside `V2HybridPredictionPublisher.publish_prediction`, which was not reached because MTF construction had no candle coverage. |
| Why are MTF snapshot keys still `0`? | The command refuses to write MTF snapshot evidence unless all required closed-candle timeframes are present and valid. |
| Was synthetic evidence used? | No. The command did not fabricate candles or snapshots. |
| Were live orders possible? | No. `routes_to_live=false`, `live_order_allowed=false`, and the command does not call order transport. |

## Responsible files and functions

| File | Function | Role |
|---|---|---|
| `v2/backend/app/cli/run_trusted_prediction_publisher_once.py` | `select_symbol_with_closed_coverage` | Scans canonical closed-candle keys and fails closed when no symbol has required timeframe coverage. |
| `v2/backend/app/cli/run_trusted_prediction_publisher_once.py` | `run_publisher_proof_once` | Builds MTF snapshot and publisher payload only after canonical closed candles are present. |
| `v2/backend/app/services/market_state_integrity/canonical_candles.py` | `build_multi_timeframe_decision_snapshot` | Selects only closed candles and validates shared decision cutoff. |
| `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/publisher.py` | `V2HybridPredictionPublisher.publish_prediction` | Existing trusted path that writes replay snapshot before prediction publication. |
| `v2/backend/app/cli/export_pipeline_trust_evidence.py` | `CATEGORY_PATTERNS["replay_snapshots"]` | Exports `v2:replay:snapshots:*` and MTF snapshot keys when they exist. |

## Minimal fix required

Restore or start the canonical closed-candle writer before re-running publisher proof.

Required runtime precondition:

```text
v2:market:ohlcv_closed:binance:{symbol}:1m  > 0
v2:market:ohlcv_closed:binance:{symbol}:5m  > 0
v2:market:ohlcv_closed:binance:{symbol}:15m > 0
v2:market:ohlcv_closed:binance:{symbol}:1h  > 0
v2:market:ohlcv_closed:binance:{symbol}:4h  > 0
```

Only after that precondition exists should `run_trusted_prediction_publisher_once` emit a fresh v3 prediction, MTF snapshot, and replay snapshot.

## Go/no-go

No-go for live-canary safety pass.

Reason: publisher proof did not produce fresh replayable v3 prediction evidence from real canonical closed candles.
