# V2 Native Edge-Proof — Spec + Replay Evaluator Ready Report

GO/NO-GO: `V2_NATIVE_EDGE_PROOF_SPEC_AND_REPLAY_EVALUATOR_READY`

**READY means the evaluator exists. READY does not mean edge is proven.**

## What this packet provides

An objective, conservative evaluation system that ingests V2
paper/shadow inputs, assembles replay bundles, and emits the
canonical edge-proof metric summary. The evaluator never claims edge
unless every operator-set numeric threshold is satisfied. The
default verdict is
`EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED` because the
operator caps are intentionally `OPERATOR_DECISION_REQUIRED` at
ship time.

## Files

- `v2/backend/app/services/edge_proof/replay_schema.py`
  — `ReplayBundle`, `OutcomeWindow`, `ReplayLabel` enum, default
  thresholds, canonical input keys, `emit_canonical_schema()`.
- `v2/backend/app/services/edge_proof/evaluator.py`
  — pure functions `evaluate(bundles, thresholds, outcome_window)` →
  `MetricSummary` covering every required metric. Bootstrap CI on
  after-cost returns. Conservative verdict logic.
- `v2/backend/app/cli/v2_native_edge_proof_evaluator.py`
  — CLI that reads V2 paper/shadow inputs read-only from `v2:*` Redis
  keys plus the V2-vs-legacy comparator mirror, assembles one bundle
  per symbol, runs the evaluator, and writes the worklog + frontend
  payloads.
- `v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py`
  — 9 focused tests covering schema, default conservative verdict,
  threshold-fail behavior, label classification, pre-cascade recall +
  precision, V2-vs-legacy match rate, checkpoint/strict-gate hold
  counts, full-pass-only-when-all-thresholds-pass, default-threshold
  invariants. All 9 pass.

## Replay bundle schema

Every bundle freezes:

- `feature_snapshot_id`, `prediction_id`, `symbol`, `timeframe`,
  `generated_at`, `features_hash`.
- `market_snapshot` (price, funding, OI, liquidations latest +
  aggregate, fee_bps, slippage_estimate_bps).
- `altdata_snapshot` (alt-data symbol score if present;
  paper/shadow only).
- `risk_decision` (per-symbol row from `v2:risk:decisions`).
- `trainer_output` (V2 prediction + expected move + calibrated
  confidence + paper-fill-gate block reasons).
- `paper_gate_decision` (paper_fill_allowed, paper_fill_gate
  block_reasons, latency_seconds).
