# V2 Native Trainer Dataset — Insufficient-Evidence Classification Remediation

GO/NO-GO: V2_NATIVE_TRAINER_DATASET_INSUFFICIENT_EVIDENCE_CLASSIFICATION_REMEDIATION_READY

live_gate=blocked_human_only. live_symbols=[]. approves_live=false. trainer_native_readiness_claimed=false. checkpoint_compatibility_claimed=false. model_parity_claimed=false. production_readiness_claimed=false. edge_proven=false.

## Codex blocker addressed
Codex previously failed `V2_NATIVE_TRAINER_DATASET_AND_BASELINE_MODEL_READY` with `INSUFFICIENT_EVIDENCE_ROWS_COLLAPSED_INTO_LABEL_MISSING`.
Rows whose label is `insufficient_evidence` are now classified as `INSUFFICIENT_EVIDENCE` and counted separately from `LABEL_MISSING`.

## Verification counts (post-remediation)
- label_distribution.insufficient_evidence: 4681
- classifications.INSUFFICIENT_EVIDENCE: 4681
- classifications.LABEL_MISSING: 0
- insufficient_evidence_rows: 4681
- label_missing_rows: 0

## Checks
- label_distribution_matches_classification_insufficient_evidence: True
- headline_counter_matches_classification_insufficient_evidence: True
- label_missing_does_not_count_insufficient_evidence: True
- no_insufficient_evidence_rows_hidden_under_label_missing: True

all_checks_passed: True

## Code changes
- `v2/backend/app/services/native_trainer/dataset_builder.py::_classify_row` — explicit `insufficient_evidence` label now maps to `ROW_INSUFFICIENT_EVIDENCE`.
- `v2/backend/app/services/native_trainer/dataset_builder.py::build_rows_from_replay_bundles` — same fix for replay-bundle-derived rows.
- Regression tests added in `v2/backend/tests/integration/cli/test_v2_native_trainer_dataset_and_baseline_model.py` covering: label classification mapping, quality-counter separation, baseline evaluator excluding insufficient-evidence rows, and replay-bundle row classification.

## What this packet did NOT do
- Did not claim V2_NATIVE_TRAINER_READY or V2_NATIVE_TRAINER_ACTIVE.
- Did not claim checkpoint compatibility.
- Did not claim policy-architecture parity.
- Did not claim production readiness.
- Did not claim edge proven.
- Did not weaken the paper-fill gate.
- Did not write any non-v2:* Redis key.
- Did not call the exchange.
- Did not enable production trading or canary.
- Did not approve legacy shutdown or Redis trim.
- Did not modify legacy or V2 runtime.
- Did not load or log any API credential value.
- Did not auto-rewrite git history.
- Did not create an approval token.
