# Codex Prospective Liquidation Publication Checkpoint — 2026-07-21

## Checkpoint identity

- Branch: `codex/liquidation-levels-bridge-remediation-20260721`
- Code commit: `cf213ca2dcdfd7cbfa5027fe5605461612dd48c7`
- Remote parity after push: local HEAD and upstream were identical.
- Runtime deployment: **not performed in this checkpoint**.
- Trainer authority: **not granted by this checkpoint**.

## What this component family establishes

The prospective liquidation model now publishes immutable, content-addressed
candidate bytes through a Redis archive/receipt/pointer protocol. The protocol
uses HMAC-authenticated receipts, expected-predecessor compare-and-set,
monotonic surface clocks, distinct observation and trainer-semantic-candidate
pointers, exact-byte consumer reopen, post-validation confirmation, and TTL
relationship checks.

Publication proves storage and reopen integrity only. It always returns
`trainer_authority=false`, even when the model is semantically eligible. A
separate source-provenance and decision-time admission boundary is required
before the trainer may consume the feature.

The model also carries two explicit validity boundaries:

- `adaptive_source_valid_until`, inclusive;
- `bracket_valid_until`, exclusive.

These boundaries are derived from observed source cadence/lag and authenticated
exchange-bracket expiry. They are not static market thresholds.

## Safety properties verified

1. Archived model candidates retain `available_at=null`,
   `postcommit_receipt_bound=false`, and `trainer_authority=false`.
2. Receipt, archive, and latest pointer identities are exact-byte bound.
3. Receipt HMAC, receipt SHA-256, model self-hash, source-input hash, source
   counts, code hashes, configuration hash, clocks, identity, and scope are
   reopened and revalidated.
4. A stale writer, equal-clock/different-payload writer, or predecessor race
   cannot replace the current pointer.
5. Degraded candidates can advance the observation pointer only; they cannot
   replace the trainer-semantic-candidate pointer.
6. Archive TTL must exceed both receipt and pointer TTL. The pointer cannot
   outlive its receipt.
7. Verified payload and receipt trees are deeply immutable.
8. Publication never turns semantic eligibility into trainer authority.
9. Adaptive source validity is inclusive and bracket expiry is exclusive.
10. Oversized/noncanonical symbol, timeframe, JSON, pointer, and Redis value
    inputs fail closed.

## Evidence counts

- Changed files: 5
- Production functions reviewed: 70 (`31 model + 39 publication`)
- Redis Lua protocols reviewed: 5
- Test functions present: 76 (`54 model + 22 publication`)
- Tests directly mapped by independent review: 35
- Focused model/publication regression: **138 passed, 0 failed**
- Bounded cross-component regression: **305 passed, 0 failed**
- Actual ephemeral Redis tests: 2
  - publish / idempotent replay / exact reopen;
  - pointer-TTL inversion rejection.
- Ruff: passed
- Python compilation: passed
- Git whitespace validation: passed
- Independent final review: **0 Critical, 0 High, 1 Medium, 1 Low**

The remaining Medium item is additional real-Redis negative-path depth; the
remaining Low item is publication-pointer parameterization across every model
degradation reason. Equivalent model degradation behavior is already covered,
and neither item permits trainer authority because this layer cannot grant it.

## Files in the code checkpoint

- `v2/backend/app/services/liquidation_surface/__init__.py`
- `v2/backend/app/services/liquidation_surface/model.py`
- `v2/backend/app/services/liquidation_surface/publication.py`
- `v2/backend/tests/unit/services/liquidation_surface/test_model.py`
- `v2/backend/tests/unit/services/liquidation_surface/test_publication.py`

## Provider and semantic boundaries retained

- Prospective levels remain modeled aggregate open-position cohort estimates;
  they are not position-exact or cross-margin-exact liquidation prices.
- Binance forced-liquidation events are not used as prospective level sources.
- CoinAnk Plan3 `openInterest_kline` remains the OI source.
- No CoinAnk liquidation heatmap/map endpoint is called or required.
- Missing or stale CoinAnk OI, mark price, bracket, or finalized-candle evidence
  must yield masked/unavailable trainer features, never fabricated zeros.
- No order, leverage, margin, or live-exchange mutation path changed.

## Commands used for the final gates

```text
PYTHONPATH="$PWD/v2/backend:$PWD" .venv/bin/pytest -q \
  v2/backend/tests/unit/services/liquidation_surface/test_publication.py \
  v2/backend/tests/unit/services/liquidation_surface/test_model.py

PYTHONPATH="$PWD/v2/backend:$PWD" .venv/bin/pytest -q \
  v2/backend/tests/unit/services/altdata/test_coinank_receipts.py \
  v2/backend/tests/unit/services/altdata/test_coinank_scheduler.py \
  v2/backend/tests/unit/services/liquidation_surface/test_source_adapters.py \
  v2/backend/tests/unit/services/liquidation_surface/test_model.py \
  v2/backend/tests/unit/services/liquidation_surface/test_publication.py \
  v2/backend/tests/unit/services/test_binance_usdm_leverage_bracket_evidence.py \
  v2/backend/tests/unit/test_canonical_candles_and_mtf_snapshot.py \
  v2/backend/tests/unit/cli/test_v2_binance_mark_price_wss_seeder.py \
  v2/backend/tests/unit/cli/test_v2_binance_public_metadata_websocket_primary.py \
  v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py

.venv/bin/ruff check <five changed Python files>
.venv/bin/python -m py_compile <five changed Python files>
git diff --check
git diff --cached --check
git commit -m "Add receipt-backed liquidation surface publication"
git push
```

## Next authorized component family

Implement the sole trainer-admission boundary and producer assembly path. It
must construct candidates from exact Redis evidence through the strict source
adapters, call the authenticated Binance bracket reader itself, bind the
publication scope to that bracket security context, rederive the model, and
grant authority only for one exact `decision_id` / `decision_time` after all
point-in-time and expiry checks pass. The trainer must retain an explicit
missingness mask and continue without this feature when the evidence is not
admissible.
