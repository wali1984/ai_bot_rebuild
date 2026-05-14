# Codex V2 Market Ingestor From Legacy Baseline Review

Decision: PASS

No blocking findings found.

## Required Artifact Check

All required input/output artifacts are present:

- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_market_ingestor_from_legacy_baseline_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_market_ingestor_from_legacy_baseline_legacy_behavior_mapping.json`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_market_ingestor_from_legacy_baseline_report.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_market_ingestor_from_legacy_baseline_status.json`
- `v2/backend/app/cli/v2_market_ingestor.py`
- `v2/backend/app/services/market_ingest/service.py`
- `v2/backend/tests/integration/cli/test_v2_market_ingestor.py`
- `v2/frontend/public/operator_runtime/v2_market_ingestor/latest/v2_market_ingestor_status.json`

## Baseline SHA Audit

The five baseline source paths cited in `LEGACY_BASELINE_ANALYSIS.md` all have matching SHA256 entries in `copied_baseline_manifest.json`, and the on-disk preserved files match those same digests.

Verified paths:

- `v2/legacy_preserved/startup_baseline/ingest/live_binance.py` -> `6c1eb771a3842e2d94b797eedd55aa624075c51c6d50aec701397f81dbace798`
- `v2/legacy_preserved/startup_baseline/ingest/live_kucoin.py` -> `73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976`
- `v2/legacy_preserved/startup_baseline/ingest/live_coinapi_v1.py` -> `c8ca17d21b972510b92c4e84c477cd3440b3cfd1e2ec8e7411624a7454cee280`
- `v2/legacy_preserved/startup_baseline/ingest/live_coinapi_wsds.py` -> `a6973d887d1c52a4bb48f3b6f222b04e97d92e500ab889e94d6026cf504471b6`
- `v2/legacy_preserved/startup_baseline/ingest/realtime_price_provider.py` -> `dfdc2568368c134b9afcc4fa0faff312cc93a6ecc501ecaac747e7c20d7344ba`

Command evidence:

- `.venv/bin/python -m v2.backend.app.cli.v2_market_ingestor --verify-baseline-shas`
- Result: `ok: true`, `mismatches: []`

## V2 Data Plane Namespace

PASS. The worker writes data-plane entries through `V2_KEY_PREFIX = "v2:market"` in `v2/backend/app/services/market_ingest/service.py`.

Observed data-plane write keys are V2 namespaced only:

- `v2:market:{symbol}:ohlcv:{timeframe}`
- `v2:market:{symbol}:price`
- `v2:market:{symbol}:bbo`
- `v2:market:{symbol}:mark`
- `v2:market:{symbol}:funding`
- `v2:market:{symbol}:open_interest`
- `v2:market:{symbol}:depth`
- `v2:market:source_health`

Searches over `v2/backend/app/cli/v2_market_ingestor.py` and `v2/backend/app/services/market_ingest/service.py` found no executable old Redis writes, Redis client construction, Redis imports, or legacy write key usage. Legacy key strings appear only in docs/tests where they define forbidden patterns.

## Exchange Mutation Reachability

PASS. The market ingestor worker and service use public HTTP GET only.

Allowed read-only endpoints found:

- CoinAPI public OHLCV REST
- Binance USD-M public `klines`
- Binance public `ticker/bookTicker`
- Binance public `premiumIndex`
- Binance public `openInterest`
- Binance public `depth`
- KuCoin public orderbook level1

No API-key env reads, signed requests, POST/PUT/DELETE requests, order placement, cancel, leverage, margin, margin-mode, account, or position mutation paths were found in the worker/service code.

The broader V2 API live surface remains default-denied: `/api/v1/live/**` is intercepted by `LiveBlockGuardMiddleware` and returns 403. The `/live` router is scaffold metadata only.

## Data Source Priority

PASS. The V2 table matches the legacy startup script table in `v2/legacy_preserved/startup_baseline/scripts/start_all_services_production.sh` lines 462-470.

Matched routing:

- OHLCV: CoinAPI V1 primary, Binance REST fallback
- Quote/BBO: CoinAPI DS primary, Binance bookTicker fallback
- Microstructure: CoinAPI DS primary, no fallback
- Funding rate: Binance WS primary, no fallback
- Mark price: Binance WS primary, no fallback
- Premium index: Binance REST primary, no fallback
- Open interest: Binance REST primary, CoinAnk fallback
- Liquidations: Binance WS primary, no fallback
- Orderbook depth: Binance REST+WS primary, no fallback

The service exposes this as `DATA_SOURCE_PRIORITY`, and integration tests assert full table equality.

## Live Gate

PASS. The worker constant and emitted payloads are blocked:

- `LIVE_GATE_STATUS = "blocked_human_only"`
- public status `live_gate = "blocked_human_only"`
- public status `current_gate_state = "blocked_human_only"`
- worker status `live_gate = "blocked_human_only"`
- worker status `current_gate_state = "blocked_human_only"`

No codepath was found that can unlock or mutate this gate.

## Test Coverage

PASS. Required tests are present and passing.

Relevant coverage in `v2/backend/tests/integration/cli/test_v2_market_ingestor.py` includes:

- V2 namespaced persistence and public status shape
- CoinAPI V1 primary before Binance REST OHLCV fallback
- KuCoin optional path recognition
- realtime price provider priority preservation
- startup script data-source table equality
- legacy WS reconnect schedule delegated contract
- CoinAPI stale threshold
- legacy-equivalent `-1003` rate-limit ban backoff
- fail-closed 5xx backoff
- no old Redis write contract
- no exchange mutation method contract
- baseline SHA manifest contract

Command evidence:

- `.venv/bin/pytest -q v2/backend/tests/integration/cli/test_v2_market_ingestor.py`
- Result: `14 passed in 0.07s`

## Final Assessment

The baseline port satisfies the requested Codex audit gates:

- required artifacts present
- baseline paths and SHA256s match the copied baseline manifest
- V2 data plane is `v2:*` namespaced
- no old Redis writes found
- no exchange mutating endpoint or leverage/margin control is reachable from this worker
- data-source priority matches the startup script table
- live gate remains `blocked_human_only`
- required rate-limit and reconnect behavior tests are present and passing
