# Uploaded List Source Inventory

Source path (user-supplied, outside repo, not committed):
- `/home/wali/Downloads/coinanksymbols.odt`

Format: OpenDocument Text (.odt) expected to contain a single table with column headers `symbol`, `baseCoin`, `exchangeName`, `expireAt`, `updateAt`. Optional columns `productType`, `quoteCoin`, `tradingPair`, `marketType` are preserved when present.

Sandbox-safe ingestion path:
1. The user runs `python3 tools/coinank_uploaded_list_to_fixture.py /home/wali/Downloads/coinanksymbols.odt v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list.json` locally.
2. The user reviews the resulting JSON. Schema must conform to `01_RAW_ROW_SCHEMA.md`.
3. The user commits the fixture if satisfied. The original `.odt` is not committed.

Why the planner does not auto-ingest:
- The Claude Code session sandbox restricts reads outside `/home/wali/Desktop/AI BOT REBUILD`.
- The CoinAnk upload is external evidence; user-confirmed input preserves the evidence integrity rule.
- Synthetic fixture `coinank_uploaded_list_synthetic.json` exercises every classification rule independently, so the test suite never depends on the real upload being present.

Validation post-ingestion:
- Re-run `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe`.
- Spot-check rows: Chinese-name preserved raw, stock-like flagged, BTCUSD_PERP and dated contracts separate, USDC and USDT not collided, only Binance-USDM-confirmed rows eligible for confirmation.
- New `exchangeName` values may be added to `BINANCE_USDM_EXCHANGE_SLUGS` only after evidence and review.

Forbidden:
- Committing the raw `.odt`.
- Calling any CoinAnk live endpoint to refresh the list.
- Using the uploaded list as a tradable universe.

PHASE2_COINANK_UPLOADED_LIST_SOURCE_INVENTORY_READY
