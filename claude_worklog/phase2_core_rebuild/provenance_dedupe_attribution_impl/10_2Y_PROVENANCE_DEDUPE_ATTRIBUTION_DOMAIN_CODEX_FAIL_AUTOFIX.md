# Phase 2Y Provenance Dedupe Attribution Domain Codex Fail Autofix

## Finding

Codex review `08_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_REVIEW.md`
failed because the duplicate-signal regression fixture did not match the
Phase 2V source-of-truth row.

Phase 2V evidence row:

- `scenario_id`: `duplicate_signal_blocked`
- `model_version`: `hybrid_trainer_v2026_05`
- `checkpoint_id`: `ckpt_duplicate_signal_blocked_2026_05`
- `confidence_raw`: `0.77`
- `confidence_calibrated`: `0.74`
- `trainer_worker_liveness`: `alive`

Fixture before remediation:

- `confidence_raw`: `0.71`
- `confidence_calibrated`: `0.68`

## Remediation

Updated:

- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/_fixtures.py`

The fixture now uses:

- `confidence_raw`: `0.77`
- `confidence_calibrated`: `0.74`

## Validation

Command:

```bash
PYTHONPATH=. ./.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/domain/provenance_dedupe_attribution \
  v2/backend/tests/unit/services/provenance_dedupe_attribution \
  v2/backend/tests/unit/composition/provenance_dedupe_attribution
```

Result:

```text
43 passed
```

No live, Redis, legacy, exchange, leverage, margin, deployment, or live-trading
paths were changed.

2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_AUTOFIX_READY
