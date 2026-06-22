# V2 Replay Bundle Cost-Model Backfill Remediation Report

GO/NO-GO: V2_REPLAY_BUNDLE_COST_MODEL_BACKFILL_REMEDIATION_READY

This packet resolves the persisted-bundle blockers from
V2_POST_HOC_REPLAY_OUTCOME_MINER_CODEX_FAIL re-review:

1. Persisted replay bundle artifacts still contained stale cost-model
   rows whose market_snapshot.cost_model_source was the legacy literal
   DEFAULT_PAPER_COST_MODEL_PENDING_OPERATOR_OVERRIDE and lacked the
   OPERATOR_DECISION_REQUIRED literal.
2. Those rows did not carry the operator_decision_required,
   operator_override_required, default_fee_bps_visible, or
   default_slippage_estimate_bps_visible fields.

The replay miner timer remains NOT installed and NOT enabled per the
constraint.

## What changed

### Backfill function in v2/backend/app/services/edge_proof/replay_miner.py

- backfill_bundle_cost_model(row) returns (re-tagged row, changed_flag).
  Only market_snapshot is mutated. Protected fields (intent_id,
  prediction_id, symbol, generated_at, anchor_ts, future_outcomes,
  label, outcome_after_cost, paper_gate_decision, risk_decision,
  orchestrator_decision, paper_intent, legacy_reference_action) are
  left untouched.
- validate_bundle_row(row) returns a list of validation error tokens.
  Empty list means the row passes. Checks include:
  - cost_model_source contains OPERATOR_DECISION_REQUIRED literal
  - operator_decision_required is True
  - operator_override_required is True
  - default_fee_bps_visible is present
  - default_slippage_estimate_bps_visible is present
  - no INSUFFICIENT outcome window carries a fabricated after-cost
  - label is one of the canonical ReplayLabel values
- backfill_jsonl_store(path) atomically re-tags every stale row in
  one JSONL file with protected-field-drift verification and
  per-row validation; fails closed if anything looks off.
- backfill_all_replay_bundle_stores() applies the above to the three
  persisted stores (worklog, public mirror, miner state).

### CLI integration in v2/backend/app/cli/v2_post_hoc_replay_outcome_miner.py

- run() now calls backfill_all_replay_bundle_stores() every cycle so
  no future regression can leave a stale row persisted.
- The cost-model backfill status is included in the emitted
  post_hoc_replay_outcome_status.json payload.

## Backfill execution evidence

Three stores, six rows each, three stale rows per store:

| Store | Rows | Re-tagged | Validation |
|---|---:|---:|---|
| claude_worklog/.../latest/replay_outcome_bundles.jsonl | 6 | 3 | PASS |
| v2/frontend/public/.../latest/replay_outcome_bundles.jsonl | 6 | 3 | PASS |
| claude_worklog/.../state/replay_bundles.jsonl | 6 | 3 | PASS |

After backfill, every persisted row carries:

- market_snapshot.cost_model_source contains OPERATOR_DECISION_REQUIRED.
- market_snapshot.operator_decision_required = true
- market_snapshot.operator_override_required = true
- market_snapshot.default_fee_bps_visible = 5.0
- market_snapshot.default_slippage_estimate_bps_visible = 2.0

Zero protected-field drift. The intent_id, symbol, timestamps, market
prices, future_outcomes, labels, paper gate decisions, risk decisions,
and orchestrator decisions of every row are byte-identical to the
pre-backfill row.

## Post-backfill artifact scan

| Check | Result |
|---|---|
| Rows still on legacy marker | 0 |
| Rows missing OPERATOR_DECISION_REQUIRED literal | 0 |
| Rows missing any of the four visible override fields | 0 |
| Approval-truthy literal hits across all artifacts | 0 |
| Raw-secret hits (AKIA / ASIA / PEM headers / .local_secrets/) | 0 |
| Invalid JSONL rows | 0 |

## Regression tests

Added in v2/backend/tests/integration/cli/test_v2_post_hoc_replay_outcome_miner.py:

- test_backfill_stale_row_retags_cost_model_and_adds_visible_fields
- test_backfill_clean_row_is_idempotent_and_unchanged
- test_validate_bundle_row_passes_on_clean_row
- test_validate_bundle_row_fails_on_stale_row
- test_validate_bundle_row_flags_fabricated_outcome_in_insufficient_window
- test_backfill_jsonl_store_retags_stale_rows_and_preserves_others
- test_persisted_replay_bundle_stores_pass_validation_after_backfill
- test_backfill_never_modifies_future_outcomes_or_labels
- test_backfill_artifacts_emit_no_live_canary_shutdown_approvals

Results:

- Focused evaluator tests: 34 of 34 passed.
- Focused miner tests (including the 9 new backfill regressions): 26 of 26 passed.
- Combined regression sweep across evaluator + miner + website + report center: 83 of 83 passed.

## Validation scans

| Scan | Result |
|---|---|
| py_compile across edge-proof code | PASS |
| Old-Redis-write scan across edge-proof code | PASS, 0 hits |
| Exchange-mutation scan across edge-proof code | PASS, 0 hits |
| Approval-token truthy scan across miner artifacts + dashboards | PASS, 0 hits |
| Raw-secret scan across miner artifacts + dashboards | PASS, 0 hits |
| JSONL validity for every row across the three persisted stores | PASS |

## What this cycle did NOT do

- Did not install or enable the replay miner timer.
- Did not modify /home/wali/Desktop/AI BOT.
- Did not stop legacy or V2 runtime.
- Did not stop continuous remediation, Codex governors, the report-center
  indexer, the legacy log observer, the V2-vs-legacy comparator, the
  liquidation WSS daemon, or the position-history persistent tracker.
- Did not write any old Redis key.
- Did not call the exchange.
- Did not create any approval marker or shutdown-acceptance file.
- Did not enable live or canary.
- Did not adopt any Symbol Universe candidate.
- Did not adopt any external feed.
- Did not expose any raw API key.
- Did not fabricate any future-outcome window value.
- Did not change any replay label.

## Safety scoreboard

- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
- did_not_install_or_enable_replay_miner_timer = true
- protected_replay_bundle_fields_unchanged = true

## Operator next step

The persisted bundle stores are now fully aligned with the
remediated cost-model marker contract. The miner runs the backfill
every cycle so any future regression cannot persist. The miner timer
remains paper-only and disabled until a separate operator decision
enables it.
