# Profiled Outcome Model-Binding Checkpoint

Timestamp: `2026-07-23T14:45:57Z`
Branch: `codex/strategy-receipt-promotion-20260723`
Implementation commit: `af0741f0fec7ef90f6a4df264194e0f584ed38d5`
Family status: implementation complete, committed, pushed, and regression-clean

## Outcome

Every finalized directional calibration row is now durably and directly bound
to the exact checkpoint and unchanged model weights that emitted its raw
profitability probability. The outcome artifact carries a 15-field
`model_binding` plus its canonical SHA-256. The calibration row and the sealed
public result both carry the checkpoint ID, checkpoint generation, model
parameter fingerprint, and model-binding digest.

The binding is freshly rederived from the authenticated raw-inference V2
payload whenever the outcome is created or reopened. It is cross-checked
against the hypothesis artifact, raw-inference binding, confidence-head schema,
ordered directional heads, profitability-label semantics, candidate contract,
candidate authorization receipt, code release, checkpoint weight digest, and
checkpoint-before-decision clock order. A calibration consumer no longer needs
private `_committed` or raw-CAS access to identify the exact model.

This is a compatibility extension to an unwired research ledger. No deployed
outcome artifacts existed, no runtime imports consume the ledger, and no
service or publisher state was changed. All downstream authority flags remain
false.

## Evidence counts

- Production files changed: 1
- Test files changed: 1
- Public ledger routes changed: 0 / 4
- HTTP/API endpoints compared or changed: 0 / 0
- Screenshots captured: 0
- Application builds applicable: 0
- Python byte-compile checks passed: 2 / 2 files
- Ruff checks passed: 2 / 2 files
- Strict mypy checks passed: 1 / 1 production module
- Commit whitespace checks passed: 1 / 1 commit
- Focused affected cases passed: 10 / 10
- Final family regression cases passed: 46 / 46
- Exact contract fields checked: 129 / 129
- Model-binding fields checked: 15 / 15
- Calibration-row fields checked: 17 / 17
- Unique sealed public-result fields checked: 27 / 27
- Direct model references added to calibration/public result: 4 / 4
- Fresh-process model-binding reopen cases passed: 1 / 1
- Model/calibration tamper cases added: 2
- False downstream-authority fields retained: 18 / 18
- Source/runtime files in parallel downstream review: 19
- Test files in parallel downstream review: 9
- Primary downstream call boundaries traced: 22
- Downstream contract field slots reviewed: 95
- PIT/finality clocks reviewed downstream: 11
- Reviewer tests/builds executed: 0 / 0 (read-only review)
- Services restarted or activated: 0
- Redis reads/writes: 0 / 0
- Exchange/PAPER/live/order paths changed: 0
- Defects fixed in this family: 1 / 1
- Defects remaining in this family: 0
- Concrete downstream boundary defects remaining: 5
- Implementation diff: 241 insertions, 2 deletions

## Exact 15-field model binding

1. `schema_version`
2. `checkpoint_id`
3. `checkpoint_generation`
4. `checkpoint_generated_at`
5. `checkpoint_weight_sha256`
6. `model_id`
7. `model_parameter_fingerprint`
8. `candidate_contract_sha256`
9. `candidate_authorization_receipt_sha256`
10. `candidate_code_release_sha`
11. `confidence_head_schema_version`
12. `confidence_head_actions`
13. `profitability_label_semantics`
14. `raw_inference_binding_sha256`
15. `hypothesis_artifact_sha256`

## Four direct consumer bindings

1. `checkpoint_id`
2. `checkpoint_generation`
3. `model_parameter_fingerprint`
4. `model_binding_sha256`

All four appear in the calibration row and in the factory-sealed durable result.
The calibration row ID also includes `model_binding_sha256`.

## Validation commands

```text
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m ruff check v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m mypy --strict v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py::test_matures_exact_selected_long_outcome_and_remains_non_authoritative
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py -k 'source_free or factory_result_seal or fresh_process'
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest --collect-only -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py
git diff --check
git diff --cached --check
git show --check --oneline af0741f0fec7ef90f6a4df264194e0f584ed38d5
```

Focused affected result: `10 passed` (`1` exact happy-path case plus `9`
fresh-process/seal/tamper cases).

Final family result: `46 passed in 986.13s`.

## Five concrete downstream defects

1. No durable finalized-outcome calibration-admission consumer exists.
2. Ordinary optimizer serving promotion correctly requires changed weights; a
   separate calibration-only unchanged-weight checkpoint/promoter is absent.
3. Publisher, ordinary-paper, lineage, and risk boundaries do not yet require
   calibration fingerprint equality with the served checkpoint/model.
4. No finalized-outcome admission or calibration-only promotion CLI/runtime
   route exists.
5. Evidence settings that affect calibration promotion (`validation_fraction`,
   ECE binning, fixed temperature search bounds/grid, degradation constants)
   and the fixed replay-snapshot TTL still require evidence-adaptive treatment.

## Next bounded family

Implement a sealed, durable finalized-calibration admission ledger that:

- groups rows by exact `model_parameter_fingerprint`;
- assigns chronological purged-train and untouched forward-validation rows;
- uses no configured sample-count or market threshold;
- prevents duplicate/sample reuse with an append-only cursor;
- proves calibration non-regression with uncertainty;
- grants calibration/checkpoint-write authority only, never PAPER/live/order
  authority; and
- preserves the exact unchanged weight fingerprint for a later dedicated
  calibration-only checkpoint promoter.

The ordinary optimizer promotion route must remain unchanged. Publisher
activation remains blocked on the five downstream defects above; this
checkpoint does not claim the trainer publisher is serving predictions.

## Files in the implementation commit

- `v2/backend/app/services/native_trainer/profiled_research_finalized_outcome_ledger_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_research_finalized_outcome_ledger_v1.py`
