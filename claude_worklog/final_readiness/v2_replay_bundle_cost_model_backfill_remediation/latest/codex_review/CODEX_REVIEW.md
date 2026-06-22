# Codex Review: V2 Replay Bundle Cost-Model Backfill Remediation

GO/NO-GO: `V2_REPLAY_BUNDLE_COST_MODEL_BACKFILL_REMEDIATION_CODEX_PASS`

READY was reviewed as persisted replay-bundle cost-model backfill only. This review does not approve edge, canary, live trading, legacy shutdown, Redis trimming, or symbol adoption.

## Reviewed Scope

- `claude_worklog/final_readiness/v2_replay_bundle_cost_model_backfill_remediation/latest/V2_REPLAY_BUNDLE_COST_MODEL_BACKFILL_REMEDIATION_REPORT.md`
- `claude_worklog/final_readiness/v2_replay_bundle_cost_model_backfill_remediation/latest/replay_bundle_cost_model_backfill_status.json`
- `claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl`
- `v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl`
- `claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/state/replay_bundles.jsonl`
- current post-hoc miner worklog/public status, metrics, and dashboard payloads
- refreshed native edge-proof metrics mirrors
- `v2/backend/app/services/edge_proof/replay_miner.py`
- `v2/backend/app/cli/v2_post_hoc_replay_outcome_miner.py`
- `v2/backend/tests/integration/cli/test_v2_post_hoc_replay_outcome_miner.py`
- `v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py`

## Findings

No blocking findings.

The three persisted replay-bundle stores currently pass the cost-model marker and visible-override-field contract. The remediation status records the original backfill over six rows, with three stale rows re-tagged per store. The current stores contain nine rows because a later miner cycle added three clean rows; the current scan covered all nine rows in every store.

## Store Validation

```text
claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl
rows=9
bad_cost_model_marker_count=0
missing_visible_override_field_count=0
labels={'insufficient_evidence': 9}
window_sources={'INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE': 36}
window_filled_or_sampled_count=0

v2/frontend/public/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl
rows=9
bad_cost_model_marker_count=0
missing_visible_override_field_count=0
labels={'insufficient_evidence': 9}
window_sources={'INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE': 36}
window_filled_or_sampled_count=0

claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/state/replay_bundles.jsonl
rows=9
bad_cost_model_marker_count=0
missing_visible_override_field_count=0
labels={'insufficient_evidence': 9}
window_sources={'INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE': 36}
window_filled_or_sampled_count=0
```

The three JSONL stores are byte-identical:

```text
latest_public_cmp=0
latest_state_cmp=0
```

Every row has:

- `market_snapshot.cost_model_source` containing `OPERATOR_DECISION_REQUIRED`
- `market_snapshot.operator_decision_required=true`
- `market_snapshot.operator_override_required=true`
- `market_snapshot.default_fee_bps_visible=5.0`
- `market_snapshot.default_slippage_estimate_bps_visible=2.0`

## Preservation Checks

- Current row identities are preserved consistently across all three stores: symbol, `prediction_id`, `generated_at`, `anchor_ts`, and label align row-for-row.
- Remediation status reports `protected_field_drift=[]` for each backfilled store.
- The backfill implementation snapshots protected fields before and after mutation and writes only when validation passes.
- Protected fields include `intent_id`, `prediction_id`, `symbol`, `generated_at`, `anchor_ts`, `future_outcomes`, `label`, `outcome_after_cost`, `paper_gate_decision`, `risk_decision`, `orchestrator_decision`, `paper_intent`, and `legacy_reference_action`.
- Current labels remain `insufficient_evidence`.
- All current future outcome windows remain explicit `INSUFFICIENT_EVIDENCE_AWAITING_FUTURE_TIMELINE` with no after-cost values and no samples.

## Verified Safety

- Edge verdict remains conservative: `EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED`.
- Miner and native edge-proof payloads keep `live_gate=blocked_human_only`.
- Miner and native edge-proof payloads keep `live_symbols=[]`.
- Approval fields remain false: `approves_live=false`, `approves_canary=false`, `approves_legacy_shutdown=false`, and `approves_redis_trim=false`.
- No fabricated future outcome windows were found.
- No label changes without evidence were found.
- No old Redis write path was found in reviewed edge-proof code.
- No exchange mutation path was found in reviewed edge-proof code.
- No raw secrets were found in reviewed artifacts; scan hits were report/status safety text only.

## Code Review Notes

- `backfill_bundle_cost_model(row)` only mutates `market_snapshot`.
- `validate_bundle_row(row)` fails stale cost-model markers, missing operator override metadata, invalid labels, and fabricated values inside insufficient-evidence windows.
- `backfill_jsonl_store(path)` performs protected-field drift verification and atomic replacement.
- `backfill_all_replay_bundle_stores()` checks the worklog latest JSONL, public mirror JSONL, and miner state JSONL.
- `v2_post_hoc_replay_outcome_miner.run()` now invokes the backfill each cycle before loading bundles and emitting status payloads.

## Test Evidence

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_post_hoc_replay_outcome_miner.py \
  v2/backend/tests/integration/cli/test_v2_native_edge_proof_evaluator.py -q
```

Result:

```text
43 passed in 0.27s
```

Compile check:

```text
python -m py_compile \
  v2/backend/app/services/edge_proof/evaluator.py \
  v2/backend/app/services/edge_proof/replay_schema.py \
  v2/backend/app/services/edge_proof/replay_miner.py \
  v2/backend/app/cli/v2_post_hoc_replay_outcome_miner.py
```

Result: pass.

## Safety Scoreboard

- did_not_modify_legacy_bot
- did_not_stop_v2_runtime
- did_not_write_old_redis
- did_not_call_exchange
- did_not_enable_live
- did_not_create_approval_marker
- did_not_fabricate_future_outcome_windows
- did_not_change_replay_labels
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
