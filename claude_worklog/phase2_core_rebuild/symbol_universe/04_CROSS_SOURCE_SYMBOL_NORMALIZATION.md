# Cross-Source Symbol Normalization

V2 uses stable canonical symbol identities and source-specific aliases.

Canonical fields include:
- `canonical_symbol_id`
- `base_asset`
- `quote_asset`
- `settlement_asset`
- `market_type`
- `contract_family`
- `contract_type`
- `exchange`
- `source`
- `source_symbol`
- `source_pair`
- `legacy_symbol`
- `normalization_confidence`
- `alias_set`
- `status`
- `last_seen_ts`
- `metadata`

Rules:
- Do not assume one symbol string is universal.
- Do not collapse perpetual and quarterly/delivery contracts.
- Binance USD-M is the primary Binance futures universe for the current V2 rebuild.
- Binance COIN-M is optional/future adapter support only.
- Do not collapse inverse COIN-M and linear USD-M contracts.
- Preserve CoinAnk aliases while keeping `live_coinank.py` copied as-is.
- Support KuCoin and CoinAPI aliases through registry adapters.

CROSS_SOURCE_SYMBOL_NORMALIZATION_READY
