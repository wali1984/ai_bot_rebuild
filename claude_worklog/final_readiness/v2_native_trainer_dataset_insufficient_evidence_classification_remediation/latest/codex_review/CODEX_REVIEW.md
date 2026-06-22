# Codex Review: V2 Native Trainer Dataset Insufficient-Evidence Classification Remediation

GO/NO-GO: `V2_NATIVE_TRAINER_DATASET_INSUFFICIENT_EVIDENCE_CLASSIFICATION_REMEDIATION_CODEX_PASS`

This review covers the dataset quality classification remediation only. It does
not approve edge, canary, live trading, legacy shutdown, Redis trim, checkpoint
compatibility, policy-architecture parity, or production trainer readiness.

## Findings

No blocking findings remain.

## Verified

- Rows with `label=insufficient_evidence` are now classified as
  `INSUFFICIENT_EVIDENCE`.
- The remediation status reconciles headline counters:
  `label_insufficient_count=4681`,
  `classification_insufficient_count=4681`, and
  `reported_insufficient_rows=4681`.
- `LABEL_MISSING` is no longer used for explicit insufficient-evidence rows:
  `classification_label_missing_count=0` and `reported_label_missing_rows=0`.
- Dataset quality no longer hides insufficient evidence. The refreshed dataset
  quality report shows:

  ```text
  total_rows=4856
  quality_report.classifications.INSUFFICIENT_EVIDENCE=4681
  quality_report.classifications.LABEL_MISSING=0
  quality_report.insufficient_evidence_rows=4681
  quality_report.label_missing_rows=0
  label_distribution.insufficient_evidence=4681
  ```

- Direct JSONL row scan found:

  ```text
  bad_insufficient_classification=0
  trainable_insufficient_evidence_rows=0
  missing_source_lineage_rows=0
  ```

- Baseline model training excludes insufficient-evidence rows. Trainable labels
  are only `correct_no_trade` and `false_negative`; the refreshed split is
  `train_count=107`, `validation_count=18`.
- Dataset source lineage remains present on every scanned row.
- Dataset quality still exposes small usable sample size:
  `minimum_sample_satisfied=false` at the dataset readiness threshold of 256.
- Raw legacy Redis is not used as current truth; legacy action remains
  reference/mirror metadata only.
- Baseline model readiness remains `NOT_PRODUCTION_READY`.
- No checkpoint compatibility claim is present.
- No model/policy-architecture parity claim is present.
- Report center exposes both the dataset/model lane and this remediation lane.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Paper-fill gate was not weakened.
- No executable old-Redis write path was found in the reviewed dataset/baseline
  scope.
- No exchange mutation path was found in the reviewed dataset/baseline scope.
- No raw secret material was found in the reviewed remediation artifacts.

## Verification

```text
python -m py_compile \
  v2/backend/app/services/native_trainer/dataset_builder.py \
  v2/backend/app/services/native_trainer/baseline_model.py \
  v2/backend/app/services/native_trainer/packet.py \
  v2/backend/app/cli/v2_native_trainer_dataset_builder.py \
  v2/backend/app/cli/v2_native_trainer_dataset_insufficient_evidence_classification_remediation.py \
  v2/backend/app/services/report_center/report_registry.py
```

Result: pass.

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_native_trainer_dataset_and_baseline_model.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q
```

Result: `43 passed in 0.22s`.

```text
PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

jq empty dataset/baseline, remediation, and report-center JSON artifacts
```

Result: report-center re-index passed; JSON validation passed.
