# Parallel Codex Change Notice — CoinGlass, Liquidation, Echo

Date: 2026-07-19

This notice is for the concurrent Codex agent working on trainer blockers and
gates. A separate user-directed task is making narrowly scoped correctness
changes outside the files already dirty in that agent's worktree.

## Intended owned files

- `v2/backend/app/services/coinglass_provider/normalizer.py`
- `v2/backend/app/services/coinglass_provider/endpoint_registry.py`
- `v2/backend/app/services/coinglass_provider/publisher.py`
- dedicated CoinGlass tests
- `v2/backend/app/cli/v2_liquidation_levels_engine.py`
- `v2/backend/app/cli/v2_liquidation_wss_loop.py` only if required
- `v2/backend/app/services/native_ingestors/liquidations_wss.py`
- `v2/backend/app/services/microstructure_trust/cascade_context.py`
- dedicated liquidation/cascade tests
- `v2/backend/app/services/echo_forecast/analog_forecaster.py`
- `v2/backend/app/services/echo_forecast/__init__.py`
- dedicated Echo tests

## Explicit non-overlap

This task will not edit the currently dirty trainer, provider bridge, paper
entry gate, risk, confluence, strategy, or execution files. It will not restart
live services or change order submission/cancellation/modification paths.

## Validation requested from the concurrent agent

After these changes land, please re-run the trainer/gate tests that exercise
provider features, liquidation cascade context, temporal lineage, and dirty
sample exclusion. Inspect the final diff before incorporating or rebasing any
of these paths. A final section will be appended to this notice with the exact
changed files and test commands/results.

## Urgent downstream contract changes discovered during live validation

- The CoinGlass Standard account only admits `1h` history for long/short,
  aggregated liquidations, taker flow, and orderbook history. The corrected
  producer now emits truthful `coinglass_liquidation_{buy,sell,total}_usd_1h`
  names. Please migrate the currently old `_1m` mappings/selectors in
  `provider_features/contracts.py` and the dirty provider/trainer path, and
  deduplicate historical provider observations by `feature_cutoff`.
- The local liquidation engine measures **retrospective observed Binance forced
  liquidation clusters**. It cannot calculate exact future position liquidation
  thresholds because the public stream contains no entry price, leverage,
  margin mode, maintenance tier, or position size. Numeric values are therefore
  being removed from the legacy future-looking `liquidation_*_level`,
  `nearest_liquidation_level_*`, and `sweep_target_*` aliases. Explicit
  `observed_liquidation_cluster_*` fields remain. Please revalidate trainer,
  strategy, risk, tensor, and gate consumers so missing legacy aliases fail
  closed and only opt into observed-cluster semantics deliberately.
- WSS rolling activity now publishes truthful, lossy-window data under
  `v2:market:liquidations:observed_aggregate:{symbol}` with explicit coverage
  masks. It no longer refreshes the old key that falsely claimed complete
  1h/24h totals. No current trainer consumer reads the new observed key yet;
  wire it only with coverage-aware semantics and do not alias it back to a
  complete 24h aggregate.
- **Restart blocker in trainer-owned feature pipeline:** once the false legacy
  aggregate expires, `_read_liq_notional_24h` in
  `v2/backend/app/cli/v2_feature_pipeline_native_loop.py` falls back to
  `XRANGE min=- max=+`, sums the entire retained stream as "24h", and repeats
  that full scan per symbol. Before restarting WSS, replace this with a
  time-bounded, coverage-aware read of the new observed aggregate (or a single
  bounded stream scan shared across symbols). Missing/incomplete coverage must
  be masked, not converted to a real zero or claimed 24h total.
- **Cascade publisher restart blocker:** the hardened cascade module requires
  explicit event/cutoff/ingest/availability clocks, while the unchanged raw
  `_source_payloads` in `v2_cascade_context_publisher.py` do not provide all of
  them for OI, funding, orderbook, or tape. A live-shape replay currently masks
  those sources with `missing_feature_cutoff`. Add source-specific, truthful
  lineage normalization and runtime-shape tests before restarting this
  publisher; never synthesize cutoff or availability as `now`.
- The active enhanced-liquidation publisher was also found fabricating +/-5%
  "predicted" zones and marking them training eligible without PIT clocks. It
  is being changed to status/shadow fail-closed until truthful future-threshold
  inputs exist.
- Generic lineage clocks are no longer written into the shared unified-feature
  hash by the liquidation engine; only `liquidation_*`-namespaced clocks are
  written there. This prevents the engine heartbeat from overwriting another
  producer's `event_time`, `available_at`, or `feature_cutoff`.

## Final changed files

CoinGlass:

