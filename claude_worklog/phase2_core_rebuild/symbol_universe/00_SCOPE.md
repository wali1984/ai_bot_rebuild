# Phase 2B Symbol Universe Scope

Phase 2B builds the local, non-live symbol universe foundation. It does not limit V2 to the current legacy `config.py` symbols.

Scope:
- Discover all Binance USD-M futures symbols from exchange-info payloads as the primary Binance futures universe.
- Retain Binance COIN-M futures as optional/future adapter support only.
- Represent future USD-M, KuCoin, CoinAnk, CoinAPI WS, and CoinAPI REST sources through adapter interfaces.
- Preserve the current legacy configured symbols as active/trusted subsets, not as the full universe.
- Normalize source-specific aliases into canonical symbol identities.
- Provide a state machine, manual overrides, scoring inputs, and hot-reload contracts.

Safety:
- No legacy bot mutation.
- No legacy config mutation.
- No preserved ingestor mutation.
- No live ingestor execution.
- No Redis writes or deletes.
- No live trading enablement.
- Tests use fixtures only.

PHASE2_SYMBOL_UNIVERSE_SCOPE_READY
