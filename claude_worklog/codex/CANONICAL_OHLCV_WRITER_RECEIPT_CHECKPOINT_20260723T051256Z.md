# Canonical OHLCV Writer-Receipt Checkpoint — 2026-07-23T05:12:56Z

## Immutable checkpoint

- Branch: `codex/strategy-receipt-promotion-20260723`
- Source commit: `c1134da0a6188238a473f8ffc2ca146833a09d06`
- Source push divergence: `0 ahead / 0 behind`
- Runtime deployment: **not deployed**
- Service changes/restarts: **0**
- Remaining blocker in this family: **1** — healthy pre-receipt windows need
  bounded, provenance-honest adoption before the writers can be rolled out.

## Contract implemented

Both Binance canonical closed-window writers now require one exact three-phase
publication result:

1. WATCH-bound canonical merge plus immutable revision preparation;
2. conditional receipt and latest-pointer commit while canonical and archive
   bytes still match;
3. exact canonical/archive/receipt/pointer reopen with TTL and Redis-clock
   ordering verification.

The receipt binds the canonical key, exact bytes/hash/count, row and candle
identity bounds, source clocks, end-exclusive finality, producer role, loaded
producer-code hash, configuration hash, TTL policy, publication availability,
and four explicit false authority fields. It proves publication integrity only;
it grants no trainer, prediction, paper, margin, leverage, or live authority.

Concurrent exact-revision publishers adopt the first valid receipt. A later
canonical mutation causes a bounded retry. Invalid schema, oversized values,
wrong Redis types, archive/receipt tampering, cross-symbol/timeframe
substitution, conflicting candle revisions, bad clocks, bad TTL ordering, and
unreceipted legacy/mock acknowledgements fail closed.

## Adaptive resource correction

A read-only Redis measurement found:

- canonical keys measured: **829**
- canonical payload bytes: **80,925,464**
- mean payload bytes: **97,618.2**
- largest payload bytes: **704,883**
- Redis memory at measurement: **15.43 GiB used / 32.00 GiB max**
- projected immutable payload retention if every close lived for the mutable
  86,400-second cache TTL: **31,449,297,540 bytes**
- projected cadence-bounded immutable payload retention: **323,701,856 bytes**
- reduction: **97.16x**

The mutable recovery-cache TTL remains unchanged. Evidence freshness is now
derived from each timeframe: receipt/pointer TTL is three source cadences and
archive TTL is four source cadences. Therefore an unrefreshed canonical key can
remain recoverable while becoming explicitly untrusted after its proof expires.
Consumers must fail closed until a writer publishes and reopens fresh proof.
Old revisions are not synchronously pruned because a concurrent reader may
already hold the old pointer; the cadence overlap prevents that TOCTOU outage.

## Evidence counts

- Production files changed: **3**
- Test files changed: **3**
- Total files committed: **6**
- Atomic phases reviewed: **3/3**
- Writer callers bound: **2/2**
- Affected tests after the resource correction: **160/160 passed**
- Initially exposed ordering failures: **4**
- Ordering failures fixed and rechecked: **4/4**
- Files compiled: **6/6**
- Files checked for fatal Ruff selectors: **6/6**
- Fatal lint findings: **0**
- Diff whitespace errors: **0**
- Isolated real-Redis Lua cases included: **1/1 passed**
- Runtime keys read for footprint measurement: **829**
- Routes inspected / fields checked / screenshots captured / endpoints
  compared / product builds passed: **0 / 0 / 0 / 0 / 0**
- Services deployed/restarted / Redis writes / exchange mutations:
  **0 / 0 / 0**
- Defects remaining in this family: **1**

## Exact files in source commit

1. `v2/backend/app/services/market_state_integrity/closed_window_redis_store.py`
2. `v2/backend/app/cli/v2_binance_kline_wss_loop.py`
3. `v2/backend/app/cli/v2_binance_kline_rest_backfill.py`
4. `v2/backend/tests/unit/services/market_state_integrity/test_closed_window_redis_store.py`
5. `v2/backend/tests/unit/cli/test_v2_binance_kline_wss_label_archive_outbox.py`
6. `v2/backend/tests/unit/cli/test_v2_binance_kline_rest_backfill_atomic_recovery.py`

## Verification commands

```text
PYTHONPATH=/tmp/codex-strategy-receipt-promotion:/tmp/codex-strategy-receipt-promotion/v2/backend /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q <three affected test modules>
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile <six changed Python files>
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/ruff check --select E9,F63,F7,F82 <six changed Python files>
git diff --check
git diff --cached --check
git commit -m 'feat(ohlcv): receipt canonical window publications'
git push origin codex/strategy-receipt-promotion-20260723
```

## Deployment gate

**NO-GO.** Do not advance either writer service yet. Land and test the
healthy-window adoption path first, then build the independent consumer
read/CAS receipt before releasing strategy supply. The strategy publisher and
all paper/live authority remain held.