- `v2/backend/app/cli/v2_coinglass_provider_loop.py`
- `v2/backend/app/services/coinglass_provider/endpoint_registry.py`
- `v2/backend/app/services/coinglass_provider/normalizer.py`
- `v2/backend/app/services/coinglass_provider/publisher.py`
- `v2/backend/tests/unit/cli/test_v2_provider_scheduler_status.py`
- `v2/backend/tests/unit/services/coinglass_provider/test_publisher_and_registry.py`
- `v2/backend/tests/unit/services/coinglass_provider/test_normalizer_contract.py` (new)

Liquidation:

- `v2/backend/app/cli/v2_liquidation_enhanced.py`
- `v2/backend/app/cli/v2_liquidation_levels_engine.py`
- `v2/backend/app/cli/v2_liquidation_wss_loop.py`
- `v2/backend/app/services/microstructure_trust/cascade_context.py`
- `v2/backend/app/services/native_ingestors/liquidations_wss.py`
- `v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py`
- `v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py`
- `v2/backend/tests/unit/cli/test_v2_liquidation_levels_engine.py` (new)
- `v2/backend/tests/unit/cli/test_v2_liquidation_enhanced_fail_closed.py` (new)

Echo:

- `v2/backend/app/services/echo_forecast/__init__.py`
- `v2/backend/app/services/echo_forecast/analog_forecaster.py`
- `v2/backend/tests/unit/services/echo_forecast/test_analog_forecaster.py`

Coordination:

- `claude_worklog/codex/CODEX_PARALLEL_CHANGE_NOTICE_2026_07_19_COINGLASS_LIQUIDATION_ECHO.md` (new)

No files were deleted. No trainer, provider-bridge, confluence, risk, paper-entry,
strategy, or order-execution file was edited by this task.

## Final verification

The root combined regression command was:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/services/coinglass_provider/test_normalizer_contract.py v2/backend/tests/unit/services/coinglass_provider/test_publisher_and_registry.py v2/backend/tests/unit/cli/test_v2_provider_scheduler_status.py v2/backend/tests/unit/services/echo_forecast/test_analog_forecaster.py v2/backend/tests/unit/cli/test_v2_liquidation_levels_engine.py v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py v2/backend/tests/unit/cli/test_v2_liquidation_enhanced_fail_closed.py v2/backend/tests/unit/cli/test_phase_c_ingestors_fail_closed.py v2/backend/tests/unit/cli/test_v2_cascade_context_publisher.py v2/backend/tests/unit/scripts/test_claude_cascade_context_supply_monitor.py v2/backend/tests/unit/cli/test_v2_copied_liquidation_runtime_wrappers.py v2/backend/tests/integration/cli/test_v2_liquidation_ingestor_loop.py v2/backend/tests/integration/cli/test_v2_liquidation_observation_aggregator.py v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py
```

Result: **241 passed in 0.81s**. The only warning was the repository's existing
pytest-asyncio unset-default-loop-scope deprecation warning.

Final static checks:

```bash
.venv/bin/ruff check v2/backend/app/services/coinglass_provider/endpoint_registry.py v2/backend/app/services/coinglass_provider/normalizer.py v2/backend/app/services/coinglass_provider/publisher.py v2/backend/app/cli/v2_coinglass_provider_loop.py v2/backend/tests/unit/services/coinglass_provider/test_normalizer_contract.py v2/backend/tests/unit/services/coinglass_provider/test_publisher_and_registry.py v2/backend/tests/unit/cli/test_v2_provider_scheduler_status.py v2/backend/app/services/echo_forecast/analog_forecaster.py v2/backend/app/services/echo_forecast/__init__.py v2/backend/tests/unit/services/echo_forecast/test_analog_forecaster.py
```

```bash
.venv/bin/ruff check --select F v2/backend/app/cli/v2_liquidation_levels_engine.py v2/backend/app/cli/v2_liquidation_enhanced.py v2/backend/app/cli/v2_liquidation_wss_loop.py v2/backend/app/services/native_ingestors/liquidations_wss.py v2/backend/app/services/microstructure_trust/cascade_context.py v2/backend/tests/unit/cli/test_v2_liquidation_levels_engine.py v2/backend/tests/unit/cli/test_v2_liquidation_enhanced_fail_closed.py v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py
```

```bash
MYPYPATH=v2/backend .venv/bin/mypy --cache-dir=/dev/null --follow-imports=skip --ignore-missing-imports v2/backend/app/services/coinglass_provider/endpoint_registry.py v2/backend/app/services/coinglass_provider/normalizer.py v2/backend/app/services/coinglass_provider/publisher.py v2/backend/app/cli/v2_coinglass_provider_loop.py v2/backend/app/services/echo_forecast/analog_forecaster.py v2/backend/app/services/echo_forecast/__init__.py
```

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m py_compile v2/backend/app/cli/v2_liquidation_levels_engine.py v2/backend/app/services/native_ingestors/liquidations_wss.py v2/backend/app/cli/v2_liquidation_wss_loop.py v2/backend/app/services/microstructure_trust/cascade_context.py v2/backend/app/cli/v2_liquidation_enhanced.py
```

