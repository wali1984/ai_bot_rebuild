# Strategy-Supply Authority and Causal-Input Remediation — 2026-07-21

## Verdict

The remediated source slice is **GO for independent review** and **NO-GO for
runtime deployment**.  No service was restarted, no Redis development write
was performed, and no live-exchange path was modified.

This slice makes strategy-supply output an observation-only research source.
It cannot create canonical prediction, signal, candidate, feature-snapshot,
risk, orchestrator, allocator, sizing, paper-fill, trainer-admission, A+, or
live authority.  The target return is not guaranteed; these changes improve
the integrity of the evidence used to pursue it.

## Root causes corrected

1. Strategy price and TA could be read from different mutable market views.
   A price alias could therefore move independently of the exact closed-candle
   window used for TA, and a later read could create a same-decision TOCTOU.
2. Optional provider payloads could be treated as useful context without an
   exact retained-artifact resolver and verified post-commit receipt.
3. The A+ inventory projected a research hypothesis into synthetic trainer,
   risk, orchestrator, allocator, and canonical lineage identities.
4. A source row could claim `consumer_eligible`, trainer admission, sizing,
   `available_at`, canonical IDs, or PASS decisions and have those claims look
   effective in the inventory.
5. Generator exceptions relabeled the exception-observation time as feature
   cutoff, decision time, and output availability.
6. Strategy-shadow feedback that had a sound future label could survive in the
   authenticated trainer Redis lane despite lacking authenticated profiled
   entry-corpus provenance.

## Resulting low-level contract

### Exact causal price/TA input

`load_causal_native_ta()` performs one binary GET of
`v2:market:ohlcv_closed:binance:{symbol}:{timeframe}`.  The existing canonical
closed-window validator establishes ABI, symbol/timeframe identity, closed
candle finality, continuity, exact payload SHA-256, exact byte count, candle
IDs, raw-payload hashes, and the maximum input `available_at`.

The strategy reference price is the close of the validator-selected last
closed candle.  Its contract binds:

- the exact OHLCV Redis key, payload SHA-256, and byte count;
- selected candle ID and raw-payload hash;
- candle open, close, `event_time`, `ingested_at`, and `available_at` clocks;
- the feature cutoff and maximum window input-availability clock; and
- `exact_binary_read_shared_with_ta=true`,
  `second_price_source_read_performed=false`, and `fallback_used=false`.

The price is explicitly research-only:
`sizing_authority_granted=false`, `consumer_eligible=false`,
`trainer_consumable=false`, `trainer_admission_granted=false`, and
`live_execution_authorized=false`.

### Optional providers

CoinGlass, Moralis, cached confluence, liquidation, microstructure, and other
optional compatibility keys are not read by this decision path.  They remain
masked until a resolver can verify exact retained bytes plus an independent
post-commit receipt.  Their absence does not stop the generator from using the
canonical closed-candle input; it only prevents those providers from
contributing a feature or strategy family.

This is compatible with Moralis being optional and rate-limited and with
CoinAPI remaining optional/dormant.  It does not disable either provider's
future integration.

### Output clocks and authority

For a normal hypothesis:

- `feature_cutoff` is the selected closed candle's economic close time;
- `input_available_at` is the maximum availability time of the exact validated
  input window;
- `decision_time` is the in-process strategy decision clock;
- `generated_at` is the serialization clock; and
- effective output `available_at` stays null until an exact post-commit
  readback receipt exists.

A generator failure has only `failure_observed_at`/`generated_at`.  It has no
feature cutoff, input availability, decision time, output availability, or
trainer/consumer authority.

### A+ inventory projection

The inventory retains research economics and a clearly named
`inventory_observation_id`, but effective canonical fields are null:

- `candidate_id`, `prediction_id`, `trainer_prediction_id`, `signal_id`,
  `preemptive_decision_id`, `feature_snapshot_id`;
- risk, orchestrator, and allocator decision IDs; and
- leverage, margin mode, gross/target notional, and sizing authority.

Risk and orchestrator are blocked/denied.  Allocator output is a blocked packet
with a separately labeled diagnostic simulation.  Any producer assertions are
retained only under `source_*_claim` fields; they do not change effective
authority.  The row cannot count as A+, become fill eligible, or enter the
trainer lane.

### Shadow feedback cleanup

`merge_feedback_rows_into_redis()` now re-evaluates both existing and incoming
strategy-supply feedback at the complete profiled-trainer boundary.  A
canonical exit label remains research evidence, not authenticated entry-corpus
provenance.  Legacy or forged shadow rows are removed from
`v2:trainer:feedback:outcomes`; unrelated feedback-source rows are preserved.

The matured research ledger is not rewritten or destroyed.  On every read its
feedback projection is re-gated and forced non-consumable.

## Change-impact map

| Changed component | Direct effect | Downstream effect |
|---|---|---|
| `causal_native_ta.py` | One exact closed-window read owns TA and reference price | Removes price/TA TOCTOU and mutable price-alias bypass |
| `edge_hypothesis_generator.py` | Masks unreceipted optional sources; exports bound price lineage | Strategy families use only authenticated-in-process causal evidence |
| `v2_strategy_supply_publish_hypotheses.py` | Failure rows stop fabricating market/output clocks | Failure telemetry cannot resemble a decision or retained feature artifact |
| `v2_a_plus_candidate_inventory.py` | Research observations cannot synthesize canonical IDs/decisions/sizing | No strategy hypothesis can manufacture A+, fill, trainer, leverage, margin, risk, or orchestrator authority |
| `feedback_maturation.py` | Re-gates existing and incoming shadow feedback | Old shadow rows cannot survive or re-enter the authenticated trainer Redis lane |

## Validation

The following combined focused command passed:

```text
python -m pytest -q \
  v2/backend/tests/unit/cli/test_v2_a_plus_candidate_inventory.py \
  v2/backend/tests/unit/cli/test_v2_strategy_supply_publish_hypotheses.py \
  v2/backend/tests/unit/services/strategy_supply/test_edge_hypothesis_generator.py \
  v2/backend/tests/unit/services/strategy_supply/test_feedback_maturation.py

110 passed
```

Adversarial coverage includes mutable/future price aliases, absent canonical
OHLCV, forged CoinGlass/Moralis/confluence payloads, one-read price/TA binding,
forged consumer/trainer/sizing/PASS/ID claims, missing output receipts,
generator-failure clock integrity, future-leaking entry snapshots, legacy
canonical shadow rows, and forged incoming shadow rows.

`py_compile`, Ruff fatal selectors (`E9,F63,F7,F82`), and
`git diff --check` also passed for the changed source and tests.

## Explicit residual work

- This slice has not been independently reviewed yet.
- It is not deployed and provides no runtime-service proof.
- Adaptive strategy economics still contain legacy market-sensitive constants
  that require a separate causal calibration audit; they were not widened or
  relaxed in this authority remediation.
- Optional provider features remain masked until exact retained-artifact and
  receipt verification is implemented.
- No claim is made that research economics are profitable or that the 1000x
  target will be achieved.
