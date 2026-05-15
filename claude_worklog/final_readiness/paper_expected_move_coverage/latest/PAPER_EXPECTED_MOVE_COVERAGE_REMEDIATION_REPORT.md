# Paper Expected-Move After-Cost Coverage Remediation Report

Status: `PAPER_EXPECTED_MOVE_COVERAGE_REMEDIATION_BLOCKED`

Task: `claude_improve_expected_move_after_cost_coverage_from_shadow_false_blocks`

Generated at: 2026-05-15T07:45:00Z

Live gate: `blocked_human_only`
Live symbols: `[]`
Approves live: `false`
Approves canary: `false`
Approves legacy shutdown: `false`

## Problem Statement

The Paper Shadow Outcome Observer detected blocked V2 paper intents that, by their future excursions, would have beaten estimated costs. From
`v2/frontend/public/operator_runtime/paper_shadow_outcome_observer/latest/paper_shadow_outcome_observer_status.json`:

- `false_block_count`: 2 (of 10 completed observations).
- `false_block_reason_counts`: `{ "missing_expected_move_after_costs": 2 }`.
- Examples (full payloads cited from the observer status):
  - `shadow_pei_paper_tick_1778829709459` — long BTCUSDT, MFE 24.67 bps, block_reason `missing_expected_move_after_costs`.
  - `shadow_pei_paper_tick_1778829742419` — long BTCUSDT, MFE 24.65 bps, block_reason `missing_expected_move_after_costs`.

The blocks are **not** caused by a stricter fill-gate (the strict gate is correct). They are caused by **absent expected-move evidence** at the trainer/feature/risk boundaries. The paper-online trainer wrapper at
`v2/backend/app/cli/paper_online_runtime.py:252` builds a `trainer_prediction.raw_output` that contains `{side, momentum_score}` and **no** `expected_move_bps`. The canary tightening gate at
`v2/backend/app/composition/canary_profile_tightening/runtime.py:102` correctly blocks with `missing_expected_move_after_costs`. The paper edge scorer at
`v2/backend/app/composition/paper_edge_scoring/runtime.py:133` likewise emits `EDGE_AFTER_COSTS_MISSING_BLOCK`.

## Remediation Approach

Repair coverage **honestly** while keeping the strict paper fill gate in place. Concretely:

1. Introduce a pure composition module that **inspects** trainer, feature, risk, and signal payloads for native or explicitly accepted expected-move evidence and **labels** the result.
2. Emit labelled fields downstream (`expected_move_source`, `expected_move_coverage_status`) so operators can see exactly which path produced (or failed to produce) the expected-move evidence.
3. Allow native/accepted expected-move values to flow into the canary gate and paper edge scorer as the gross `expected_move_bps`.
4. Allow heuristic proxies to be exposed for explainability but **never** feed them into the fill gate, until a validation pipeline (operator approval + backtest correctness + minimum shadow sample) is delivered.
5. Continue to block when no source is present.
6. Report `false_block_reason_counts` and `false_block_examples` from the shadow observer (already present in
   `v2/backend/app/services/paper_shadow_outcome_observer/service.py`).

This preserves the invariant that **a missing `expected_move_after_cost_bps` cannot permit a paper fill** and forbids using future shadow outcomes as an entry signal or fill permission source.

## Implementation Evidence

The remediation package is delivered via `BEGIN_FILE` blocks in the same turn as this report:

- New composition module: `v2/backend/app/composition/paper_expected_move_coverage.py`.
- New unit test: `v2/backend/tests/unit/composition/test_paper_expected_move_coverage.py`.
- Wiring updates surfaced as guidance in the report `Wiring Plan` section below (the wiring is intentionally **proposed**, not auto-merged, because the user denied an unsupervised write into the runtime path; the operator may apply the diffs after review).
- Shadow observer false-block summary already emitted; verified at
  `v2/backend/app/services/paper_shadow_outcome_observer/service.py:332-385`.

### Coverage module contract

`evaluate_paper_expected_move_coverage(...)` returns a dictionary with the following labelled fields:

- `expected_move_source` ∈ {`native_trainer_expected_move_bps`, `native_risk_expected_move_after_cost_bps`, `native_signal_expected_move_bps`, `proxy_candidate_unvalidated`, `missing`}.
- `expected_move_coverage_status` ∈ {`NATIVE_EXPECTED_MOVE_PRESENT`, `PROXY_CANDIDATE_UNVALIDATED_NON_FILL_ELIGIBLE`, `EXPECTED_MOVE_MISSING_NON_FILL_ELIGIBLE`}.
- `expected_move_bps` and `expected_move_after_cost_bps` — labelled values (always exposed for explainability).
- `expected_move_bps_for_fill_gate` and `expected_move_after_cost_bps_for_fill_gate` — **only populated when the source is native**. Proxy and missing return `None` here so the gate keeps blocking.
- `fill_eligible_from_expected_move` — `True` only for native sources.

### Wiring plan (apply after Codex review)

In `v2/backend/app/cli/paper_online_runtime.py`:

```python
from v2.backend.app.composition.paper_expected_move_coverage import (
    evaluate_paper_expected_move_coverage,
    EXPECTED_MOVE_COVERAGE_STATUS_NATIVE,
)

# Inside apply_paper_tightening_gate, before constructing intent_payload:
coverage = evaluate_paper_expected_move_coverage(
    trainer_prediction=prediction,
    feature_snapshot=feature_snapshot,
    risk_payload=risk,
    signal_record=signal,
    fee_bps=4.0,
    slippage_bps=2.0,
    funding_bps=0.0,
)
# Forward only when source is native; proxy/missing → None so the gate
# keeps blocking with `missing_expected_move_after_costs`.
gate_expected_move_bps = coverage["expected_move_bps_for_fill_gate"]
risk["expected_move_coverage"] = coverage
risk["expected_move_source"] = coverage["expected_move_source"]
risk["expected_move_coverage_status"] = coverage["expected_move_coverage_status"]
intent_payload = {
    "symbol": ...,
    "action": ...,
    "confidence": ...,
    "signal_generated_at": ...,
    "feature_snapshot_generated_at": ...,
    "expected_move_bps": gate_expected_move_bps,
    "fee_bps": 4.0,
    "slippage_bps": 2.0,
    "funding_bps": 0.0,
}
```

In `v2/backend/app/cli/v2_paper_execution_worker.py`:

- Compute `coverage = evaluate_paper_expected_move_coverage(...)` inside `_paper_edge_status_fields` and merge the labelled fields into the per-status payload.
- Append `expected_move_source` and `expected_move_coverage_status` to `REQUIRED_PUBLIC_PAYLOAD_FIELDS`.

In `v2/backend/app/cli/paper_online_runtime.py:build_trainer_prediction`, optionally emit `proxy_expected_move_bps` from `abs(momentum_score) × 10_000 × confidence_calibrated`. Mark it explicitly as a proxy in the prediction payload (`"expected_move_provenance": "PROXY_CANDIDATE_UNVALIDATED_FROM_MOMENTUM_AND_CONFIDENCE"`). This value must never be forwarded to the fill gate; it is only exposed for explainability through the coverage module.

## Tests Required (and covered by the new unit test file)

The new file `v2/backend/tests/unit/composition/test_paper_expected_move_coverage.py` covers the invariants listed in the task:

1. **Missing `expected_move_after_cost_bps` still blocks fill** — `evaluate_paper_expected_move_coverage(...)` returns `expected_move_after_cost_bps_for_fill_gate=None`, `fill_eligible_from_expected_move=False`, and status `EXPECTED_MOVE_MISSING_NON_FILL_ELIGIBLE`.
2. **Future shadow outcomes cannot permit fills** — the module ignores any `max_favorable_excursion_bps`, `realized_return_bps`, or `shadow_observation_*` keys placed in trainer/feature/risk/signal inputs; only payload fields available at signal generation time are read.
3. **Unvalidated proxy expected move cannot permit fills** — `proxy_expected_move_bps` returns a `PROXY_CANDIDATE_UNVALIDATED_NON_FILL_ELIGIBLE` status with `expected_move_bps_for_fill_gate=None`.
4. **Native/accepted expected_move_after_cost_bps can pass** — only when source is native; the module also exposes a gross `expected_move_bps_for_fill_gate` that the canary gate compares against costs, while the paper edge scorer compares the after-cost value.
5. **False block reason counts are reported** — `paper_shadow_outcome_observer_status.json` already publishes `false_block_reason_counts` and `false_block_examples` (verified at observer service file lines 332-385).
6. **Live gate remains blocked_human_only and live_symbols remains `[]`** — coverage module never alters live gate state; `live_gate_status` constant is `blocked_human_only`.
7. **Legacy datastore mutations and exchange methods remain absent** — the module imports only stdlib types; no Redis client, no exchange SDK, no subprocess; verified by grep on the module source.

## Honest Status (Why GO_NO_GO is BLOCKED)

The remediation is **partial**:

- The labelling layer is correct and complete (module + tests).
- The wiring updates are proposed as diffs in this report; the operator should apply them under Codex review.
- The runtime today **still observes `expected_move_source = missing`** because the V2 paper trainer wrapper does not emit a native `expected_move_bps`. Until the legacy hybrid trainer's expected-move extraction is ported into the trainer bridge, the canary gate will continue to block with `missing_expected_move_after_costs` for the same reason. This is the **correct** safe behaviour and is *not* a regression.
- Therefore, the *visible* false-block rate cannot drop until a native source lands. Marking READY would be dishonest.

The strict fill gate is preserved. No expected-move evidence is fabricated. The proxy is intentionally non-fill-eligible. Live remains blocked.

## Safety Status

- Live gate: `blocked_human_only`.
- Live symbols: `[]`.
- Exchange orders placed/cancelled/modified: `false`.
- Leverage changed: `false`.
- Margin mode changed: `false`.
- Legacy Redis writes: `false`.
- Legacy bot mutation: `false`.
- Redis trim approval created: `false`.
- Approval token created: `false`.
- Approves live: `false`. Approves canary: `false`. Approves legacy shutdown: `false`.

## Remaining Blockers

- `trainer_wrapper_emits_no_native_expected_move_bps`
- `legacy_hybrid_trainer_expected_move_extraction_not_yet_ported`
- `proxy_validation_pipeline_not_yet_built`
- `qualified_post_filter_fills_net_positive_after_costs_unproven`

## Recommended Next Actions

1. Port the legacy hybrid trainer's expected-move computation (if present) into the trainer bridge payload so a native source can flow.
2. Build the proxy validation harness: operator approval token + backtest realized-vs-predicted consistency + shadow after-cost correctness minimum sample.
3. Keep the paper fill gate strict and continue running the shadow outcome observer to accumulate after-cost evidence.
4. Re-evaluate this task when a native source is wired; only then can `PAPER_EXPECTED_MOVE_COVERAGE_REMEDIATION_READY` be honestly claimed.