All passed, as did `git diff --check` over every file listed above. An
independent Redis DB15 probe also proved WSS Lua idempotency (`written`, then
`duplicate`, one stream row) and removed its test data afterward.

Read-only audit commands used `rg`/`sed`/`git diff`/`git status`, `ps`,
`systemctl --user list-unit-files`/`list-units`, and `redis-cli` (`SCAN`, `GET`,
`TYPE`, `STRLEN`, `XLEN`, `XINFO STREAM`, `XRANGE`, and `XREVRANGE`). Sanitized
one-shot Python probes made no exchange writes: CoinGlass Standard was queried
for BTCUSDT history at 1m/5m/15m/1h, funding/market response scope, and market
instrument identity; Redis DB0 was read to compare WSS stream coverage,
duplicate IDs, latency, service payloads, and process state. API keys and raw
secrets were never printed.

Downstream checks run without edits:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/services/provider_features/test_provider_feature_bridge.py v2/backend/tests/unit/services/feature_pipeline/test_provider_unified_feature_bridge.py
```

Result: **22 passed**.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/services/altdata/test_altdata_confluence_engine.py
```

Result: **8 passed, 1 failed** in the already-dirty trainer/confluence lane:
`test_feature_cutoff_is_conservative_minimum`. It still constructs the removed
synthetic `coinglass_funding_rate_zscore` and the dirty confluence path selects
the later cutoff. This task deliberately did not edit that file.

## Echo measured performance and integration decision

A purged, gap-aware walk-forward evaluation used 14,595 forecasts from finalized
local candles across 11 symbols, five timeframes, and 1/3/6-bar horizons:

- direction accuracy: 50.26% (mean-reversion baseline: 51.49%);
- prediction/realized correlation: 0.0233 (historical-mean baseline: 0.0565);
- MAE: 52.44 bps (zero-return baseline: 50.11 bps, Echo 4.66% worse);
- zero-baseline MAE lost in all 15 timeframe/horizon buckets and all 11 symbols;
- heuristic-quality/correctness correlation: -0.0026.

The numerical/PIT implementation is now hardened and fully tested, but the
model is intentionally **not wired into trainer or decisions** because this
out-of-sample evidence does not establish useful predictive accuracy.

## Runtime rollout state

No service was restarted. The current CoinGlass, WSS, levels, enhanced, and
cascade processes still have their pre-patch modules loaded. This is deliberate:
restarting them before the concurrent trainer/gate agent resolves the `_1h`
mapping, observed-aggregate fallback, observed-cluster consumers, and cascade
source-lineage normalization would either reintroduce false semantics or make
currently assumed features disappear mid-validation. After those fixes are
validated, restart enhanced first and allow 300 seconds for its old unsafe
actual keys to expire; then perform the coordinated provider/WSS/levels/cascade
restart and verify the new status/coverage masks before admitting samples.

## Follow-up downstream integration repair (2026-07-20)

A separate, clean-file follow-up resolved the restart blockers that did not
overlap the trainer/gate agent's dirty provider bridge:

- `provider_features/contracts.py` now maps Standard-plan CoinGlass liquidation
  history only to truthful `liquidation_{buy,sell,total}_usd_1h` canonical
  names. The misleading `_1m` aliases were removed.
- `_read_liq_notional_24h` in `v2_feature_pipeline_native_loop.py` now reads
  only `v2:market:liquidations:observed_aggregate:{symbol}` and admits a numeric
  24h value only when the semantic kind, exact 24h window, local retention,
  source capture, no-truncation, and PIT clocks all prove a complete aggregate.
  The per-symbol unbounded `XRANGE - +` fallback and legacy aggregate read were
  removed. The current lossy Binance stream therefore remains `None` for the
  claimed complete-24h trainer feature; it is never converted to zero.
- `v2_cascade_context_publisher.py` now normalizes OI, funding, long/short,
  orderbook/spread, mark/index, and cross-asset lineage only from literal source
  clocks. Cross-asset changes use finalized 5m candles and their dependency
  clock envelope; unfinished candles are excluded. It never stamps source
  cutoff or availability with publisher `now`.
