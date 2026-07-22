# CoinAnk Full-Universe 5m OI Scheduler Checkpoint — 2026-07-21

## Checkpoint identity

- Branch: `codex/liquidation-levels-bridge-remediation-20260721`
- Implementation commit: `f3cfba131a`
- Parent receipt checkpoint: `39e1f0bf28`
- Provider calls during implementation: 0
- Redis writes during implementation: 0
- Service restarts during implementation: 0

This family removes the 40-symbol deep-endpoint cap from the canonical CoinAnk
OI source used by the prospective liquidation surface. It does not duplicate
OI calls per surface timeframe: one receipt-backed 5m source lane is reusable
by the 1m, 5m, 15m, 1h, and 4h surface calculations with honest temporal
resolution coverage.

## Evidence counts

- Files changed: 5
- Production implementation files changed: 2
- Runtime producer file changed: 1
- Test files changed: 3
- New fair-rotation helper functions: 2
- New/expanded focused test functions: 8
- Combined targeted tests: 282 passed, 0 failed
- Python modules compiled: 2
- Current resolved training symbols: 159
- Current Binance USD-M confirmed symbols: 666
- Surface OI lanes for the current universe: 159
- Static deep-symbol cap applied to canonical OI surface source: 0
- Plan4/liquidation heatmap calls: 0
- Defects remaining in scheduler code family: 0
- Runtime evidence still required: fresh post-restart coverage receipts

## Dynamic universe contract

On every `openInterest_kline` parameter-plan rebuild, the runtime unions and
de-duplicates:

1. the canonical published runtime universe;
2. configured trainer symbols;
3. configured CoinAnk symbols.

It then rejects labels outside the canonical `^[A-Z0-9]+USDT$` runtime
contract. The old `COINANK_ACTIVE_SYMBOL_LIMIT=40` remains applicable to other
heavy deep-dive endpoints, but no longer limits canonical OI used by the
liquidation surface.

Read-only provenance evidence at checkpoint time:

```json
{
  "symbol_profile": "dynamic_or_baseline",
  "count": 159,
  "discovered_count": 159,
  "binance_usdm_confirmed_count": 666,
  "baseline_count": 25,
  "source_path": "/home/wali/Desktop/AI BOT REBUILD/v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"
}
```

The count is not frozen in code. A later published training-universe change is
picked up on the next OI plan rebuild; the persistent cursor is normalized to
the new pool size.

## Adaptive request-budget calculation

The priority batch is derived from:

- current 5m OI lane count;
- measured start-to-start endpoint visit cadence;
- the existing data-freshness SLA;
- the existing OI RPM share;
- the existing per-visit computational call cap.

It does not use a trading, volatility, confidence, leverage, or price
threshold. Those immutable resource/data-quality bounds do not approve a
trade.

For the current 159-lane test case at a measured 90-second visit cadence:

```text
max visits inside 600 seconds = floor(600 / 90) = 6
required 5m calls per visit   = ceil(159 / 6) = 27
OI-share call ceiling/visit   = floor(30 RPM * 90 / 60) = 45
selected surface calls        = 27
estimated complete revisit    = ceil(159 / 27) * 90 = 540 seconds
remaining non-surface budget  = 45 - 27 = 18 calls/visit
```

The production code recalculates these values from measured cadence. A
1,000-symbol stress case requires 167 calls per 90-second visit but is capped
at 45 by the OI share; it reports `PARTIAL_CAPACITY` with an estimated
2,070-second revisit instead of claiming full freshness.

## Fairness and failure behavior

The 5m priority lane has its own persisted attempt cursor:

```text
coinank:scheduler:surface_oi_cursor:5m
```

The cursor advances by calls actually attempted, not successful calls. One
unavailable or invalid symbol therefore cannot monopolize the front of the
queue. Freshness remains success-ledger based, so a failed attempt advances
fairness but never becomes fresh evidence.

Duplicate parameter identities fail closed. If the universe changes, cursor
modulo normalization preserves a valid starting point without asserting that
new lanes are already fresh.

## Non-surface OI preservation

