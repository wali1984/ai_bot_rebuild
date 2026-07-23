# Canonical OHLCV Writer-Bound Atomic Capture Checkpoint — 2026-07-23T06:44:39Z

## Immutable checkpoint

- Branch: `codex/strategy-receipt-promotion-20260723`
- Source commit: `370d1347a451c78fb3a4ac278922f86b68b3e245`
- Remote: `origin/codex/strategy-receipt-promotion-20260723`
- Push divergence after source push: `0 ahead / 0 behind`
- Production module SHA-256:
  `ef87b28c90c41212b94c51c992a646dbc8c62e818404389d5919f4e077a877e7`
- Test module SHA-256:
  `f3d92c593b261cfe03e6c46584d9778907b2f7b64ea3076dd2794057d1f8195e`
- Known defects in this component family: **0**

## Scoped result

The new standalone composite binds two independently authenticated source
proofs without modifying either existing implementation:

1. A genuine WSS/REST writer-publication receipt and immutable four-key reopen.
2. The existing exact canonical-window capture, selected candle byte spans,
   per-candle v4 receipts, suffix identity, and immutable CAS manifest.

The composite executes this bounded receipt sandwich:

1. Pre-atomic genuine writer proof: **2** Redis transactions.
2. Per-candle atomic capture: **1** Redis transaction.
3. Post-atomic genuine writer re-proof: **2** Redis transactions.

The normal path therefore uses **5** bounded read-only Redis transactions. The
child writer consumers use one attempt each; only the outer composite may
retry, so retry costs cannot multiply without bound.

The pre/post writer revision, receipt, role, code hash, configuration hash,
allowlist hash, exact bytes, validated window, row count, and canonical CAS
address must all agree with the atomic capture. This detects both a changed
payload and a new writer revision that republishes identical payload bytes.

The wrapper remains unwired and grants no ledger, feature, trainer,
prediction, paper-trading, leverage, margin, or live-execution authority.

## Exact clock semantics

The immutable manifest preserves and validates **14** distinct ordered clocks:

```text
feature_cutoff / latest economic close
<= max producer_event_time
<= max ingested_at
<= max source available_at
<= writer publication_available_at
<= pre-writer discovery Redis TIME
<= pre-writer authoritative Redis TIME
<= pre-writer consumer_observed_at
<= atomic-adapter Redis TIME
<= atomic-adapter consumer_observed_at
<= post-writer discovery Redis TIME
<= post-writer authoritative Redis TIME
<= post-writer consumer_observed_at
<= generated_at
```

The latest candle must still be the latest completed interval at
`generated_at`. The manifest is generated before its immutable CAS write, so
it does not mislabel `generated_at` as post-publication availability. Instead,
`available_at`, `decision_time`, and `execution_time` are explicitly **null**.
Those clocks can only be added by later receipted publication and decision
boundaries.

## Retry and failure contract

Only these exact child writer races are retryable:

- `canonical_ohlcv_consumer_pointer_race_retry_exhausted`
- `canonical_ohlcv_consumer_prepare_race_retry_exhausted`

A pre/atomic/post identity change is also retryable by the bounded outer loop.
Writer tamper, unknown integrity errors, adapter validation/integrity errors,
transport failures, invalid clock order, stale-at-generation input, CAS
corruption, and authority substitution fail closed without being relabeled as
a benign race.

## Evidence counts

- Production files inspected before design: **9**
- Existing production/test dependents indexed and preserved: **7 / 10**
- Existing files modified: **0**
- New production/test files: **1 / 1**
- Child capture fields inventoried: **131**
- Composite capture fields checked: **75/75**
- Composite manifest fields checked: **72/72**
- Non-null clocks ordered / explicit null clocks checked: **14 / 3**
- Downstream authority flags checked false: **8/8**
- Unwired/market-threshold flags checked false: **2/2**
- Genuine writer roles exercised: **2/2**
- Normal-path Redis transactions: **5/5**
- Real-Redis smoke paths: **2** (**1** exposed a defect, **1** passed after fix)
- New focused test cases: **32**
- Focused tests, second-agent run: **32/32 passed**
- Focused tests, primary-agent final run: **32/32 passed**
- Existing atomic-adapter regression tests: **20/20 passed**
- Final bounded regression total: **52/52 passed**
- Files compiled / full-linted / format-checked: **2/2 / 2/2 / 2/2**
- Whitespace findings: **0**
- Defects exposed: **1**
- Defects fixed and regression-covered: **1/1**
- Defects remaining in this family: **0**
- Routes / endpoints / screenshots / product builds: **0 / 0 / 0 / 0**
- Runtime services / runtime Redis keys / exchange actions changed: **0 / 0 / 0**

The smoke defect was a constructor-placement error for the three explicit
null clocks. The first genuine Redis invocation exposed it before the test
suite; the corrected 71-row REST path and all 32 focused cases pass.

One pre-existing `pytest-asyncio` loop-scope configuration deprecation warning
appeared during collection/runs. It did not affect any passing test and was
not introduced by this slice.

## Exact files in the source commit

1. `v2/backend/app/services/native_trainer/canonical_ohlcv_writer_bound_atomic_capture_v1.py`
2. `v2/backend/tests/unit/services/native_trainer/test_canonical_ohlcv_writer_bound_atomic_capture_v1.py`

Source diff: **2 files / 1,811 insertions / 0 deletions**.

## Commands executed

```text
rg/sed targeted reads of the writer consumer, atomic adapter, its 17 indexed dependents, multitimeframe capture set, strategy native-TA route, and focused tests
<repo-venv>/bin/python - <<'PY' ... ephemeral-Redis 71-row REST writer-bound smoke ... PY
<repo-venv>/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_canonical_ohlcv_writer_bound_atomic_capture_v1.py
<repo-venv>/bin/python -m pytest --collect-only -q v2/backend/tests/unit/services/native_trainer/test_canonical_ohlcv_atomic_receipt_adapter.py
<repo-venv>/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_canonical_ohlcv_atomic_receipt_adapter.py
python -m py_compile <two new Python files>
<repo-venv>/bin/ruff check <two new Python files>
<repo-venv>/bin/ruff format <new production module>
<repo-venv>/bin/ruff format --check <two new Python files>
git diff --check
git add -- <two exact source/test files>
git commit -m 'feat(trainer): bind writer proof to atomic OHLCV'
git push origin codex/strategy-receipt-promotion-20260723
sha256sum <production module> <focused test module>
git show --stat --oneline --decorate HEAD
git rev-list --left-right --count '@{upstream}'...HEAD
```

## Runtime and execution boundary

This source contract was not deployed or wired into any publisher, trainer,
strategy generator, paper loop, or execution service. The only Redis writes
were inside disposable test servers. No service was started, stopped,
restarted, or released from hold. No paper/live order, position, leverage,
margin, allocation, or risk behavior changed.

## Next gate

Build the deterministic strategy TA/transform boundary from this composite
capture. Its semantic content hash must exclude observation wall clocks while
its audit manifest retains them; it must bind exact transform code/config
dependencies, feature cutoff, generated time, and a later availability
receipt. Keep the unreceipted `v2:live_gate:state` out of authenticated
strategy economics. Keep the strategy publisher held until the transform and
strategy-output admission receipts are both complete.
