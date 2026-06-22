# Post-6H Production Equivalence Decision Report

Generated: `2026-05-17T17:11:23Z`

GO/NO-GO: `POST_6H_PRODUCTION_EQUIVALENCE_OPERATOR_DECISION_REQUIRED`

## Decision

The 6h V2 runtime soak has Codex PASS, but production equivalence and paper-only legacy shutdown are not automatically approved. The current post-6h state is operator-decision-required because:

- no approved checkpoint artifact or sidecar metadata is present in approved V2 local paths;
- the paper-only shutdown limitations acceptance file is absent;
- legacy production processes are still running and still own populated production Redis namespaces;
- the V2-vs-legacy comparator still shows action mismatches driven by deterministic-init checkpoint state.

This packet does not approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, Redis trim, or any approval token.

## Checkpoint Decision

`CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED` remains open.

- Approved local checkpoint candidates in `.local_models/`, `.local_secrets/`, and `v2/runtime/`: `0`
- Operator paper-only limitations acceptance file exists: `false`
- V2 checkpoint parity claimed: `false`
- Raw legacy checkpoint loaded by V2: `false`

Required operator path:

1. Provide an approved checkpoint artifact plus sidecar metadata for Codex shape/security review, or
2. explicitly accept deterministic-init / no-trained-checkpoint limitations for paper-only shutdown evaluation using `claude_worklog/approvals/OPERATOR_ACCEPTS_V2_PAPER_ONLY_SHUTDOWN_LIMITATIONS.md`.

No raw legacy checkpoint may be loaded without a separate Codex review.

## Legacy Production Processes

| Legacy process | Current owner role | V2 equivalent | V2 status | Classification |
| --- | --- | --- | --- | --- |
| `ingest/live_binance.py` | production market ingestion | `v2_native_ingestors_live_loop` | running | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `ingest/live_binance_liquidations.py` | production liquidation ingestion | `v2_native_ingestors_live_loop` | running | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `ingest/live_coinank.py` | production CoinAnk ingestion | `v2_native_ingestors_live_loop` | running | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `ingest/live_kucoin.py` | production KuCoin ingestion | `v2_native_ingestors_live_loop` | running | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `ingest/live_coinapi_v1.py` | production CoinAPI REST ingestion | `v2_native_ingestors_live_loop` | running | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `ingest/live_coinapi_wsds.py` | production CoinAPI WSDS ingestion | `v2_native_ingestors_live_loop` | running | `OPERATOR_DECISION_REQUIRED` |
| `feature_pipeline.py` | production feature generation | `v2_feature_pipeline_native_loop` | running | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `rl.hybrid_trainer` | production trainer / prediction owner | `v2_rl_core_inference_loop` | running | `NOT_SAFE_TO_STOP` |
| `rl.orchestrator_worker` | production orchestration owner | `v2_orchestrator_arbitration_loop` | running | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `monitor_portfolio_primary.py` | production portfolio monitor | `v2_trade_management_paper_loop` + `v2:risk:*` | running / populated | `NOT_SAFE_TO_STOP` |

V2 runtime equivalents are active, but that is not the same as permission to stop legacy. Legacy remains the production reference until checkpoint/limitation decisions and final Codex shutdown review pass.

## Redis Namespace Comparison

No Redis key was trimmed, deleted, or mutated by this packet.

| Legacy namespace | Legacy count | V2 equivalent | V2 count | Decision |
| --- | ---: | --- | ---: | --- |
| `prediction:*` | `151` | `v2:prediction:*` | `3` | `OPERATOR_DECISION_REQUIRED` |
| `features:*` | `5723` | `v2:features:*` | `5` | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `signals:*` | `8` | `v2:signals:*` / `v2:signals:paper` | `1` | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `market:*` | `144` | `v2:market:*` | `11` | `LEGACY_REFERENCE_STILL_REQUIRED` |
| `trainer:*` | `26` | `v2:trainer:*` | `2` | `NOT_SAFE_TO_STOP` |
| `orchestrator:*` | `1` | `v2:orchestrator:*` | `3` | `LEGACY_REFERENCE_STILL_REQUIRED` |

The V2 namespace is populated, but legacy production namespaces remain active. This blocks shutdown unless the operator explicitly accepts the remaining paper-only limitations and Codex later verifies the acceptance gate.

## V2-vs-Legacy Comparison

Comparator payload: `v2/frontend/public/v2_runtime_soak_and_production_equivalence/latest/production_equivalence_comparison.json`

- `schema_version`: `v2_production_equivalence_comparison_v2`
- `no_invented_outcomes`: `true`
- compared symbols: `BTCUSDT`, `ETHUSDT`, `SOLUSDT`

| Symbol | Legacy action | V2 action | Match | Explanation |
| --- | --- | --- | --- | --- |
| `BTCUSDT` | `close_long_open_short` | `hold` | `false` | V2 reports `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`; deterministic-init V2 policy does not match legacy action. |
| `ETHUSDT` | `close_short_open_long` | `hold` | `false` | V2 reports `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`; deterministic-init V2 policy does not match legacy action. |
| `SOLUSDT` | `close_long_open_short` | `hold` | `false` | V2 reports `CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED`; strict paper gate blocks negative after-cost edge with `NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK`. |

The SOLUSDT paper-fill block-reason passthrough remains safe and visible. No paper fill was created from the held SOLUSDT signal.

## Shutdown Recommendation

Current recommendation: `OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN`.

Shutdown is not safe from this packet. The required next decision is one of:

- provide an approved compatible checkpoint artifact and sidecar metadata for Codex review, or
- explicitly accept deterministic-init / no-trained-checkpoint limitations for paper-only shutdown evaluation.

Even after operator acceptance, a separate Codex review must pass before any shutdown-safe output is allowed.

## Safety

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
- exchange mutation scan: no hits in reviewed V2 runtime loops
- old Redis write scan: active V2 writers are guarded to `v2:` keys
- approval scan: no live/canary/shutdown/Redis-trim approval found for this gate
- legacy modified by this packet: `false`
- legacy stopped by this packet: `false`

## Final Decision

`POST_6H_PRODUCTION_EQUIVALENCE_OPERATOR_DECISION_REQUIRED`
