# Codex Review: V2 Full Observation Liquidation Aggregator Burndown

Generated: `2026-05-17T22:50:14Z`

GO/NO-GO: `V2_FULL_OBSERVATION_LIQUIDATION_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`

## Decision

Codex passes the liquidation burndown as real partial progress. The builder now uses the V2-native liquidation observation aggregator and increases the full-observation generated dimensions by four per symbol without padding, hiding missing fields, or claiming parity.

This is not complete full-observation parity. It does not approve checkpoint compatibility, policy architecture parity, production equivalence, live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, or legacy shutdown.

## Runtime Continuity

- 6h soak remains passed: `soak_6h_ready=true`.
- Current soak evidence: `1246.87` observed minutes.
- Continuous remediation governor: `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`.
- V2/remediation processes: `12/12` running.
- V2 Redis namespaces are non-empty.
- Comparator and legacy log observer are fresh.
- Full observation builder payload is fresh.
- `live_gate=blocked_human_only`; `live_symbols=[]`.

## Burndown Evidence

Refreshed active builder status reports:

| Symbol | Prior generated dim | Current generated dim | Delta |
| --- | ---: | ---: | ---: |
| `BTCUSDT` | `144` | `148` | `+4` |
| `ETHUSDT` | `144` | `148` | `+4` |
| `SOLUSDT` | `139` | `143` | `+4` |

Liquidation subfamily progress:

- per symbol: `4/12 -> 8/12`
- aggregate: `12/36 -> 24/36`
- target full observation dimension remains `1911`
- state remains `FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS`

The four still-missing liquidation fields remain explicit for every symbol:

- `latest_liquidation_notional`
- `latest_liquidation_side_long`
- `latest_liquidation_side_short`
- `liquidation_notional_1h_proxy`

All four carry `MISSING_FROM_V2_LIQUIDATION_AGGREGATOR`.

## Source Discipline

Reviewed source:

- `v2/backend/app/services/rl_core/liquidation_observation_aggregator.py`
- `v2/backend/app/cli/v2_liquidation_observation_aggregator_status.py`
- `v2/backend/app/services/rl_core/full_observation_builder.py`

The aggregator consumes only V2-owned sources:

- `v2:features:latest:{symbol}:{timeframe}` for `last_liq_bps_24h`;
- `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json` for V2 CoinAnk intelligence freshness and global aggregate data.

No legacy Redis liquidation keys or legacy `features:*` keys are consumed as current truth. Redis probes also show no V2 per-symbol liquidation aggregator keys exist today:

- `v2:liquidations*`: `0`
- `v2:market:liquidations*`: `0`
- `v2:liquidation*`: `0`
- `v2:ingestor:liquidations*`: `0`
- `v2:binance:liquidations*`: `0`

The global CoinAnk liquidation count is labeled `V2_COINANK_GLOBAL_AGGREGATE_NOT_PER_SYMBOL`; it is not presented as per-symbol liquidation market data. The `v2_liquidation_source_available=0.0` field is an explicit source-availability probe flag, not a market-data substitute.

## No Fabrication

Codex verified:

- `zero_filled_field_count=0` for all symbols;
- `no_zero_fill_for_unknown_fields=true`;
- missing fields remain `None` with explicit source labels;
- generated dims are not padded to `1911`;
- checkpoint compatibility remains false;
- policy architecture parity remains false;
- `FULL_OBSERVATION_BUILDER_COMPLETE` is not claimed.

## Validation

- Refreshed liquidation aggregator status: `24/36` aggregate present.
- Refreshed full-observation builder status: generated dims `148`, `148`, `143`.
- Focused tests: `27 passed` for liquidation/full-observation lane.
- Additional builder/bridge regression run: `27 passed`.
- `py_compile`: PASS for liquidation aggregator, liquidation CLI, full observation builder, and builder CLI.
- Torch/pickle load scan: PASS.
- Legacy current-truth scan: PASS, no legacy Redis `features:*` or liquidation-key reads.
- Old Redis write scan: PASS, no write calls in reviewed builder/aggregator paths.
- Exchange mutation scan: PASS.
- Approval/live/shutdown drift scan: PASS.
- Raw secret scan: PASS.
- `git diff --check`: PASS for reviewed files/artifacts.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Remaining Blockers

- Full observation remains partial.
- A V2-native per-symbol liquidation time-series aggregator is still missing.
- Token metrics and onchain families remain external-source-required.
- `ccxt_ohlcv` remains operator-decision-required.
- Checkpoint compatibility remains false.
- Policy architecture parity remains false.
- Production equivalence, legacy shutdown, and live trading remain blocked.

## Final Decision

`V2_FULL_OBSERVATION_LIQUIDATION_BURNDOWN_CODEX_PASS_PARTIAL_PROGRESS`
