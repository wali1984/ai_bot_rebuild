# Canonical OHLCV Healthy-Window Adoption Checkpoint — 2026-07-23T05:39:49Z

## Immutable checkpoint

- Branch: `codex/strategy-receipt-promotion-20260723`
- Source commit: `a7d07f32a1e332d0a0480a38b3609529bf294ea4`
- Source push divergence: `0 ahead / 0 behind`
- Runtime deployment: **not yet deployed**
- Services changed/restarted: **0**
- Known defects remaining in this slice: **0**

## Exact migration contract

The WSS worker can now create publication-integrity receipts for the current
runtime Cartesian symbol/timeframe set without waiting up to four hours for
the next higher-timeframe close. The migration path:

1. resolves only the current adaptive universe and configured timeframes;
2. performs no key scan and no REST/HTTP/provider request;
3. WATCHes the exact canonical key and its latest receipt pointer;
4. bounded-reads the exact bytes and Redis clock;
5. validates schema, source clocks, end-exclusive finality, and the latest
   expected completed interval;
6. preserves the canonical bytes and their existing PTTL exactly;
7. creates a cadence-bounded immutable archive and receipt;
8. refuses to overwrite a valid or concurrently appearing writer pointer;
9. atomically reopens canonical/archive/receipt/pointer and re-derives every
   receipt/revision binding.

An existing WSS, REST, or prior adopter receipt is reopened instead of
replaced. A malformed pointer, missing/tampered artifact, wrong Redis type,
oversized payload, dirty/unfinished/future row, clock violation, orphan
receipt conflict, or exhausted mutation race fails closed.

All synchronous Redis adoption calls run serially in one `asyncio.to_thread`
worker after the WebSocket consumer tasks have been scheduled. Per-pair
failures are counted without cancelling the seven WSS consumers. Successful
pairs remain suppressed during the current membership epoch; removed pairs
are discarded from that set so a later re-entry is retried.

## Provenance boundary

The distinct producer role is
`CANONICAL_CLOSED_WINDOW_EXISTING_PAYLOAD_ADOPTER_V1`. Its receipt proves only
that exact, schema-valid, final bytes existed and were archived/reopened at the
recorded Redis time. It does **not** prove the legacy writer identity, original
code/configuration, or Binance authenticity. Both
`producer_authenticity_verified` and `legacy_source_authenticity_verified`
remain false, as do trainer, prediction, paper, and live authority.

Downstream strategy admission must accept only independently allow-listed
genuine WSS/REST producer receipts. The adopter prevents a migration blind
spot; it does not manufacture source provenance.

## Evidence counts

- Production files changed: **2**
- Test files changed: **2**
- Total files committed: **4**
- New focused tests: **18**
- Final affected tests: **242/242 passed**
- Real Redis adoption Lua cases: **1/1 passed**
- Files compiled: **4/4**
- Files checked with fatal Ruff selectors: **4/4**
- Fatal lint findings: **0**
- Diff whitespace errors: **0**
- Planned active pairs proved in test: **795/795**
- Timeframe counter families: **5/5**
- Adoption worker threads scheduled: **1**
- REST/HTTP calls added: **0**
- Redis SCAN calls added: **0**
- Routes inspected / fields checked / screenshots captured / endpoints
  compared / product builds passed: **0 / 0 / 0 / 0 / 0**
- Runtime Redis writes / exchange calls / orders / leverage changes / margin
  changes: **0 / 0 / 0 / 0 / 0**
- Known slice defects: **0**

## Exact files in source commit

1. `v2/backend/app/services/market_state_integrity/closed_window_redis_store.py`
2. `v2/backend/app/cli/v2_binance_kline_wss_loop.py`
3. `v2/backend/tests/unit/services/market_state_integrity/test_closed_window_redis_store.py`
4. `v2/backend/tests/unit/cli/test_v2_binance_kline_wss_adaptive_universe.py`

## Verification commands

```text
PYTHONPATH=/tmp/codex-strategy-receipt-promotion:/tmp/codex-strategy-receipt-promotion/v2/backend /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q <four affected test modules>
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile <four changed Python files>
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check --select E9,F63,F7,F82 <four changed Python files>
git diff --check
git diff --cached --check
git commit -m 'feat(ohlcv): adopt existing windows safely'
git push origin codex/strategy-receipt-promotion-20260723
```

## Next gate

Deploy the two canonical writers from one immutable release, verify adoption
counts and memory bounds, and allow genuine WSS receipts to supersede adopter
receipts by timeframe. Keep strategy supply held until its independent
writer-receipt allow-list, exact consumer read/CAS receipt, and deterministic
transform manifest are implemented and tested.