- The cascade source resolver prefers the explicit observed-liquidation key and
  ignores the legacy complete-aggregate key. A fully retained one-hour local
  window can contribute explicitly labelled observed lower-bound cascade
  evidence, but is never aliased to a complete exchange 1h/24h total. The
  context publishes the capture/retention semantics alongside the result.
- A live-shape probe showed the existing agg-trade producer's `generated_utc`
  precedes WebSocket collection, so it is correctly *not* promoted to tape
  availability. Tape stays masked as `missing_ingested_at` until its producer
  supplies literal receive/availability clocks. The pre-restart liquidation
  and levels payloads likewise stay masked until the coordinated rollout loads
  their already-patched full lineage.

### Follow-up file ownership

Modified:

- `v2/backend/app/services/provider_features/contracts.py`
- `v2/backend/app/cli/v2_feature_pipeline_native_loop.py`
- `v2/backend/app/cli/v2_cascade_context_publisher.py`
- `v2/backend/tests/unit/cli/test_v2_cascade_context_publisher.py`
- `v2/backend/tests/unit/cli/test_v2_long_short_ratio_feature_pipeline.py`

Created:

- `v2/backend/tests/unit/cli/test_v2_liquidation_observed_feature_contract.py`
- `v2/backend/tests/unit/services/provider_features/test_coinglass_contract_semantics.py`

Conflict intentionally left untouched:

- `v2/backend/app/services/provider_features/provider_feature_bridge.py`
- `v2/backend/tests/unit/services/provider_features/test_provider_feature_bridge.py`
- `v2/backend/tests/unit/services/feature_pipeline/test_provider_unified_feature_bridge.py`

Those three files were already dirty with the concurrent trainer/PIT repair.
The owning agent must change `_payloads_for_tensor` from the obsolete
`liquidation_*_1m` selectors to deliberate `liquidation_*_1h` semantics and
revalidate its ABI/collision policy. This follow-up did not overwrite or merge
that work.

### Follow-up validation

Focused contract suite:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/cli/test_v2_liquidation_observed_feature_contract.py v2/backend/tests/unit/cli/test_v2_cascade_context_publisher.py v2/backend/tests/unit/services/provider_features/test_coinglass_contract_semantics.py v2/backend/tests/unit/cli/test_v2_long_short_ratio_feature_pipeline.py
```

Result: **19 passed**.

Broader cascade/feature/provider regression suite:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/cli/test_v2_cascade_context_publisher.py v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py v2/backend/tests/unit/scripts/test_claude_cascade_context_supply_monitor.py v2/backend/tests/unit/cli/test_v2_liquidation_observed_feature_contract.py v2/backend/tests/unit/cli/test_v2_feature_pipeline_native_loop.py v2/backend/tests/unit/cli/test_v2_long_short_ratio_feature_pipeline.py v2/backend/tests/unit/services/provider_features/test_coinglass_contract_semantics.py v2/backend/tests/unit/services/provider_features/test_provider_feature_bridge.py v2/backend/tests/unit/services/feature_pipeline/test_provider_unified_feature_bridge.py
```

Result: **157 passed**. Both commands emitted only the repository's existing
pytest-asyncio loop-scope deprecation warning.

`py_compile`, Ruff fatal/error checks (`--select F,E9`), and `git diff --check`
also passed for the follow-up implementation and tests. No service was
restarted and no live order, strategy, PPO/MASA, risk, or execution path was
changed.

## 2026-07-20 follow-up repair scope

The operator requested implementation of the remaining blockers plus narrow
CoinAnk, KuCoin, and adaptive-symbol-selection audits. This follow-up continues
to treat the concurrently dirty trainer/gate lane as a hard boundary.

Planned clean-file work is limited to:

- `v2/backend/app/services/provider_features/contracts.py` (truthful CoinGlass
  hourly names only; the dirty provider bridge is not being edited);
- `v2/backend/app/cli/v2_feature_pipeline_native_loop.py` (bounded,
  coverage-aware observed-liquidation reads, subject to a final clean-file
  check immediately before editing);
- `v2/backend/app/cli/v2_cascade_context_publisher.py` (source-specific factual
  lineage normalization, subject to the same clean-file check);
- CoinAnk/KuCoin ingestor-specific clean files and focused tests;
- symbol-universe publisher/service clean files and focused tests, without
  changing strategy, risk, position sizing, or order execution.

`v2/backend/app/services/provider_features/provider_feature_bridge.py`, its
currently dirty tests, trainer files, gate files, and paper/risk/execution paths
will not be edited. If any clean target becomes dirty during this work, that
edit will stop and be reported rather than merged over concurrent changes.
No service restart is authorized as part of this follow-up.

