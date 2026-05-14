# v2_feature_pipeline_and_ta_worker — Legacy-Baseline Port Report

**Task:** `claude_port_v2_feature_pipeline_and_ta_worker_from_legacy_baseline`
**Lane:** runtime_migration
**Worker ID:** `v2_feature_pipeline_and_ta_worker`
**Live gate:** `blocked_human_only` (immutable from this worker)
**Status:** EMITTED, pending Codex review.

## What was emitted

| Output file | Role |
|---|---|
| `v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py` | CLI entrypoint (`python3 -m v2.backend.app.cli.v2_feature_pipeline_and_ta_worker --loop --interval 10 --symbol BTCUSDT --timeframe 1m`). Reads a snapshot input (file or public Binance REST GET), invokes the service, writes V2 status payload + V2 data-plane file. |
| `v2/backend/app/services/feature_pipeline_and_ta/service.py` | Pure service: `FeaturePipelineAndTAService` with five legacy-baseline-anchored methods (unified-features, TA indicators, OHLCV resampler, universe validator, paralysis detector). No legacy Redis writes. |
| `v2/backend/tests/integration/cli/test_v2_feature_pipeline_and_ta_worker.py` | All required tests + extra coverage. |
| `v2/frontend/public/operator_runtime/v2_feature_pipeline_and_ta_worker/latest/v2_feature_pipeline_and_ta_worker_status.json` | Seeded public payload for the operator dashboard. |
| `..._LEGACY_BASELINE_ANALYSIS.md` | Legacy-anchored analysis with SHA citations. |
| `..._legacy_behavior_mapping.json` | Machine-readable legacy → V2 mapping. |
| `..._status.json` | Worker status (sibling to this file). |
| `..._report.md` | This file. |

## Legacy baselines anchored

The worker is anchored to five preserved baselines under
`v2/legacy_preserved/startup_baseline/`. SHAs are taken verbatim from
`copied_baseline_manifest.json` and embedded as `LEGACY_BASELINE_SHA256`
inside the CLI module:

- `feature_pipeline.py` — `143938e735342179105155a12c50d7c495bdd1c16d570586cb369d03d7d4b2e8`
- `ohlcv_resampler_hotfix.py` — `b83edf60a7d0db51556752cdcf9d713ee9d7175d05b26a6ce6c2235d214f4239`
- `ingest/live_technical_analysis.py` — `5cdd4ea1d43271d0199e1ca92ecad3a8b76308838898a611df6ef4602f7388ac`
- `scripts/validate_symbol_universe_data.py` — `151720d7e9b1c3f9608df6404e20a912da4572dc66078d7cef001bc4ddd5ec07`
- `scripts/paralysis_detectors.py` — `8fd4c4f55ac43e5af07c84cddea04328f7b4e5811a5230442f276caf33fc7c27`

The test `test_baseline_sha256_matches_copied_baseline_manifest_contract`
reads the manifest at test-time and asserts each constant matches; it
also recomputes the SHA against the on-disk preserved file if present.

## TA library used

The legacy TA engine (`legacy_reference/ingest/technical_analysis.py`)
imports `talib` (TA-Lib Python bindings). The V2 worker preserves the
**indicator naming convention** (`ta_RSI_14`, `ta_MACD_12_26_9_*`,
`ta_ATR_14`, `ta_SMA_20`, `ta_EMA_20`) without depending on TA-Lib so the
V2 control-plane venv stays lightweight; numerical values are computed
inline in pure Python. This documented departure satisfies clause (3) of
the LEGACY-FIRST MANDATE.

## Lane configuration (preserved verbatim)

| Lane | Timeframes | Refresh | V2 source |
|---|---|---|---|
| Fast | `1m`, `5m` | 10s | `FAST_LANE_INTERVAL_SEC` |
| Slow | `15m`, `1h`, `4h` | 300s | `SLOW_LANE_INTERVAL_SEC` |

OHLCV resampler runs every 12s with the legacy TF expiry map preserved
verbatim: `5m=600`, `15m=1800`, `1h=7200`, `4h=28800` seconds. Live TA
service cadence is preserved at 60s.

## Universe validation

Default thresholds preserved from
`scripts/validate_symbol_universe_data.py` (env-overridable):

- `VALIDATE_ORDERBOOK_STALE_SEC = 10`
- `VALIDATE_FAST_TF_MAX_AGE_SEC = 90`
- `VALIDATE_SLOW_TF_MAX_AGE_SEC = 600`
- `VALIDATE_MIN_CANDLES = 50`

The startup retry window is preserved from
`legacy_reference/scripts/start_all_services_production.sh`:

- `STARTUP_VALIDATE_RETRIES = 10`
- `STARTUP_VALIDATE_SLEEP_SEC = 15`

Both surface on the public payload under `universe_validation.*`.

## Paralysis detector

Sustained-paralysis logic preserved from
`scripts/paralysis_detectors.py`:

- 1-minute bucketing (`int(ts_ms // 60_000)`).
- Sustained = bucket-coverage(reason) >= `expected_buckets`,
  `expected_buckets = max(1, int(window_minutes))`.
- Default window = `5.0` minutes.

**Routing change (preserved as a documented departure from the LEGACY-FIRST
mandate clause 3):** alerts route into the V2 worker public payload
(`paralysis_detector.result.alerts`) instead of any legacy Redis stream.
Reason: the legacy script writes alerts to the operator's terminal/log only
and explicitly does not emit a Redis stream; the V2 worker formalizes
operator-facing alerts via the public payload exclusively.