- `orchestrator_decision` (V2 orchestrator).
- `paper_intent` (matching symbol's paper intent).
- `legacy_reference_action` (V2-vs-legacy comparator public mirror
  ONLY — never raw legacy Redis as current truth).
- `future_outcomes` over 4 windows: 1m, 5m, 15m, 1h. Each window
  carries `return_bps`, `after_cost_return_bps`, `drawdown_bps`,
  `stop_hit`, `samples`. The primary window for the evaluator is 5m.
- `outcome_after_cost`, `label` (one of `correct_trade`,
  `correct_no_trade`, `false_positive`, `false_negative`,
  `false_block`, `insufficient_evidence`).

Schema artifact: `replay_bundle_schema.json` (worklog + public
mirror).

## Inputs the evaluator reads

Canonical V2 Redis keys (read-only via the `_safe_redis_read` helper
which refuses any non-`v2:*` key):

- `v2:prediction:{symbol}:{timeframe}`
- `v2:features:latest:{symbol}:{timeframe}`
- `v2:market:prices:{symbol}`
- `v2:market:liquidations:heartbeat`
- `v2:market:liquidations:latest:{symbol}` (event-dependent)
- `v2:market:liquidations:aggregate:{symbol}` (event-dependent)
- `v2:altdata:symbol_score:{symbol}` (lane-exists-payload-absent today)
- `v2:risk:decisions`
- `v2:paper:intents`
- `v2:paper:intents_held_by_paper_fill_gate`
- `v2:paper:ledger`
- `v2:paper:position_history:{symbol}`
- `v2:paper:position_price_track:{symbol}`
- `v2:orchestrator:decisions`

Reference-only mirrors (never current-truth Redis):

- `v2/frontend/public/v2_legacy_v2_production_comparator/latest/operator_dashboard_payload.json`
  — picked up per-symbol via `_legacy_reference_action_for`.
- Legacy log observer summary mirrors are not read at this stage;
  they remain available as a future optional input for the post-hoc
  replay miner.

The evaluator does **not** read old (legacy) Redis as current truth.

## Metrics emitted

| Metric | Status |
|---|---|
| `after_cost_pnl_delta` | computed |
| `expected_move_after_cost_bps` | computed |
| `false_positive_rate` | computed (None when no positive predictions) |
| `false_negative_rate` | computed (None when no negative predictions) |
| `downside_pre_cascade_recall` | computed (None when no pre-cascade events) |
| `downside_pre_cascade_precision` | computed (None when no warnings) |
| `average_latency_to_signal_seconds` | computed |
| `gate_block_reason_distribution` | computed |
| `v2_vs_legacy_action_match_rate` | computed (informational only) |
| `v2_hold_due_checkpoint_count` | computed |
| `v2_hold_due_strict_gate_count` | computed |
| `no_trade_correct_count` | computed |
| `false_block_count` | computed |
| `fee_drag_bps` | computed |
| `slippage_estimate_bps` | computed |
| `sample_count` | computed |
| `minimum_sample_satisfied` | computed against operator `min_sample_count` |
| `after_cost_ci_lower_bps`, `after_cost_ci_upper_bps` | bootstrap CI |

## Conservative verdict logic

| Verdict | Triggered when |
|---|---|
| `EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED` | any threshold still `OPERATOR_DECISION_REQUIRED` (default state) |
| `EDGE_NOT_PROVEN_INSUFFICIENT_SAMPLES` | `min_sample_count` numeric but sample count below it |
| `EDGE_NOT_PROVEN` | every threshold numeric but at least one check fails |
| `EDGE_PROVISIONAL_PAPER_PASS` | every operator-set numeric threshold passes in paper/shadow — explicitly NOT a live or canary approval |

`min_v2_vs_legacy_action_match_rate` is treated as **informational
only** per the model-path decision packet.

## Default thresholds (preliminary, analysis only)

- `min_sample_count = OPERATOR_DECISION_REQUIRED`
- `min_after_cost_expectancy_bps = OPERATOR_DECISION_REQUIRED`
- `min_after_cost_lower_ci_bps = OPERATOR_DECISION_REQUIRED`
- `max_drawdown_bps_rolling = OPERATOR_DECISION_REQUIRED`
- `min_downside_pre_cascade_recall = OPERATOR_DECISION_REQUIRED`
- `max_false_positive_rate = OPERATOR_DECISION_REQUIRED`
- `max_false_negative_rate = OPERATOR_DECISION_REQUIRED`
- `min_v2_vs_legacy_action_match_rate = OPERATOR_DECISION_REQUIRED_INFORMATIONAL_ONLY`
- `preliminary_only_for_analysis = true`
- `no_live_approval_implied = true`

## Smoke-test verdict on current runtime

The evaluator assembled 3 bundles (BTCUSDT/ETHUSDT/SOLUSDT). Verdict:
`EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`. This is the correct
conservative state. No metric currently claims edge; future outcome
windows are `INSUFFICIENT_EVIDENCE` because the realtime path
intentionally does not fabricate forward returns. A post-hoc replay
miner (separate task) will fill the future-outcome windows from the
paper ledger and position-history tracker once the operator approves
the edge-proof gate.

## Test evidence

```
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py -q
```

Result: **9 / 9 passed**.

## Outputs

| Path | Purpose |
|---|---|
| `claude_worklog/final_readiness/v2_native_edge_proof/latest/GO_NO_GO.md` | `V2_NATIVE_EDGE_PROOF_SPEC_AND_REPLAY_EVALUATOR_READY` |
| `claude_worklog/final_readiness/v2_native_edge_proof/latest/native_edge_proof_status.json` | Evaluator metric summary + thresholds |
| `claude_worklog/final_readiness/v2_native_edge_proof/latest/replay_bundle_schema.json` | Canonical replay bundle schema |
| `claude_worklog/final_readiness/v2_native_edge_proof/latest/edge_metrics_summary.json` | Metric view for storage |
| `v2/frontend/public/v2_native_edge_proof/latest/operator_dashboard_payload.json` | Frontend mirror |
| `v2/frontend/public/v2_native_edge_proof/latest/edge_metrics_summary.json` | Frontend mirror |
| `v2/frontend/public/v2_native_edge_proof/latest/replay_bundle_schema.json` | Frontend mirror |
| `v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py` | 9 / 9 passing tests |

## Required visible text (in operator dashboard payload)

- "Live trading is blocked."
- "Legacy shutdown is blocked."
- "Candidate symbols are not adopted automatically."
- "Recovery requires proof of edge before scaling."
- "No fake readiness."
- "READY means evaluator exists. READY does not mean edge proven."

## Safety scoreboard

- did_not_modify_legacy_bot
- did_not_stop_v2_runtime
- did_not_stop_continuous_remediation
- did_not_stop_codex_governors
- did_not_stop_legacy_log_observer
- did_not_stop_v2_vs_legacy_comparator
- did_not_stop_liquidation_wss_daemon
- did_not_stop_position_history_persistent_tracker
- did_not_write_old_redis
- did_not_call_exchange
- did_not_create_approval_marker
- did_not_create_shutdown_acceptance_file
- did_not_enable_live
- did_not_expose_raw_api_keys
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false

## Next steps (operator-gated)

1. Operator sets numeric values for every threshold in
   `replay_bundle_schema.json` -> `default_thresholds`.
2. A post-hoc replay miner (separate task) fills `future_outcomes`
   from the V2 paper ledger and `v2:paper:position_history:{symbol}`
   so bundles can be classified beyond `INSUFFICIENT_EVIDENCE`.
3. The evaluator runs over the mined bundles and emits a verdict.
4. Only on `EDGE_PROVISIONAL_PAPER_PASS`, with a separate Codex
   review, can the operator consider the next gate
   (`operator_caps_set` → `canary_approval` → `live_ramp_approval`).
5. No live, canary, shutdown, Symbol Universe adoption, or external
   feed adoption is implied by any verdict of this evaluator.