## Immediate concurrent-agent handoff: CoinAnk/KuCoin/adaptive repairs (2026-07-20)

This section is an active coordination notice for the separate Codex agent that
owns trainer, sample-admission, gate, and provider-tensor work.  The follow-up
has modified ingestion- and symbol-universe-owned files.  Do not assume the
old provider contracts are unchanged when validating that lane.

Hard conflict boundaries that require that agent's validation:

- `v2/legacy_owned_runtime/rl/hybrid_trainer.py::_load_global_features` reads
  all eleven `features:global_coinank:*:latest` objects and appends `value`
  without checking `supported`, `aggregate_valid`, coverage, freshness, or
  nullability.  The repaired CoinAnk aggregate truthfully represents
  unsupported metrics with `value: null` and represents partial coverage
  explicitly.  **Do not restart the CoinAnk global aggregator** until the
  trainer-owned consumer rejects/masks invalid or incomplete members and its
  fixed-width tensor contract is revalidated.  This follow-up will not edit
  that trainer file over concurrent work.
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/data_loader.py`
  and `tensor_builder.py` still map CoinAnk features from collided
  generic `latest:coinank:{family}:...` keys.  Live inspection proved those
  keys can contain a sibling endpoint (for example funding indicator instead
  of funding kline, an untyped long/short variant, or an OI chart variant).
  The repaired V2 CoinAnk bridge is deliberately `trainer_consumable: false`.
  The trainer-owned lane must either bind an endpoint-identity-, finality-,
  freshness-, and receipt-validated contract or fail closed; restarting the
  legacy producer must not be treated as resolving this consumer collision.
- Historical contamination is already observable in the active aggregator
  log.  On 2026-07-20 local EDT, `market_sentiment` exceeded its [-1, 1]
  contract from 00:25:55 through 01:40:55 (UTC 04:25:55 through 05:40:55),
  and `total_volume` was negative from 00:30:55 through 01:30:55 (UTC
  04:30:55 through 05:30:55).  Values reached roughly 5.5e16.  Producer repair
  does not clean replay, samples, or checkpoints already built from these
  rows.  The trainer/gate owner must quarantine evidence whose lineage
  intersects at least that window (and broaden the quarantine to the full
  pre-contract CoinAnk period when lineage cannot prove exclusion), including
  rows made from zero-count proxies.  This follow-up will not delete or rewrite
  trainer artifacts across the ownership boundary.
- The active unit
  `ai-bot-v2-coinank-global-aggregator-direct.service` explicitly sets
  `COINANK_GLOBAL_AGG_TF=15m`.  A read-only simulation of the repaired strict
  contract at that timeframe produced zero valid supported global metrics;
  the exact 1h endpoint lane had near/full coverage for funding, order flow,
  liquidations, and the explicit global-account long/short source.  Coordinate
  a service-timeframe change only after the trainer validity/masking contract
  is repaired and retested.  Restarting the current 15m unit would publish
  null/partial truth into a consumer that currently appends it unchecked.
- The concurrently dirty
  `v2/backend/app/services/provider_features/provider_feature_bridge.py` still
  selects obsolete CoinGlass `liquidation_*_1m` names.  Standard-plan history
  is now truthfully published only as `liquidation_*_1h`; the owning agent must
  repair and retest the tensor selector before the coordinated CoinGlass /
  liquidation restart.
- Adaptive symbol selection is default-off and shadow-only.  It must not become
  authoritative until scope-aware trainer, paper-entry, open-position data,
  risk, and execution consumers are explicitly bound and validated.  BTC,
  ETH, and SOL receive ordering preference only after the same data-health and
  validated-edge gates as every other symbol.
- The native trainer data loader currently requests a consolidated
  `v2:market:kucoin:{symbol}` object that this worker does not publish.  KuCoin
  now publishes PIT-labelled component keys and a deliberately held
  `v2:features:kucoin:{symbol}:latest` cross-venue snapshot with
  `trainer_consumable: false`.  The trainer owner must define and validate a
  canonical component contract (final candles, explicit clocks, homogeneous
  product identity, funding interval/units, and a publication receipt) rather
  than enabling the mixed snapshot or silently treating the lane as present.

Current follow-up ownership (final list and validations will be appended after
the independent reviews finish):

- CoinAnk: `v2/backend/app/cli/v2_coinank_intel_bridge.py`,
  `v2/backend/app/services/altdata/provider_feature_bridge.py`, focused tests,
  and the locally active ignored legacy source files
  `v2/legacy_owned_runtime/ingest/live_coinank.py` and
  `v2/legacy_owned_runtime/ingest/live_coinank_global_aggregator.py`.
- CoinAnk operator truth: the previously clean
  `v2/backend/app/services/operator_truth/trade_derivatives_runtime.py` and its
  focused payload test now require valid/fresh/temporally valid bridge
  contracts before display.  Provider-unit-unknown OI is no longer relabelled
  as USD; the compatibility `coinank_open_interest_usd` field is explicitly
  null and the actual observation carries its unknown-unit label.
- KuCoin: `v2/backend/app/cli/v2_kucoin_ingestor_worker.py`,
  `v2/backend/app/services/native_ingestors/kucoin.py`, and focused tests.
- Adaptive symbol selection: `v2/backend/app/cli/symbol_universe_public_payload.py`,
  `v2/backend/app/services/v2_symbol_runtime_universe.py`, new
  `adaptive_symbol_selection*.py` services, and focused tests.

No strategy, PPO/MASA, risk, position-sizing, order-submission, cancellation,
or exchange-account path is being changed by this follow-up.

## Frozen follow-up result and mandatory trainer/gate revalidation (2026-07-20)

The ingestion and symbol-universe patches are now frozen.  Two independent
reviews found no remaining code-correctness blocker in the CoinAnk or KuCoin
lanes.  This is **code/regression approval, not rollout approval**: no service
was restarted, the active CoinAnk processes still contain the July 17 modules,
and the trainer-owned consumer conflicts listed above remain observable in the
current worktree.

### CoinAnk result

- Current-window requests no longer use the old one-hour offset.  Canonical
  mirrors are exact-endpoint and exact-variant mirrors, so a sibling funding,
  long/short, OI-chart, or generic endpoint cannot overwrite the selected
  feature family.  Canonical symbol normalization also prevents `USDTUSDT`
  duplication.
- A persisted, stable major-first scheduler keeps BTC, ETH, and SOL at the
  front without starving the rest of the universe.  Critical endpoints run in
  a due-priority queue before the 54-endpoint generic loop.
- Scheduler capacity is based on measured start-to-start revisit time, actual
  attempts, call duration, adaptive endpoint minimum intervals, and 429
  cooldowns.  Cold start cannot claim complete coverage until a second visit
  establishes cadence.  An expanded universe or insufficient RPM fails
  closed.
- All five canonical critical responses pass endpoint-specific semantic
  validation before `persist()` or scheduler-ledger advancement.  HTTP 200 is
  insufficient by itself: success envelopes, a finalized/recent cutoff,
  explicit receipt time, numeric values, and endpoint domains are required.
  Invalid/stale/empty responses preserve the last-known-good mirror.
- Global aggregation groups only an exact cutoff bucket and publishes a value
  only with explicit supported semantics, sufficient coverage, truthful
  units, and temporal lineage.  Cross-contract funding is null/unsupported
  because CoinAnk does not establish a common funding interval; no unknown
  interval is silently normalized.

CoinAnk files modified:

- `v2/backend/app/cli/v2_coinank_intel_bridge.py`
- `v2/backend/app/services/altdata/provider_feature_bridge.py`
- `v2/backend/tests/integration/cli/test_v2_coinank_intel_bridge_consumption.py`
- `v2/legacy_owned_runtime/ingest/live_coinank.py` (ignored operational source)
- `v2/legacy_owned_runtime/ingest/live_coinank_global_aggregator.py` (ignored
  operational source)

CoinAnk files created:

- `v2/backend/app/services/altdata/coinank_scheduler.py`
- `v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py`

The two `legacy_owned_runtime` files are excluded by `.gitignore` and must be
included deliberately in deployment packaging.  Current read-only evidence:
PIDs 4619, 8011, and 8947 started July 17; Redis
`EXISTS coinank:scheduler:latest_status` is `0`.  Therefore the repaired
scheduler has not loaded and must not be described as live-validated.

### KuCoin result

- Futures authority now requires the exact active USDT-settled, non-inverse
  product and its authoritative multiplier; spot fallback is homogeneous and
  explicit.  Final candles carry literal event/ingest/availability/cutoff
  clocks and an unfinished current candle cannot become a feature.
- Futures kline granularity uses the provider's minute-valued API contract.
  Funding observations preserve the authoritative 1h/4h/8h interval in
  milliseconds and expose per-hour normalization separately.
- REST calls have budgets/deadlines, major-first fair rotation, a persisted
  successor cursor, and component receipts.  TTL safety uses a rolling
  12-observation recent-revisit window so one historical slow sample remains
  visible as lifetime telemetry but does not make recovery impossible.
- The dormant native WebSocket topics were corrected to the provider's
  futures ticker-v2, level2, and instrument topic contracts.  This path remains
  dormant and was not restarted.

KuCoin files modified:

- `v2/backend/app/cli/v2_kucoin_ingestor_worker.py`
- `v2/backend/app/services/native_ingestors/kucoin.py`
- `v2/backend/tests/unit/cli/test_v2_kucoin_ingestor_worker.py`
- `v2/backend/tests/integration/cli/test_v2_kucoin_ingestor_worker.py`

The currently published 2026-07-20T06:54:41Z public status is truthful and
partial: 151 authorized symbols, 162 requests within a 240-request budget, 79
successful rotated rows, 79 tickers, 48 finalized-kline rows, 79 order books,
77 funding rows, and 77 contract rows.  It remains `trainer_consumable: false`
where sparse/expired component coverage is not proven.  It performs public
market-data reads only and does not place orders.

### Adaptive symbol-selection result

- Training and trading scopes are now separate.  Every candidate requires
  finite, finalized, sufficiently fresh, explicitly clocked market evidence;
  execution candidates additionally require spread/depth feasibility.
- Trading selection requires at least 30 explicitly leakage-free,
  out-of-sample, after-cost validation samples with positive expectancy and a
  positive lower confidence bound.  Trading is a subset of training.  Missing
  evidence fails closed rather than treating prediction confidence or an
  unvalidated alt-data score as proven benefit.
- The ranking combines data health, liquidity/executability, realized move
  opportunity, and validated after-cost predictability.  It includes bounded
  capacity, hysteresis, and per-cycle turnover limits.  It is an opportunity
  ranking, not a claim that a move will occur.
- BTCUSDT, ETHUSDT, and SOLUSDT are preferred and ordered first, but the
  preference never bypasses health, PIT, feasibility, or validated-edge gates.
  Legacy authoritative scopes receive the same major-first ordering without
  changing membership.
- Adaptive authority is default-off and needs both
  `V2_ADAPTIVE_SYMBOL_SCOPES_ACTIVE` and
  `V2_ADAPTIVE_SYMBOL_SCOPE_CONSUMERS_BOUND`.  Open positions, risk, and order
  consumers must be explicitly bound before activation.  No execution or
  position-management behavior changed.
- The selector explicitly publishes `guaranteed_return_claim: false` and
  `guaranteed_1000x_claim: false`; no defensible implementation can guarantee
  a 1000x result.

Adaptive files modified:

- `v2/backend/app/cli/symbol_universe_public_payload.py`
- `v2/backend/app/services/v2_symbol_runtime_universe.py`
- `v2/backend/app/services/operator_truth/trade_derivatives_runtime.py`
- `v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py`
- `v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py`
- `v2/backend/tests/unit/services/test_trade_derivatives_runtime_payloads.py`

Adaptive files created:

- `v2/backend/app/services/adaptive_symbol_selection.py`
- `v2/backend/app/services/adaptive_symbol_selection_runtime.py`
- `v2/backend/tests/unit/services/test_adaptive_symbol_selection.py`
- `v2/backend/tests/unit/services/test_adaptive_symbol_selection_runtime.py`

The public payload at 2026-07-20T06:57:37Z evaluated 108 unique valid symbol
rows, with zero duplicate/invalid rows.  It correctly selected zero adaptive
training/trading symbols because the trainer-consumption readiness and
validated OOS evidence are absent.  Adaptive authority is inactive.  Safe
legacy fallback remains loaded with 155 training, 99 paper, and 108 collection
symbols; each begins BTCUSDT, ETHUSDT, SOLUSDT.

### Final regression and static evidence

The final frozen suites were rerun from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/services/coinglass_provider/test_normalizer_contract.py v2/backend/tests/unit/services/coinglass_provider/test_publisher_and_registry.py v2/backend/tests/unit/cli/test_v2_provider_scheduler_status.py v2/backend/tests/unit/services/echo_forecast/test_analog_forecaster.py v2/backend/tests/unit/cli/test_v2_liquidation_levels_engine.py v2/backend/tests/integration/cli/test_v2_liquidation_wss_loop.py v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py v2/backend/tests/unit/cli/test_v2_liquidation_enhanced_fail_closed.py v2/backend/tests/unit/cli/test_phase_c_ingestors_fail_closed.py v2/backend/tests/unit/cli/test_v2_cascade_context_publisher.py v2/backend/tests/unit/scripts/test_claude_cascade_context_supply_monitor.py v2/backend/tests/unit/cli/test_v2_copied_liquidation_runtime_wrappers.py v2/backend/tests/integration/cli/test_v2_liquidation_ingestor_loop.py v2/backend/tests/integration/cli/test_v2_liquidation_observation_aggregator.py v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py
```