The runtime always prepends 5m to the canonical OI interval plan even if an
ambient `COINANK_TFS` value omitted it. It removes those 5m lanes from the
secondary pool, schedules the derived fair batch first, and spends only the
remaining endpoint budget on 15m/30m/1h/4h/1d (or other configured) OI lanes.
No provider call is duplicated between priority and secondary selections.

## Truthful status schema

The existing scheduler status gains these surface-specific fields:

- `surface_oi_source_timeframe`
- `surface_oi_classification`
- `surface_oi_symbol_count`
- `surface_oi_lane_count`
- `surface_oi_requested_this_tick`
- `surface_oi_successful_this_tick`
- `surface_oi_fresh_success_count`
- `surface_oi_fresh_coverage_ratio`
- `surface_oi_required_calls_for_sla`
- `surface_oi_call_budget`
- `surface_oi_planned_capacity_satisfies_sla`
- `surface_oi_attempt_budget_satisfied`
- `surface_oi_capacity_satisfies_sla`
- `surface_oi_estimated_revisit_seconds`
- `surface_oi_cursor_before`
- `surface_oi_cursor_after`
- `non_surface_oi_call_budget`

Classification is deliberately staged:

```text
WARMING_CADENCE
  -> PARTIAL_CAPACITY (when plan or actual attempts cannot meet the SLA)
  -> WARMING_FRESHNESS (capacity is adequate but not all lanes succeeded)
  -> FRESH_COVERAGE_COMPLETE
```

Attempt count never substitutes for successful freshness. `FRESH` requires
every current 5m identity to have a success-ledger timestamp inside the
data-quality SLA.

## Point-in-time result

For canonical OI, the producer-side semantic validator now evaluates finality
at `request_started_at_ms - 1`, not at the later response clock. This matches
the strict adapter rule `bar_cutoff < request_started_at_ms`; a bar that closes
at or during the request cannot make the success ledger fresh.

The later persistence clock and future Redis consumer receipt remain separate.
No scheduler status grants trainer authority.

## Test evidence

The actual runtime functions were AST-isolated and executed without starting
the persistent process or contacting CoinAnk:

- real `build_param_sets("openInterest_kline")` with 159 symbols emitted 477
  rows for 5m/15m/1h, including exactly 159 unique Binance/SWAP 5m lanes;
- real `_liquidation_surface_oi_symbols()` unioned resolved/configured symbols,
  preserved major-first ordering, removed duplicates, and rejected an invalid
  label;
- six 27-call rotations covered all 159 identities, with the cursor at 3 after
  wraparound;
- capacity, cadence, attempt, freshness, impossible-count, duplicate-identity,
  and 1,000-symbol partial-capacity cases were exercised;
- two stale universe tests were corrected to compare consumers with the
  canonical resolver instead of the obsolete `BASELINE_25_SYMBOLS[0]` order.

Final regression command:

```text
PYTHONPATH="$PWD/v2/backend:$PWD" \
  '/home/wali/Desktop/AI BOT REBUILD/.venv/bin/pytest' -q \
  v2/backend/tests/unit/services/altdata/test_coinank_receipts.py \
  v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py \
  v2/backend/tests/unit/services/liquidation_surface/test_source_adapters.py \
  v2/backend/tests/unit/services/liquidation_surface/test_model.py \
  v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py \
  v2/backend/tests/unit/test_canonical_candles_and_mtf_snapshot.py \
  v2/backend/tests/unit/cli/test_v2_binance_mark_price_wss_seeder.py \
  v2/backend/tests/unit/cli/test_v2_binance_public_metadata_websocket_primary.py \
  v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py
```

Result: `282 passed in 0.52s`, with one pre-existing `pytest_asyncio`
configuration deprecation warning. Ruff on the four changed tracked
implementation/test modules, Python compilation, `git diff --check`, and
`git diff --cached --check` also passed.

The second-agent review did not return within the bounded window and is not
counted as evidence.

## Deployment boundary

Commit `f3cfba131a` is pushed but the active user service still executes the
main-worktree projection. No restart occurred in this code family. Before
claiming live coverage, the committed producer files must be projected
byte-for-byte, compiled in the service environment, dry-planned without
provider calls, then the CoinAnk data service may be restarted and monitored
for causal receipts and staged coverage classifications.
