# Test Plan

Tests live in `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`.

Fixtures live in `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json` and reuse `source_symbol_payloads.json` for Binance USD-M comparators.

Tests, one rule each:
- `test_coinank_btcusdt_is_discovery_only_with_low_confidence`: LOW confidence, discovery_only status, unknown contract_family, candidate flag true, COINANK-DISC- canonical prefix.
- `test_coinank_btcusdt_does_not_collapse_with_usdm_btcusdt`: cross-source match returns `none`.
- `test_coinank_btcusd_perp_marked_inverse_and_does_not_collapse_with_usdm`: inverse flag true, candidate flag false, no collapse.
- `test_coinank_dated_does_not_collapse_with_perpetuals`: dated flag true, contract_type=`dated_delivery`, candidate flag false.
- `test_coinank_usdc_separate_from_usdt`: distinct quote_assets, distinct canonical ids, no collapse.
- `test_ethbtc_not_usdm_candidate`: quote_asset=BTC, candidate flag false.
- `test_stock_like_marked_and_blocked_from_confirmation`: stock_like flag true, confirmation returns None.
- `test_chinese_name_preserved_and_blocked_from_confirmation`: Chinese-name flag true, raw `baseCoin` preserved verbatim, base_asset hashed CJK token, candidate flag false.
- `test_confirmation_requires_usdm_present_and_trading`: confirmation returns USD-M identity only when present and trading; settling/missing returns None.
- `test_adapter_emits_identities_with_alias_set`: every emitted identity has its canonical id in alias_set.
- `test_adapter_confirm_against_usdm_returns_only_valid_matches`: BTC USDT row confirms; ETHBTC row does not.

Run command:
`PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe`

Network discipline:
- No urllib/requests/aiohttp call paths reachable from the test code.
- Adapter `from_payload` accepts in-memory payloads only; the `fetch_exchange_info` Binance USD-M path is not invoked.
- Synthetic fixture is the only data source; real CoinAnk upload is not required to exist.

PHASE2_COINANK_TEST_PLAN_READY