Result: **246 passed**.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/cli/test_v2_cascade_context_publisher.py v2/backend/tests/unit/services/microstructure_trust/test_cascade_context.py v2/backend/tests/unit/scripts/test_claude_cascade_context_supply_monitor.py v2/backend/tests/unit/cli/test_v2_liquidation_observed_feature_contract.py v2/backend/tests/unit/cli/test_v2_feature_pipeline_native_loop.py v2/backend/tests/unit/cli/test_v2_long_short_ratio_feature_pipeline.py v2/backend/tests/unit/services/provider_features/test_coinglass_contract_semantics.py v2/backend/tests/unit/services/provider_features/test_provider_feature_bridge.py v2/backend/tests/unit/services/feature_pipeline/test_provider_unified_feature_bridge.py
```

Result: **157 passed**.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=v2/backend .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/cli/test_symbol_universe_public_payload.py v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py v2/backend/tests/unit/services/test_adaptive_symbol_selection.py v2/backend/tests/unit/services/test_adaptive_symbol_selection_runtime.py v2/backend/tests/unit/services/test_trade_derivatives_runtime_payloads.py
```

Result: **45 passed**.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=v2/backend .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py v2/backend/tests/integration/cli/test_v2_coinank_intel_bridge_consumption.py v2/backend/tests/unit/services/feature_pipeline/test_provider_unified_feature_bridge.py v2/backend/tests/unit/services/provider_features/test_provider_feature_bridge.py v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py v2/backend/tests/integration/cli/test_v2_alternative_data_status.py v2/backend/tests/unit/cli/test_v2_altdata_confluence_loop.py v2/backend/tests/unit/services/test_coinank_native_trainer_feature_fallbacks.py
```

Result: **82 passed**.

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=v2/backend .venv/bin/python -m pytest -q -p no:cacheprovider v2/backend/tests/unit/cli/test_v2_kucoin_ingestor_worker.py v2/backend/tests/integration/cli/test_v2_kucoin_ingestor_worker.py
```

