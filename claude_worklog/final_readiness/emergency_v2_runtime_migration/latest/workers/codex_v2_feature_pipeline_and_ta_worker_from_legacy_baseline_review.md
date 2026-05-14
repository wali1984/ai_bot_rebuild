# Codex Review: V2 Feature Pipeline + TA Worker From Legacy Baseline

Result: CODEX PASS  
Reviewed: 2026-05-14  
Live gate: `blocked_human_only`

I did not touch `/home/wali/Desktop/AI BOT`, did not write old Redis, did not call exchange mutation APIs, and did not change leverage or margin.

## Validation Performed

- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/integration/cli/test_v2_feature_pipeline_and_ta_worker.py`
  - Result: `16 passed in 0.10s`.
- `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m v2.backend.app.cli.v2_feature_pipeline_and_ta_worker --verify-baseline-shas`
  - Result: `ok: true`, five checked baseline SHAs, no mismatches.
- `python3 -m json.tool` on the worker status JSON and legacy behavior mapping JSON.
  - Result: both valid JSON.
- AST/source scan of the reviewed CLI and service.
  - Result: no Redis imports and no Redis write or exchange mutation attribute calls in `v2_feature_pipeline_and_ta_worker.py` or `feature_pipeline_and_ta/service.py`.
- Data-plane/status inspection.
  - Result: three worker data-plane keys, all under `v2:features:*`.

## Gate Results

| Gate | Result | Evidence |
|---|---:|---|
| TA indicator set preserved or removals explained | PASS | V2 implements `RSI`, `MACD`, `ATR`, `SMA`, `EMA`; the remaining TA families are listed in `LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON` with per-family reasons. Tests assert implemented plus deferred equals the reviewed TA whitelist. |
| Universe-validation retry window | PASS | Legacy startup uses `STARTUP_VALIDATE_RETRIES=${STARTUP_VALIDATE_RETRIES:-10}` and `STARTUP_VALIDATE_SLEEP_SEC=${STARTUP_VALIDATE_SLEEP_SEC:-15}`. V2 constants and payload surface `startup_validate_retries=10` and `startup_validate_sleep_sec=15`; retry orchestration remains supervisor-owned. |
| Paralysis detector alerts via V2 payload | PASS | Sustained bucket detection routes to `paralysis_detector.result.alerts` in the public/status payload. No legacy Redis alert stream is emitted by this worker. |
| SHA256 citations | PASS | The five embedded baseline SHAs match `copied_baseline_manifest.json` for `feature_pipeline.py`, `ohlcv_resampler_hotfix.py`, `ingest/live_technical_analysis.py`, `scripts/validate_symbol_universe_data.py`, and `scripts/paralysis_detectors.py`. |
| V2 namespace only | PASS | Data-plane writes are `v2:features:{symbol}:{tf}:unified`, `v2:features:{symbol}:{tf}:ta`, and `v2:features:{symbol}:{tf}:ohlcv_resampled`. |
| Live safety | PASS | `live_gate` and `current_gate_state` remain `blocked_human_only`; no order, cancel, leverage, or margin mutation methods are present. |

## Symbol Universe Gate

Result: PASS with evidence gap.

The worker checks V2 public symbol-universe payload candidates first, then falls back to the V2 `SymbolUniverseService` contract. The public payload is currently absent and is surfaced explicitly as `MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD`; this is an evidence gap, not a replacement with hardcoded truth.

The worker payload distinguishes all required symbol scopes:

- `legacy_active_symbols`
- `discovered_symbols`
- `observed_symbols`
- `training_symbols`
- `paper_symbols`
- `live_blocked_symbols`

No hardcoded current 25-symbol universe was found. The CLI has a single `BTCUSDT` default/fallback, but it does not claim that as the full universe. The worker does not train or trade all discovered symbols automatically: `training_symbols` and `paper_symbols` remain separate, `live_blocked_symbols` is surfaced, and `symbol_scope_policy` is `do_not_train_or_trade_all_discovered_symbols_automatically`.

CoinAnk symbols are not treated as directly tradable. The payload marks `coinank_symbols_tradability` as `market_intelligence_only_until_binance_usdm_confirmed` and keeps `binance_usdm_confirmed_symbols` separate.

## Non-Blocking Evidence Gaps

- The V2 public symbol-universe payload is missing. This should be produced by the symbol-universe owner, but the worker reports the gap rather than hardcoding a universe.
- Extended TA families are deferred rather than computed. This is acceptable for this review because every deferred family has a written reason and test coverage enforces the implemented/deferred registry.
- Several legacy feature families remain deferred to their owning V2 modules: CoinAnk endpoint features, CoinAPI WSDS depth, Binance tape, cross-timeframe context, BTC correlation, and kline taker-buy ratios.

## Decision

PASS for the baseline-port review. This is not a live-trading approval; live remains `blocked_human_only`.
