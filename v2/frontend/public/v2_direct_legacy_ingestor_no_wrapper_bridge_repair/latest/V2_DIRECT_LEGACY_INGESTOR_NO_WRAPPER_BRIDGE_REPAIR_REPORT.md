# V2 Direct Legacy Ingestor No Wrapper Bridge Repair Report

Gate: `V2_DIRECT_LEGACY_INGESTOR_NO_WRAPPER_BRIDGE_REPAIR_READY`
Generated EST: `2026-06-09T18:41:55-04:00`
Live gate: `enabled_operator_approved`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Live submit blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`

## Result

CoinAnk is no longer running through the V2 CoinAnk/liquidation bridge lane. It now runs the direct legacy-owned scripts:

- `v2/legacy_owned_runtime/ingest/live_coinank.py`
- `v2/legacy_owned_runtime/ingest/live_coinank_global_aggregator.py`

Liquidation current runtime is direct V2 WSS plus levels engine, not an ingestor bridge:

- `ai-bot-v2-liquidation-wss-paper-shadow.service`
- `ai-bot-v2-liquidation-levels-engine.service`
- `ai-bot-v2-liquidation-runtime-status-publisher.service`

## Current Runtime

- CoinAnk classification: `DIRECT_COINANK_RUNTIME_OK`
- CoinAnk runtime mode: `DIRECT_LEGACY_OWNED_COINANK_INGESTORS_NO_V2_BRIDGE_WRAPPER`
- CoinAnk ingestor bridge active: `False`
- Liquidation classification: `LIQUIDATION_RUNTIME_OK`
- Liquidation runtime mode: `DIRECT_V2_LIQUIDATION_WSS_AND_LEVELS_RUNTIME`
- Liquidation ingestor bridge active: `False`
- Liquidation events XLEN: `10007`
- Liquidation levels symbols covered: `123`

## Masked Bridge Units

- `ai-bot-v2-coinank-global-bridge-loop.service`
- `ai-bot-v2-liquidation-bridge.service`
- `ai-bot-v2-liquidation-bridge-status-publisher.service`

`ai-bot-v2-trainer-bridge.service` remains enabled because it is not a market ingestor lane.

## Website Sync

Updated current website/runtime surfaces to show direct CoinAnk and direct liquidation runtime truth. The script monitor now excludes retired ingestor bridge CLIs from current worker enumeration and reads the current runtime-truth live gate instead of the old static `blocked_human_only` fallback.

## Validation

- py_compile: `PASS`
- backend focused tests: `PASS: 7 passed`
- frontend typecheck: `PASS`
- frontend build: `PASS`
- stale active ingestor bridge scan: `PASS`
- local route probe: `PASS`
- production route probe: `PASS`
- production bundle hash matches local: `PASS`

## Safety

No real order/test-order/cancel/modify was performed. No leverage or margin mutation, old Redis write, legacy restart, Redis trim, or raw credential output was performed.
