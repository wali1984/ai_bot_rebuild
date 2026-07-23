# Canonical OHLCV Writer-Receipt Consumer Checkpoint — 2026-07-23T06:20:16Z

## Immutable checkpoint

- Branch: `codex/strategy-receipt-promotion-20260723`
- Source commit: `0bcb67108275058d5d27f67e5236b5c6cf0e4801`
- Remote: `origin/codex/strategy-receipt-promotion-20260723`
- Push divergence after source push: `0 ahead / 0 behind`
- Production module SHA-256:
  `f412790842273113c44c4c142d37b6c7468a85801ffb536379376ab23304103f`
- Test module SHA-256:
  `7cf9b711d4d863a649f792004a112ee41c75c61b4056217daa18d143bbbfaf2a`
- Known defects in this component family: **0**

## Scoped result

The new consumer independently verifies the current canonical Binance closed
OHLCV writer publication before any transform or strategy code can rely on it.
It does not trust the mutable canonical Redis value by itself.

The read boundary is:

1. Discover the latest immutable revision pointer in one bounded, raw-binary,
   read-only Redis transaction.
2. Reopen the canonical value, immutable archive, writer receipt, and current
   pointer in one ordered four-key transaction.
3. Retry only bounded pointer or prepare races.
4. Require byte-identical canonical/archive content and the same pointer in
   both reads.
5. Independently rederive the complete writer receipt, publication revision,
   cadence-bounded TTL contract, source schema, finality, freshness, and causal
   clock order.
6. Require an explicit role-to-code-hash allowlist for the WSS and REST writers.
7. Reject the legacy existing-payload adopter, unknown roles, and cross-role
   code hashes.
8. Store exact canonical, receipt, pointer, and tuple-manifest bytes in the
   immutable content-addressed store and freshly reopen all four objects.

No trainer admission, feature publication, prediction, paper-trading, margin,
leverage, or live-execution authority is granted by this boundary.

## Exact trust boundary

Accepted producer roles: **2/2**.

- `BINANCE_USDM_KLINE_WSS_CANONICAL_CLOSED_WINDOW_V1`
- `BINANCE_USDM_KLINE_REST_CANONICAL_CLOSED_WINDOW_V1`

Explicitly rejected producer role: **1/1**.

- `CANONICAL_CLOSED_WINDOW_EXISTING_PAYLOAD_ADOPTER_V1`

The trusted code hashes are caller-supplied immutable-release configuration.
They are never learned from the receipt under validation. Both accepted roles
must be present, each hash must be a lowercase SHA-256, duplicate hashes and
cross-role collisions fail closed, and the bounded allowlist is itself
canonicalized and bound into the consumer manifest.

## Point-in-time and finality proof

The consumer requires this causal order for every accepted capture:

`source available_at <= writer publication_available_at <= discovery Redis TIME <= authoritative reopen Redis TIME <= consumer_observed_at`

The canonical schema independently retains and checks `event_time`,
`ingested_at`, and `available_at`. Every candle must be final, and the latest
economic close must equal the latest interval completed at the authoritative
Redis observation. An unfinished candle, stale window, future availability,
future publication, or reversed discovery/reopen clock fails closed.

This boundary does not invent a feature cutoff or decision time. Those clocks
remain held for the deterministic transform and strategy-output families.

## Evidence counts

- Routes inspected: **1** strategy input route chain
- Mutable inputs identified: **2**
- Mutable input admitted by this family: **1** canonical OHLCV family
- Mutable input deliberately excluded: **1** unreceipted
  `v2:live_gate:state`
- Redis read transactions verified per capture: **2**
- Exact Redis members compared: **5** (**1** discovery + **4** authoritative)
- Writer roles accepted / adopter roles rejected: **2 / 1**
- Writer receipt fields checked: **39/39**
- Consumer manifest fields checked: **41/41**
- Frozen writer/consumer authority fields checked: **12/12 false**
- Immutable CAS objects written and freshly reopened per capture: **4/4**
- New focused test cases: **34**
- Focused tests, second-agent run: **34/34 passed**
- Focused tests, primary-agent final run: **34/34 passed**
- Bounded dependency regression files: **5**
- Bounded dependency regression tests: **380/380 passed**
- Files compiled: **2/2**
- Files passing full configured Ruff: **2/2**
- Whitespace findings: **0**
- Defects exposed by adversarial tests: **2**
- Defects fixed and regression-covered: **2/2**
- Defects remaining in this family: **0**
- Product routes / screenshots / endpoints compared / builds: **0 / 0 / 0 / 0**
- Runtime services changed / Redis runtime keys changed / exchange actions:
  **0 / 0 / 0**

The two exposed defects were incomplete post-return capture-field rebinding
and a missing discovery-to-authoritative Redis clock-order assertion. Both are
now exact-manifest regression cases.

One pre-existing `pytest-asyncio` loop-scope configuration deprecation warning
appeared during test collection/runs. It did not affect the 380 passing tests
and was not introduced by this slice.

## Exact files in the source commit

1. `v2/backend/app/services/native_trainer/canonical_ohlcv_writer_receipt_consumer_v1.py`
2. `v2/backend/tests/unit/services/native_trainer/test_canonical_ohlcv_writer_receipt_consumer_v1.py`

Source diff: **2 files / 2,462 insertions / 0 deletions**.

## Commands executed

```text
rg/sed targeted reads of the strategy input chain, canonical writer contract, atomic Redis reader, immutable CAS store, OHLCV schema, and existing canonical adapter
python -m py_compile v2/backend/app/services/native_trainer/canonical_ohlcv_writer_receipt_consumer_v1.py
<repo-venv>/bin/ruff check <production module> <focused test module>
<repo-venv>/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_canonical_ohlcv_writer_receipt_consumer_v1.py
<repo-venv>/bin/python -m pytest --collect-only -q <five bounded writer/reader/schema/CAS/consumer test files>
<repo-venv>/bin/python -m pytest -q <five bounded writer/reader/schema/CAS/consumer test files>
git diff --check
git add -- <two exact source/test files>
git commit -m 'feat(trainer): verify canonical writer receipts'
git push origin codex/strategy-receipt-promotion-20260723
git show --stat --oneline --decorate HEAD
sha256sum <production module> <focused test module>
git rev-list --left-right --count '@{upstream}'...HEAD
```

## Runtime and execution boundary

This source family was not deployed or wired into the strategy publisher. No
service was started, stopped, restarted, or released from hold. No Redis
runtime value was changed outside ephemeral test servers. No paper or live
order, position, leverage, margin, or risk behavior changed.

## Next gate

Build the isolated composite strategy-input wrapper that requires both this
writer-publication proof and the existing per-candle exact-read/CAS adapter,
then bind their identical source bytes into the deterministic TA/transform
manifest. Keep `v2:live_gate:state` outside authenticated strategy economics
until it receives its own point-in-time receipt. Keep the strategy publisher
held until the input transform and output/admission receipt families are both
complete.