Result: **42 passed**.  One preceding command included the nonexistent path
`v2/backend/tests/unit/services/native_ingestors/test_kucoin.py`; pytest exited
4 without running tests.  The corrected exact two-file suite above then
passed.

Independent review additionally reran CoinAnk (82), CoinAnk scheduler/bridge /
operator (40), and KuCoin (42) suites.  `py_compile` passed over all owned
Python and test files plus both ignored CoinAnk operational sources.  Ruff
fatal/error checks passed; the intentionally narrow legacy-producer check used
`--select E9,F821,F822,F823` because that old file has 13 unrelated existing
style/unused-import findings.  `git diff --check` passed over every owned
tracked file.  The only pytest output was the repository's existing
pytest-asyncio default-loop-scope deprecation warning.

Read-only closing commands used `rg`, `sed`, `tail`, `head`, `find`, `ls`,
`stat`, `git status --short --untracked-files=all`, `git diff --stat`,
`git diff --check`, `ps -eo`, `jq`, and `redis-cli EXISTS/GET/SCAN` to inspect
source ownership, process age, Redis contracts, and public statuses.  No live
exchange write, Redis deletion, service restart, order action, or data rewrite
was performed.

### Required action by the concurrent trainer/gate owner

Before any coordinated restart or adaptive activation, revalidate and repair:

1. `provider_feature_bridge.py` lines 483-484 still select obsolete CoinGlass
   `liquidation_*_1m` fields instead of the truthful Standard-plan `_1h`
   contract.
2. The native trainer still reads collided generic `latest:coinank:*` keys and
   a nonexistent consolidated `v2:market:kucoin:{symbol}` object.  Bind only
   final, fresh, endpoint-identified component contracts with receipts.
3. The legacy trainer must reject/mask unsupported, null, incomplete, stale,
   or temporally invalid global CoinAnk values and quarantine the historical
   contaminated interval documented above.
4. Only after those consumers pass should CoinAnk be packaged/restarted in a
   staged warm-up, then checked for two visits, `cadence_observed`, actual
   revisit, semantic-valid coverage, and last-known-good behavior.  Coordinate
   the remaining CoinGlass/liquidation services afterward.
5. Adaptive authority must remain off until trainer, paper-entry, open-position,
   risk, and execution consumers prove the two-scope contract.  Activation is
   an explicit later operator decision, not part of this task.

No task-owned file was deleted.  The unrelated dirty worktree and its existing
`v2/package-lock.json` deletion belong to the concurrent/user lane and were not
modified or reverted here.
