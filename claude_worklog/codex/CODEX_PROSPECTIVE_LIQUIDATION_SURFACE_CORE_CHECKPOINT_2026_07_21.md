# Prospective liquidation-surface core checkpoint — 2026-07-21

## Immutable checkpoint

- Branch: `codex/liquidation-levels-bridge-remediation-20260721`
- Core commit: `5a55e5a5c238697e9f84cdf92cdf31a541c1cf21`
- Remote head verified equal to the core commit after push.
- Parent: `f06277824efacb58ac5f83f1d42eca4a56adabe8`
- Files committed: 4
- Lines committed: 2,410 additions
- Targeted cases: 114 passed
- Independent final-review findings: 9 passed, 0 failed, 0 blocking
- Provider calls: 0
- Runtime writes/restarts in this component family: 0
- Exchange order, cancellation, leverage, margin, transfer, or live-execution
  mutations: 0

## Exact semantic boundary

This component models prospective liquidation-price surfaces for still-open,
aggregate position cohorts. It is intentionally separate from Binance and
CoinAnk forced-liquidation streams, which report positions after liquidation
has occurred.

The output declares all of the following:

- `liquidation_semantic_kind=estimated_open_position_liquidation_surface`
- `not_position_exact=true`
- `forced_liquidation_events_used_as_level_source=false`
- forced-liquidation events may only supply causal, realized-outcome
  calibration after their event and availability clocks
- isolated USD-M geometry is modeled; cross-margin position-exactness is false
- the cumulative maintenance deduction is omitted, moving modeled levels
  toward entry on both sides, and the conservative assumption is explicit
- `trainer_authority=false` and `available_at=null` until a later producer
  performs an exact post-commit read receipt

Exact participant entry, wallet balance, added margin, leverage, position
notional, and margin mode are private. The engine therefore does not claim to
reconstruct exchange-private positions or an exchange-supplied heatmap.

## Required causal inputs per venue, symbol, and timeframe

1. Finalized price candles with exact venue/symbol/timeframe identity,
   timeframe duration and boundary, continuous sequence, OHLC geometry,
   `event_time`, `ingested_at`, `available_at`, source key, and source SHA-256.
2. At least two venue mark-price observations with causal clocks and lineage.
   Mark price drives current-side filtering and distance. Final candle close is
   only a diagnostic fallback and can never make the surface trainer-eligible.
3. Finalized open-interest periods with exact identity, feature cutoff,
   `event_time`, `ingested_at`, `available_at`, consistent unit, continuous
   timeframe sequence, source key, and source SHA-256.
4. Current authenticated exchange leverage brackets for the exact venue and
   symbol, including notional ranges, maximum initial leverage, maintenance
   margin rate, cumulative deduction metadata, fetch/ingest/availability/
   expiry clocks, and one coherent source snapshot.
5. Optional outcome calibration with a cutoff and availability no later than
   the surface as-of time. Only weights overlapping actually modeled leverage
   scenarios affect confidence.

`unknown` OI units may produce a labeled diagnostic but cannot make a trainer
feature eligible. Missing OI, mark price, or brackets similarly degrades the
surface without fabricating trainer-authoritative values.

## Calculation and adaptivity

For entry price `E`, leverage `L`, and maintenance-margin rate `m`, the declared
conservative isolated geometry is:

```text
long  = E * (1 - 1/L) / (1 - m)
short = E * (1 + 1/L) / (1 + m)
```

- Positive OI deltas create cohorts at the latest causally available finalized
  candle proxy.
- Every futures contract contributes matched long and short OI. Taker-buy flow
  is retained only as aggressor metadata; it does not fabricate directional OI.
- OI decreases reduce existing cohorts proportionally.
- All exchange-supported leverage/notional-tier scenarios are retained within
  explicit computational bounds; the bot's own leverage envelope does not cap
  the market-participant surface.
- Historical post-entry candle paths remove scenarios whose modeled
  liquidation level has already been crossed, preventing levels from
  reappearing after price recovery.
