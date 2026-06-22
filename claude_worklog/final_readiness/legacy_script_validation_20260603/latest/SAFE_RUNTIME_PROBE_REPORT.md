# Legacy Safe Runtime Probe Report

Generated UTC: 2026-06-04T00:31:00Z
Overall status: `ok`
Scope: bounded probes only for V2-covered legacy ingestors and V2 native replacements.

## Probe Results
- `legacy_adapter_kucoin_one_cycle`: `ok` (returncode=0, elapsed=32.658s)
- `legacy_adapter_coinapi_v1_bounded`: `ok` (returncode=0, elapsed=20.416s)
- `v2_kucoin_native_public_rest`: `ok` (returncode=0, elapsed=5.36s)
- `v2_coinank_global_bridge_once`: `ok` (returncode=0, elapsed=0.061s)
- `v2_misc_state_keys_publisher`: `ok` (returncode=0, elapsed=0.061s)

## Redis Evidence
- `v2:coinank:global:*`: 12
- `v2:features:global_coinank:*`: 11
- `v2:features:kucoin:*`: 117
- `v2:kc:*`: 150
- `v2:latest:coinapi:ohlcv:*`: 6
- `v2:market:coinank:global:*`: 11
- `v2:market:kucoin:*`: 109
- `v2:market:state`: 1
- `v2:market:state:*`: 27
- `v2:normalized:ohlcv:*`: 6
- `v2:ohlcv:list:coinapi:*`: 6
- `v2:symbol_universe:contract`: 1

## Safety
- Exchange probes were read-only.
- Legacy Redis writes were only allowed through the V2 prefixing adapter.
- LIVE_GATE remained `blocked_human_only`; `live_symbols=[]`.
