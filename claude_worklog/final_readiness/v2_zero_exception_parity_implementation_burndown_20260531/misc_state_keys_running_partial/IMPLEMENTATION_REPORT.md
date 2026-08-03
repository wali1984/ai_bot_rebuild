# V2 Running Partial Fix — Misc State Keys

Generated EST: 2026-06-03T18:38:54-0400  
Generated UTC: 2026-06-03T22:38:54Z  
LIVE_GATE: blocked_human_only | live_symbols: [] | exchange mutation: none

## Implemented

Added `v2/backend/app/cli/v2_misc_state_keys_publisher.py` to materialize V2 replacements for the legacy misc/state key family:

- `config:symbols` -> `v2:symbol_universe:contract`
- `market:state` -> `v2:market:state`
- `market:{SYMBOL}` -> `v2:market:state:{symbol}`

Added website Redis bridge contracts for:

- `v2_market_state`
- `v2_symbol_universe_contract`

The publisher reads only `v2:` market/symbol state, writes only `v2:` keys, and has no exchange/network/trading path.

## Evidence

Command:

```bash
PYTHONPATH=$PWD ./.venv/bin/python3 -m v2.backend.app.cli.v2_misc_state_keys_publisher --write-v2-redis --write-evidence
```

Result:

- `classification=V2_MISC_STATE_KEYS_PUBLISHED`
- `v2_keys_written_count=29`
- `v2:symbol_universe:contract` = 1
- `v2:market:state` = 1
- `v2:market:state:*` = 27
- public payload: `v2/frontend/public/operator_runtime/v2_misc_state_keys/latest/v2_misc_state_keys_status.json`

## Safety

- No old Redis keys written.
- No live/canary/shutdown enabled.
- No exchange order/cancel/leverage/margin path exists in the publisher.