- Scenario weights use observed adverse excursions and optional causal outcome
  calibration. There is no fixed market-admission cutoff.
- Freshness budgets are derived from observed cadence plus observed causal
  publication lag for candles, OI, and mark price. The payload exposes ages,
  budgets, and per-family results; no static market freshness threshold is
  used.
- Bucketing uses tick size when proven or a data-derived distribution width.
- Source-row, cohort, scenario, level, and expansion caps are explicitly
  computational memory/CPU controls, not market thresholds.

## Point-in-time and finality invariants

- Candle: `open < close <= event <= ingested <= available <= surface_as_of`
- OI: `feature_cutoff <= event <= ingested <= available <= surface_as_of`
- Mark: `event <= ingested <= available <= surface_as_of`
- Bracket: `fetched <= ingested <= available <= surface_as_of <= generated < expires`
- Calibration: `feature_cutoff <= ingested <= available <= surface_as_of`
- Surface: all causal dependencies contribute to `feature_cutoff`,
  `ingested_at`, and `source_available_at`; bracket fetch time is included.
- `generated_at >= surface_as_of`
- Publication `available_at` remains null inside the pure model.

The later consumer must still prove:

```text
surface available_at <= PPO decision_time
MASA feature_cutoff <= PPO decision_time
```

## Verification evidence

The 114 cases cover:

- long/short formula and invalid numeric inputs
- identity, lineage, and all clock orderings
- candle/OI finality, exact timeframe duration, boundary, and continuity
- venue mark-price requirement and diagnostic fallback
- OI unit consistency and unknown-unit quarantine
- leverage-bracket canonical sequence, ranges, MMR, cumulative recurrence,
  coherent snapshot, expiry, and source lineage
- recovered-price removal for historically crossed long and short scenarios
- pre-entry excursion exclusion and OI reduction interaction
- adaptive stale-candle, stale-OI, and stale-mark rejection
- 1-minute cadence behavior in addition to the 5-minute base fixture
- calibration overlap, partial/full coverage, and overflow
- deterministic hashing and input-order independence
- finite/subnormal numeric boundaries
- source, resource, and expanded-candidate bounds
- truncation coverage remaining within `[0,1]`
- forced-liquidation semantic separation

Final commands succeeded:

```text
.venv/bin/ruff check <three engine files> <targeted test file>
.venv/bin/ruff format --check <three engine files> <targeted test file>
python3 -m py_compile v2/backend/app/services/liquidation_surface/*.py
.venv/bin/pytest -q v2/backend/tests/unit/services/liquidation_surface/test_model.py
.venv/bin/pytest --collect-only -q v2/backend/tests/unit/services/liquidation_surface/test_model.py
git diff --cached --check
git commit -m "feat(liquidation): add causal prospective surface core"
git push -u origin codex/liquidation-levels-bridge-remediation-20260721
git ls-remote --heads origin codex/liquidation-levels-bridge-remediation-20260721
```

## CoinAnk subscription boundary

CoinAnk Plan4 liquidation heatmap/map endpoints are out of subscription scope
and must not be called or made a dependency. Plan3 data may be used only when
an exact supported endpoint provides venue-bound, finalized, causally clocked
OI or related calibration evidence. The legacy heatmap-symbol capability list
is not liquidation-level data.

## Next component family

The core is committed but not deployed. The next bounded family is the source
adapter and publication receipt:

1. Parse exact finalized Binance candle and mark-price evidence.
2. Parse Plan3-supported, venue-specific CoinAnk OI without calling Plan4.
3. Consume authenticated Binance bracket evidence with its account/environment
   binding and expiry.
4. Enumerate the configured symbol universe and timeframes.
5. Publish one canonical surface per venue/symbol/timeframe, read back the exact
   bytes, bind the post-commit receipt, and keep invalid/missing inputs masked.
6. Only after producer verification, add strict optional trainer features and
   missingness/uncertainty masks. Missing liquidation data must not stop the
   trainer or create a false signal.

No service restart or runtime release is authorized by this checkpoint alone.
