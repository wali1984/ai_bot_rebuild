# Codex Review: V2 Shadow Observation Outcome Metrics

Generated: `2026-05-19T01:21:10Z`

GO/NO-GO: `V2_SHADOW_OBSERVATION_OUTCOME_METRICS_CODEX_PASS`

## Decision

Codex passes the shadow/no-trade outcome metrics path. The service reads V2-owned shadow/held rows and V2 market/feature/prediction inputs, writes only `v2:paper:shadow_outcome:*`, and does not count shadow or held rows as accepted positions, fills, PnL ledger events, or paper-fill gate openings.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, or legacy shutdown.

## Evidence Reviewed

Reviewed:

- `v2/backend/app/services/paper_shadow_outcome_metrics/service.py`
- `v2/backend/app/cli/v2_paper_shadow_outcome_metrics.py`
- `v2/backend/tests/integration/cli/test_v2_paper_shadow_outcome_metrics.py`
- `claude_worklog/final_readiness/v2_shadow_observation_outcome_metrics/latest/`
- `v2/frontend/public/v2_shadow_observation_outcome_metrics/latest/operator_dashboard_payload.json`
- live Redis keys under `v2:paper:shadow_outcome:*`, plus `v2:paper:positions` and `v2:paper:ledger`

## Source And Write Boundaries

The service reads only the expected V2-owned sources:

- `v2:paper:shadow_observations`
- `v2:paper:intents_held_by_paper_fill_gate`
- `v2:market:prices:{symbol}`
- `v2:features:latest:{symbol}:1m` only when `feature_freshness_state="CURRENT"`
- `v2:prediction:{symbol}:1m`

The service write boundary allows only:

- `v2:paper:shadow_outcome:{symbol}`
- `v2:paper:shadow_outcome:heartbeat`

Codex verified `_safe_redis_set` refuses `v2:paper:positions`, `v2:paper:ledger`, `v2:paper:heartbeat`, old Redis keys, and unrelated namespaces. A live Redis scan after a one-shot run found only:

- `v2:paper:shadow_outcome:BTCUSDT`
- `v2:paper:shadow_outcome:ETHUSDT`
- `v2:paper:shadow_outcome:SOLUSDT`
- `v2:paper:shadow_outcome:heartbeat`

## Live Outcome State

After refreshing the one-shot:

| Symbol | Label | Move bps | After cost bps | no_trade_correct | false_block_candidate |
| --- | --- | ---: | ---: | --- | --- |
| `BTCUSDT` | `SHADOW_OUTCOME_ONLY` | `0.0` | `-10.0` | `true` | `false` |
| `ETHUSDT` | `SHADOW_OUTCOME_ONLY` | `0.0` | `-10.0` | `true` | `false` |
| `SOLUSDT` | `HELD_OUTCOME_ONLY` | `null` | `null` | `null` | `null` |

BTCUSDT and ETHUSDT classifications are based on actual V2 current price and the shadow entry price from V2 provenance. In the current sample, gross move is `0.0` bps and round-trip cost makes after-cost move `-10.0` bps, so `no_trade_correct=true` and `false_block_candidate=false`.

SOLUSDT remains held-only with missing entry flags. It does not become a fill and does not produce MFE/MAE/ROE.

## Safety Invariants

Every emitted outcome row carries:

- `counted_as_accepted_position=false`
- `counted_as_fill=false`
- `affects_pnl_ledger=false`
- `opens_paper_fill_gate=false`
- `places_real_order=false`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

The live `v2:paper:positions` key remains an empty accepted-position list, and `v2:paper:ledger` still reports `accepted_position_count=0`, `shadow_observation_count=2`, and `held_position_count=1`. The shadow outcome one-shot did not modify accepted positions, ledger, or paper heartbeat.

## Recorder Isolation

Codex verified the accepted-position recorder and full-observation path do not import or read `paper_shadow_outcome_metrics` / `v2:paper:shadow_outcome:*`.

Refreshed recorder state remains:

- state counts: `FLAT=3`
- `symbols_with_entry_recovered=[]`
- `symbols_still_blocked=["BTCUSDT", "ETHUSDT", "SOLUSDT"]`

This proves shadow/held rows are not feeding accepted-position MFE/MAE/ROE.

## Runtime Governors

The runtime governors remain ready:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- V2/remediation processes: `13/13`
- 6h soak remains passed.
- full observation remains `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`
- generated dims remain `BTCUSDT=151`, `ETHUSDT=151`, `SOLUSDT=145`

No checkpoint compatibility or policy architecture parity claim was found in the reviewed service/status path; the packet report explicitly keeps both false.

## Validation

- Shadow outcome one-shot: PASS.
- Focused shadow outcome tests: `17 passed`.
- Related isolation sweep: `46 passed`.
- `py_compile`: PASS.
- JSON validation: PASS.
- Raw secret scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Approval drift scan: PASS.
- `git diff --check`: PASS for reviewed artifacts.

Residual note: tests cover long-side favorable/adverse classification and the current live rows are long/held. Add a short-side classification test before using these metrics for aggregate model-training decisions.

## Final Decision

`V2_SHADOW_OBSERVATION_OUTCOME_METRICS_CODEX_PASS`