## V2 outputs (NEW; `v2:features:*` namespace ONLY)

- `v2:features:{symbol}:{tf}:unified` — unified features (numeric + ts)
- `v2:features:{symbol}:{tf}:ta` — TA indicator hash (preserved naming)
- `v2:features:{symbol}:{tf}:ohlcv_resampled` — OHLCV 6-field + expiry tag

The data plane is persisted as a JSON file under
`v2/runtime/v2_feature_pipeline_and_ta_worker/latest/`. No legacy Redis is
touched.

## Safety contracts (asserted by tests)

1. `live_gate == "blocked_human_only"` — always.
2. No legacy Redis writes — test scans both CLI and service source for the
   ~20 legacy key prefixes the legacy files write.
3. No exchange mutating method invoked.
4. Public REST GETs only.
5. Data-plane keys must start with `v2:features`.
6. `SYMBOL_UNIVERSE_CONTRACT_REQUIRED` — the worker reads symbol scope through
   the V2 `SymbolUniverseService` contract when a public symbol-universe
   payload is absent, classifies that absence as
   `MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD`, and surfaces distinct
   `legacy_active_symbols`, `discovered_symbols`, `observed_symbols`,
   `training_symbols`, `paper_symbols`, `live_blocked_symbols`, and
   `binance_usdm_confirmed_symbols`.

## Explicit Non-Parity Register

The initial V2 worker preserves the legacy execution shape and the core
indicator names required for downstream bootstrapping. It does **not** claim
full feature parity for every legacy feature-family branch. The following are
explicitly deferred rather than silently dropped:

- CoinAnk endpoint/family features: consumed from the V2 CoinAnk bridge in a
  downstream feature-expansion pass; CoinAnk candidates are not tradable until
  Binance USD-M confirmation exists.
- CoinAPI WSDS depth features and Binance tape features: owned by the V2 market
  ingestor / market-intelligence data plane; this worker does not read legacy
  Redis.
- Cross-timeframe context and BTC-correlation injection: deferred to dedicated
  V2 feature modules so this worker remains independently runnable and
  fail-closed.
- Additional TA-Lib families beyond RSI, MACD, ATR, SMA, and EMA are not
  silently dropped. Each family is classified in
  `LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON` and covered by
  `test_legacy_ta_surface_has_explicit_coverage_or_defer_reason`:
  AD, ADX, AROON, BOP, CCI, HT_TRENDMODE, MINUS_DI, MOM, NATR, OBV, PLUS_DI,
  STOCHRSI, TRIX, ULTOSC, WILLR, and selected candle-pattern families. All are
  deferred until parity fixtures against the preserved TA-Lib engine exist.

The implemented/deferred feature-family registry is machine-checked by
`test_legacy_feature_surface_has_explicit_coverage_or_defer_reason`, which
requires every listed legacy feature family to be either implemented in this
worker or explicitly deferred with an owner/reason.

## Closure scan

Each legacy file has `local_imports=[config]` and unknown imports
(`utils.symbol_manager`, `redis`, `talib`, `pandas`, `numpy`, `requests`,
`dateutil`, `pytz`). These are explicitly classified
`MISSING_IN_LEGACY_BASELINE_INTENTIONALLY_REPLACED` in the legacy behavior
mapping JSON with a written reason per import.

## Runnable invocation

```
python3 -m v2.backend.app.cli.v2_feature_pipeline_and_ta_worker \
    --loop --interval 10 --symbol BTCUSDT --timeframe 1m
```

Single-shot run from a snapshot file:

```
python3 -m v2.backend.app.cli.v2_feature_pipeline_and_ta_worker \
    --once --input-file v2/runtime/v2_feature_pipeline_and_ta_worker/inputs/snapshot.json
```

Baseline SHA self-check:

```
python3 -m v2.backend.app.cli.v2_feature_pipeline_and_ta_worker --verify-baseline-shas
```

## Codex review

This emit triggers
`codex_review_v2_feature_pipeline_and_ta_worker_from_legacy_baseline`.
Codex must verify:

- All five legacy baseline SHAs match `copied_baseline_manifest.json` byte-for-byte.
- The legacy_behavior_mapping.json sibling enumerates the same V2 mappings.
- The V2 worker module does not contain any legacy Redis write keys.
- TA indicator family set is preserved (RSI, MACD, ATR, SMA, EMA).
- Universe validation thresholds + retry window match the legacy defaults.
- Paralysis detector uses 1-minute bucketing and `max(1, int(window))` rule.
- Live gate remains `blocked_human_only`.
- Symbol-universe role fields are present and no current 25-symbol list is
  hardcoded as the full universe.

## Acknowledged constraints honored

- `/home/wali/Desktop/AI BOT` is **not** touched.
- No old Redis writes.
- No exchange mutation APIs.
- No leverage / margin changes.
- No live-gate unlock.
- All five baseline SHAs cited in BOTH the analysis MD and the mapping JSON
  per the LEGACY-FIRST MANDATE clause (3).

All eight required files emitted. The CLI worker is anchored to those SHAs
via `LEGACY_BASELINE_SHA256`, persists only `v2:features:*` keys, and
surfaces paralysis alerts via the public payload (not a legacy Redis
stream). Tests cover unified-features namespace, TA indicator naming,
OHLCV resampler 6-field + expiry map, universe-validation thresholds and
retry window, sustained-bucket paralysis alerts, no-legacy-redis-writes,
no-exchange-mutation, and baseline-SHA contracts. Live gate stays
`blocked_human_only`.
