# Phase 2B Binance USD-M Correction Review

Result: PASS

Reviewed only:
- v2/backend/app/domain/symbols
- v2/backend/app/adapters/symbol_sources
- v2/backend/tests/unit/symbol_universe
- v2/backend/tests/fixtures/symbol_universe
- claude_worklog/phase2_core_rebuild/symbol_universe

Findings:
- USD-M is primary in the correction docs and implementation path. `BinanceUsdMFuturesSource` exists and uses `/fapi/v1/exchangeInfo`.
- COIN-M remains a separate optional adapter through `BinanceCoinMFuturesSource` and `/dapi/v1/exchangeInfo`; it is not used as the legacy active-symbol mapping.
- Legacy active symbols such as `BTCUSDT` map to Binance USD-M identities with canonical IDs like `BINANCE-USDM-BTC-USDT-PERP`.
- USD-M and COIN-M identities do not collapse: matching checks contract family, contract type, and settlement asset; tests cover USD-M BTCUSDT versus COIN-M BTCUSD_PERP.
- Unit tests use local JSON fixtures and do not call `fetch_exchange_info`; static scan found network calls only inside adapter fetch methods, not in tests.
- No Redis write/delete usage found in the reviewed scope.
- No secret values or API keys found in the reviewed scope.
- `git diff --name-only HEAD -- .` showed no tracked file changes, so no legacy tracked files are modified by this correction. One unrelated untracked supervisor task file exists outside the reviewed inputs.

Verification:
- `pytest -q v2/backend/tests/unit/symbol_universe` failed because `pytest` was not on PATH.
- `.venv/bin/pytest -q v2/backend/tests/unit/symbol_universe` failed because `v2` was not on `PYTHONPATH`.
- `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe` passed: 15 passed in 0.02s.
