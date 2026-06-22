# Codex Review: V2 Per-Symbol Liquidation Source Ingestor And Aggregator

Generated: `2026-05-17T23:16:46Z`

GO/NO-GO: `V2_PER_SYMBOL_LIQUIDATION_SOURCE_CODEX_PASS_BLOCKED_OPERATOR_DECISION`

## Decision

Codex passes the packet at the blocked-operator-decision scope. The state is honest: V2 has a documented public Binance Futures force-order WSS path, but no operator-approved V2-owned continuous WebSocket client is implemented or running. No per-symbol liquidation events were synthesized.

This review does not approve an external feed, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Source State

Current packet truth:

- `GO_NO_GO.md`: `V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED`
- `source_classification`: `V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED_BY_OPERATOR_DECISION`
- `operator_decision_required=true`
- `public_no_credential_path_known=true`
- `V2_LIQUIDATION_WSS_OPT_IN` is not set true in the current environment.

The source classifier in `v2/backend/app/services/native_ingestors/liquidations.py` performs no network I/O. It documents the public WSS path and blocks by default until operator approval scopes a V2-owned client.

## Redis Verification

After a one-shot V2 status run, Redis contains exactly the heartbeat key under the liquidation namespace:

- `v2:market:liquidations:heartbeat`

No per-symbol liquidation event/snapshot/aggregate keys are populated:

- `v2:market:liquidations:latest:*`: none
- `v2:market:liquidations:aggregate:*`: none
- `v2:market:liquidations:{symbol}` keys: none

The heartbeat payload reports:

- `go_no_go=V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED`
- `source_classification=V2_PER_SYMBOL_LIQUIDATION_SOURCE_BLOCKED_BY_OPERATOR_DECISION`
- `symbols_with_any_v2_liquidation_key_populated_count=0`
- `writes_legacy_redis=false`
- `writes_exchange_orders=false`
- `no_synthetic_liquidation_events=true`

The only Redis write path found in reviewed source is guarded to `v2:market:liquidations:heartbeat`.

## Aggregator Wiring

The liquidation observation aggregator is forward-compatible:

- With no per-symbol data, the four per-symbol slots remain explicit missing:
  - `latest_liquidation_notional`
  - `latest_liquidation_side_long`
  - `latest_liquidation_side_short`
  - `liquidation_notional_1h_proxy`
- With simulated in-memory per-symbol data in tests, those four slots fill from `V2_MARKET_LIQUIDATIONS_LATEST` and `V2_MARKET_LIQUIDATIONS_AGGREGATE`.
- The source-availability flag is `0.0` / `V2_PROBE_FLAG_NO_PER_SYMBOL_LIQUIDATION_AGGREGATOR_PRESENT` when keys are absent and `1.0` / `V2_MARKET_LIQUIDATIONS_PER_SYMBOL_PRESENT` only when real per-symbol data is provided.

Current refreshed aggregator status remains `24/36` across three symbols, so no hidden 36/36 liquidation parity is claimed.

## Runtime And Safety

- Continuous remediation governor remains `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`.
- 6h soak remains passed.
- V2/remediation processes remain running.
- No `v2_liquidation_ingestor_loop`, `forceOrder`, `fstream.binance`, or WebSocket process is running.
- No legacy process was stopped.
- No legacy path was modified.

Safety state:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Validation

- Focused tests: `18 passed`
  - `test_v2_liquidation_ingestor_loop.py`
  - `test_v2_liquidation_observation_aggregator.py`
- `py_compile`: PASS for liquidation source, ingestor CLI, observation aggregator, and aggregator CLI.
- WebSocket/network-client scan: PASS, no implemented or running WSS client found.
- Redis namespace scan: PASS, heartbeat only; no per-symbol keys faked.
- Old Redis write scan: PASS; no unsafe non-`v2:` writes found.
- Exchange mutation scan: PASS.
- Approval/live/shutdown drift scan: PASS.
- Raw secret scan: PASS.
- Torch/pickle load scan: PASS.
- `git diff --check`: PASS for reviewed files/artifacts.

## Remaining Blocker

The operator still must explicitly approve and scope a V2-owned Binance Futures force-order WebSocket client before per-symbol liquidation ingestion can be implemented. Until then, the correct state remains blocked by operator decision.

## Final Decision

`V2_PER_SYMBOL_LIQUIDATION_SOURCE_CODEX_PASS_BLOCKED_OPERATOR_DECISION`
