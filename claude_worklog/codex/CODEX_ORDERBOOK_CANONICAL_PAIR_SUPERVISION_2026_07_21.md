# Canonical direct-orderbook pair supervision — 2026-07-21

## Outcome

The active direct order-book recorder already owns the exact pair required by
authenticated cost evidence:

- `v2:orderbook:depth:binance:{symbol}` with schema
  `direct_orderbook_depth_v1`;
- `v2:orderbook:features:binance:{symbol}` with schema
  `direct_orderbook_features_v1`.

The older `v2_orderbook_features_publisher` was not the canonical owner.  It
read generic `v2:market:orderbook:*` echoes and was intended to overwrite the
canonical feature key with a different schema.  At audit time those generic
echoes carried current clocks but no bid/ask arrays, so the worker wrote zero
features and incorrectly reported all 157 symbols as stale.  The direct
recorder's actual depth and feature pairs were fresh for all 157 symbols.

This slice makes the redundant worker a summary-only supervisor.  It validates
the direct pair's schema, producer, exchange, symbol, sequence/gap fields,
event/received/available/generated clock order, freshness, and exact paired
identity fields.  It can now write only
`v2:orderbook:features:summary`; the write helper rejects every per-symbol key.

## Authority and causal contract

The supervisor grants no trainer or consumer authority.  Its summary fixes:

- `features_written=0`;
- `per_symbol_feature_write_authorized=false`;
- `trainer_admission_authorized=false`;
- `consumer_eligible=false`;
- `paper_only=true` and `live_gate=blocked_human_only`.

The canonical recorder remains the only per-symbol writer.  Authenticated
training still has to capture the exact Redis bytes, persist them in CAS, bind
the atomic read receipt, and rederive the economic fields.  A healthy
supervision summary cannot substitute for any of those steps.

No exchange endpoint, order path, leverage, margin, allocator, risk, trainer,
paper-loop, model, prediction, or live-execution service was changed or
restarted by this code slice.

## Runtime evidence

At the read-only observation on 2026-07-21, the dynamic universe contained 157
symbols.  Every symbol had a present, correctly shaped, clock-valid, fresh,
derivable direct depth payload from `direct_binance`.  After the stricter pair
check, all 157 depth/feature pairs matched and zero reasons were reported.

This is transport/pair evidence, not authenticated trainer admission evidence.

## Validation

- 8 focused unit tests passed.
- Python compilation passed for the worker and its tests.
- Ruff fatal selectors `E9,F63,F7,F82` passed.
- `git diff --check` passed.
- A read-only real-Redis inventory reported `157/157` exact direct pairs
  healthy and no rejection reasons.

The branch is not deployed by this commit.  Deployment requires an immutable
release plus post-start verification that only the summary key changed and the
canonical direct pair remains owned by `v2_direct_orderbook_recorder`.
