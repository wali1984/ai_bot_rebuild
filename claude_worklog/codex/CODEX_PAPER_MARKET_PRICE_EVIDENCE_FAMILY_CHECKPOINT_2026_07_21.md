# Codex Paper Market-Price Evidence Family Checkpoint — 2026-07-21

## Checkpoint status

Component-family implementation and adversarial validation are complete on an
isolated branch. This checkpoint is not a deployment record. No service was
restarted, no Redis state was changed, and no exchange/live transport was
touched.

- Approved base: `f06277824efacb58ac5f83f1d42eca4a56adabe8`
- Branch: `codex/paper-market-price-evidence-f062-20260721`
- Worktree: `/tmp/codex-paper-market-price-evidence-f062`
- Scope: paper entry and paper lifecycle market-price evidence only
- Explicitly out of scope: live/order transport, leverage, margin, atomicity,
  trainer provenance receipts, feature-worker release, service deployment, and
  service restart

## Blocker closed by this component family

The approved base read a number from either
`v2:market:prices:{symbol}.ticker_24hr.lastPrice` or
`v2:features:latest:{symbol}:1m.features.*` without proving that the payload was
bound to the requested key, symbol, timeframe, final candle/event clock, or
consumer lookup. A wrong-symbol/wrong-timeframe payload under a requested Redis
key could therefore become an entry or lifecycle mark. The lifecycle service
also replaced a rejected/missing mark with the previous/entry mark and could
continue an exit evaluation without verified current evidence.

The new path makes both consumers use a structured, content-addressed evidence
envelope and fail closed when any binding is absent or inconsistent.

## Canonical evidence contract

Schema: `V2_PAPER_MARKET_PRICE_EVIDENCE_V1`

Every valid envelope binds:

- requested Redis key;
- requested normalized symbol;
- requested normalized timeframe;
- source kind and source label;
- exact selected field and finite positive selected value;
- source event time;
- final candle close for the feature branch;
- producer availability clock and the exact field that supplied it;
- consumer lookup-observed clock captured after the Redis `get`;
- freshness interval derived from the requested timeframe;
- canonical source-material SHA-256;
- full source-payload SHA-256;
- consumer evidence-receipt SHA-256, including the lookup clock;
- explicit `paper_only=true`, `routes_to_live=false`, and
  `places_real_order=false` routing flags.

### Clock rules

ISO clocks must contain an explicit UTC offset resolving to UTC. Naive ISO
timestamps and non-UTC offsets are rejected. Integral epoch seconds or epoch
milliseconds are accepted as unambiguous UTC. Boolean, floating-point, missing,
non-finite, malformed, and out-of-range clocks are rejected.

For the source temporal cutoff `t_source`, source availability `t_available`,
and post-read lookup observation `t_lookup`, validity requires:

```text
t_source <= t_available <= t_lookup
0 <= t_lookup - t_source <= duration(requested_timeframe)
```

The freshness budget is therefore adaptive to the requested market interval.
No independent fixed market-staleness threshold was introduced.

### Ticker branch

- Requested key: `v2:market:prices:{SYMBOL}`
- Selected field: `ticker_24hr.lastPrice`
- Temporal cutoff: `ticker_24hr.closeTime`
- Availability: explicit top-level `available_at`, otherwise the producer's
  top-level `fetched_utc` retained under its real field name
- Required binding: top-level `symbol == requested symbol`; a nested ticker
  symbol, if supplied, must also match
- A supplied payload/nested timeframe must match the requested timeframe
- Semantics remain a point event. The ticker `closeTime` is never relabelled as
  a candle close.

### Feature branch

- Requested key: `v2:features:latest:{SYMBOL}:{TIMEFRAME}`
- Selected fields, in order: `features.close_price`, `features.last_price`,
  `features.lastPrice`
- Required payload symbol/timeframe equality
- Required `feature_freshness_state == CURRENT`
- Required `candle_closed_confirmed is true`
- Required `latest_candle_temporally_valid is true`
- Required strict UTC `candle_close_time`
- Required `feature_cutoff == candle_close_time`
- Required strict UTC `available_at`

On the approved base, feature snapshots whose exact publication availability
receipt is still absent remain rejected. This is intentional: this component
does not bypass the upstream provenance hold. The ticker branch remains usable
when its canonical producer fields are present and current.

## Hash and tamper model

Three hashes serve distinct purposes:

1. `source_payload_hash_sha256` identifies the exact decoded Redis payload.
2. `source_hash_sha256` binds the canonical source projection used for price
   selection and PIT validation.
3. `evidence_hash_sha256` binds the requested identity, selected value, all
   canonical clocks including post-read lookup, freshness derivation, source
   hashes, and paper-only route flags.

Entry attachment and lifecycle consumption recompute the hashes and semantic
bindings. A copied envelope whose price, source material, or lookup clock is
changed is rejected.

## Runtime consumer behavior

### Entry

1. Read ticker evidence; if invalid, read feature evidence.
2. Return a numeric tuple only after full evidence verification against the
   requested symbol and out-of-band requested `1m` price timeframe.
3. Reverify the envelope while attaching entry/fill/latest-price provenance.
4. On rejection, attach no entry/fill/latest numeric price and set the existing
   `MISSING_V2_MARKET_PRICE_FOR_FILL` blocker.
