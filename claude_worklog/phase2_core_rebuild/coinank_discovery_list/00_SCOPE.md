# Phase 2D CoinAnk Discovery List Scope

Phase 2D adds the uploaded CoinAnk symbol list as a non-live discovery/alias source for the V2 symbol universe.

It does not change the legacy ingestor `live_coinank.py`.
It does not promote any CoinAnk symbol to a tradable identity.
It does not call any live API.
It does not write Redis.

Scope:
- Preserve raw CoinAnk rows verbatim with original keys `symbol`, `baseCoin`, `exchangeName`, `expireAt`, `updateAt`.
- Classify each row deterministically (Chinese-name, stock/commodity-like, dated, USD perp inverse, USDC, USDT, candidate for confirmation).
- Emit V2 `SymbolIdentity` instances for CoinAnk only as `discovery_only` records with normalization confidence LOW.
- Provide a confirmation helper that maps a CoinAnk discovery record to a Binance USD-M canonical identity only when Binance USD-M independently confirms the symbol.
- Provide a fixture-only synthetic dataset that exercises every rule.
- Provide an ODT-to-fixture converter tool that the user runs locally to ingest the uploaded `coinanksymbols.odt`.

Out of scope:
- Live CoinAnk API calls (preserved legacy `live_coinank.py` only, copy-as-is, untouched).
- Direct trading-universe inclusion of CoinAnk symbols.
- Auto-promotion of any CoinAnk symbol to OBSERVED, TRAINING, or PAPER state without USD-M confirmation.

Safety:
- No legacy bot mutation.
- No legacy ingestor edits.
- No live API calls.
- No Redis writes or deletes.
- No live trading enablement.
- No deployment.
- No production migration.
- No secret access.

PHASE2_COINANK_DISCOVERY_LIST_SCOPE_READY