5. The existing pre-fill/post-fill evidence gates and fill-write invariant then
   prevent an economic paper fill.

### Lifecycle

1. Build structured mark evidence for symbols in new accepted fills and for
   symbols already present in `open_positions`/`positions_by_symbol`.
2. Pass the expected `1m` price timeframe separately from the evidence so the
   envelope cannot self-assert a different binding.
3. Recompute evidence validity and require the mapped numeric price to equal
   the bound selected value.
4. On rejection, return no mark and do not substitute the previous/entry mark.
5. Preserve the position unchanged and emit a non-close evaluation with
   `VERIFIED_MARKET_PRICE_EVIDENCE_REQUIRED`.
6. No close event, outcome label, or trainer-feedback row is created from the
   rejected mark.

Legacy direct lifecycle tests that intentionally pass an unstructured float or
mapping remain unchanged. The production paper loop explicitly opts into the
strict structured path with `market_price_evidence_required=true`.

## Adversarial evidence counts

New dedicated suite result: **25 passed**.

- 2 valid source controls: ticker point event and final closed feature candle.
- 18 malformed/unsafe source cases rejected:
  - wrong ticker/feature symbol;
  - wrong ticker/feature timeframe;
  - missing close/event clock;
  - naive availability clock;
  - future availability clock;
  - inverted event/availability clocks;
  - stale ticker event;
  - unfinished feature candle;
  - non-current feature freshness;
  - non-finite selected price;
  - stale feature candle;
  - feature-cutoff/final-close mismatch.
- 3 post-construction tamper variants rejected: selected price, canonical
  source material, and lookup-observed clock.
- 1 symbol-union proof: existing open positions receive strict lifecycle marks
  even when there is no new fill for that symbol.
- 1 invalid-entry proof: no entry/fill price and pre-fill evidence rejection.
- 1 invalid-lifecycle proof: no close, no outcome, and no trainer row.
- 1 positive lifecycle sensitivity control: the same valid 102 mark closes the
  100 entry under the configured test take-profit rule.

The categories overlap within parameterized pytest items; the authoritative
test-run count is 25 passed.

## Validation results

### Green scoped validations

```text
python -m py_compile \
  v2/backend/app/services/paper_trade_management/market_price_evidence.py \
  v2/backend/app/services/paper_trade_management/lifecycle.py \
  v2/backend/app/cli/v2_trade_management_paper_loop.py
```

Result: pass.

```text
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check \
  v2/backend/app/services/paper_trade_management/market_price_evidence.py \
  v2/backend/tests/unit/services/paper_trade_management/test_market_price_evidence.py
```

Result: all checks passed.

```text
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/pytest -q \
  v2/backend/tests/unit/services/paper_trade_management/test_market_price_evidence.py
```

Result: `25 passed`.

```text
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/pytest -q \
  v2/backend/tests/integration/cli/test_v2_paper_ledger_fill_price_provenance.py \
  -k 'read_v2_market_price or attach_entry_price_provenance'
```

Result: `6 passed, 26 deselected`.

### Broader regression comparisons

```text
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/pytest -q \
  v2/backend/tests/unit/cli/test_v2_trade_management_paper_loop.py
```

Branch result: `426 passed, 3 failed`. Clean approved-base result:
`426 passed, 3 failed`, with the same failures:

- two `app.cli` alias imports resolve the main workspace's later CLI file and
  request `PreemptiveReplayError`, absent from the approved-base decision
  module;
- portfolio cascade guard omits `CALMUSDT` under the test's breach input.

```text
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/pytest -q \
  v2/backend/tests/unit/services/paper_trade_management/test_lifecycle.py
```

Branch result: `97 passed, 1 failed`. The same single failure reproduces on the
clean approved base: `squeeze_evidence_score` is `0.0`, expected `0.74`.

```text
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/pytest -q \
  v2/backend/tests/integration/cli/test_v2_paper_ledger_fill_price_provenance.py
```

Branch result: `31 passed, 1 failed`. The same failure reproduces on the clean
approved base: on cycle two the accepted list is empty after the pre-existing
position-reconstruction failure, so the test cannot index `accepted[0]`.

These inherited failures were not modified because reconstruction, preemptive
replay, squeeze feedback, and portfolio cascade behavior are outside this
component-family scope.

## Files changed by this checkpoint

- `v2/backend/app/services/paper_trade_management/market_price_evidence.py`
- `v2/backend/app/cli/v2_trade_management_paper_loop.py`
- `v2/backend/app/services/paper_trade_management/lifecycle.py`
- `v2/backend/tests/unit/services/paper_trade_management/test_market_price_evidence.py`
- `v2/backend/tests/integration/cli/test_v2_paper_ledger_fill_price_provenance.py`
- `claude_worklog/codex/CODEX_PAPER_MARKET_PRICE_EVIDENCE_FAMILY_CHECKPOINT_2026_07_21.md`

## Operator handoff

This branch is safe to review/cherry-pick as a paper-only component slice. It
does not authorize deployment or restart. After integration, the owner should
deploy the normal paper-loop artifact and observe evidence rejection counts
before expecting lifecycle closes. Feature fallback will remain fail closed
until the upstream exact publication-availability receipts are actually
available; do not force `CURRENT` or fabricate availability to increase supply.
