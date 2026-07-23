# Adaptive Confidence Calibration Checkpoint — 2026-07-23 15:48:04 UTC

## Resume coordinates

- Authoritative worktree: `/tmp/codex-strategy-receipt-promotion`
- Branch: `codex/strategy-receipt-promotion-20260723`
- Implementation commit: `a18c2a4c50e390eba226c605fcdabe4ac6732a5d`
- Parent checkpoint commit: `3920ba0a5d9dae0a8b0774267a424eb6db31e21f`
- Family status: implementation and directly impacted regression complete
- Live/PAPER services changed or restarted: `0`
- Exchange/order/risk/allocator authority changed: `0`

## Evidence counts

- Source modules changed: `7`
- Test modules changed: `6`
- Calibration/inference/admission/checkpoint callable boundaries reconciled: `17`
- Calibration-state contract fields checked: `25`
- Hashed uncertainty-evidence fields checked: `16`
- Admission top-level fields checked: `11`
- V2 evidence-policy fields checked: `15`
- Directly impacted pytest suites: `6`
- Tests passed: `131/131`
- Source modules byte-compiled: `7/7`
- Ruff-target files passed: `10/10`
- `git diff --check`: passed
- Screenshots captured: `0` (backend-only family)
- HTTP endpoints compared: `0` (no HTTP contract changed)
- Build failures: `0`
- Remaining defect groups in the calibration-to-publisher path: `5`

## Completed contract

1. Active calibration fitting no longer uses the historical `T=[0.25, 6]`
   bounds, 41-point grid, or 40 fixed optimizer iterations. It solves the
   convex inverse-temperature score equation, expands its bracket from the
   observed data, and bisects to adjacent IEEE-754 floats.
2. The honest `logit_scale=0` boundary is first-class. It is never encoded as
   a fake large finite temperature. Inference, PPO validation, admission,
   checkpoint serialization, and checkpoint restore all consume the
   authoritative nonnegative logit scale.
3. Equal-width 10-bin ECE was removed from active fitting and validation. The
   active estimator groups exact predicted confidences and seals the supremum
   of the cumulative signed reliability residual.
4. Non-regression admission now requires the full observed metric and every
   delete-one recomputation to be non-regressing. One-standard-error values
   remain descriptive telemetry only and are not admission thresholds.
5. Confidence data-quality downrating now uses observed missing/stale fractions
   directly. The fixed `0.25` floors, `0.75/0.5` slopes, and `0.015/0.01`
   absolute-count fallbacks were removed. Missing total-feature lineage fails
   the separate quality-admission score closed without corrupting the fitted
   probability.
6. Ordinary fit non-identifiability is a waiting state, not an integrity
   failure. Perfect separation and all-0.5 raw probabilities cannot mint a
   finite interior fit.
7. New admissions use the V2 adaptive artifact/classification and V2 evidence
   policy. Immutable V1 artifacts retain a frozen, version-dispatched verifier;
   historical fixed constants exist only inside that verifier and cannot mint
   active V2 evidence.
8. The shared probability-scaling, calibration-error, and paired-evidence
   producers now feed PPO and durable admission, preventing producer/verifier
   drift.

## Regression command

```bash
PYTHONPATH="$(pwd)" /home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m pytest -q \
  v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py \
  v2/backend/tests/unit/services/native_trainer/test_profiled_research_calibration_admission_v1.py \
  v2/backend/tests/unit/services/native_trainer/test_training_state.py \
  v2/backend/tests/unit/services/native_trainer/test_checkpoint_lifecycle.py \
  v2/backend/tests/unit/services/native_trainer/test_confidence_proportional_calibration.py \
  v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py
```

Result: `131 passed, 1 non-failing third-party warning in 28.52s`.

Additional verification:

```bash
/home/wali/Desktop/AI\ BOT\ REBUILD/.venv/bin/python -m py_compile \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/confidence.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/model.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/training_state.py \
  v2/backend/app/services/native_trainer/hybrid_cuda_trainer/checkpoint.py \
  v2/backend/app/services/native_trainer/persistent_cuda_trainer_runtime.py \
  v2/backend/app/services/native_trainer/profiled_research_calibration_admission_v1.py
```

The ten-file scoped Ruff command and `git diff --check` both passed. Full-file
Ruff on `model.py`, `ppo_trainer.py`, and the persistent runtime was not used as
family evidence because those files retain unrelated pre-existing diagnostics;
the edited boundaries compile and are exercised by the regression suite.

## Files in the implementation commit

- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/checkpoint.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/confidence.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/model.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/ppo_trainer.py`
- `v2/backend/app/services/native_trainer/hybrid_cuda_trainer/training_state.py`
- `v2/backend/app/services/native_trainer/persistent_cuda_trainer_runtime.py`
- `v2/backend/app/services/native_trainer/profiled_research_calibration_admission_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_checkpoint_lifecycle.py`
- `v2/backend/tests/unit/services/native_trainer/test_confidence_calibration.py`
- `v2/backend/tests/unit/services/native_trainer/test_confidence_proportional_calibration.py`
- `v2/backend/tests/unit/services/native_trainer/test_hybrid_confidence_profitability_semantics.py`
- `v2/backend/tests/unit/services/native_trainer/test_profiled_research_calibration_admission_v1.py`
- `v2/backend/tests/unit/services/native_trainer/test_training_state.py`

## Remaining defects — do not call the publisher ready yet

1. Admission still selects the latest structurally identifiable validation
   suffix. It needs an immutable candidate/validation-start receipt so later
   outcomes append to one sealed forward cohort instead of reselecting it.
2. Ordinary trainer partitioning still has a configured `validation_fraction`
   default. This must be replaced by an evidence-derived, PIT-safe cohort
   contract without weakening candle finality or `available_at <= decision_time`.
3. Finalized calibration rows carry the exact raw probability but not the
   confidence head's pre-sigmoid raw logit. Exact endpoint lineage therefore
   remains less informative than it can be.
4. The unchanged-weight calibration promoter/publisher is not yet activated.
   No trainer publisher or held service was started in this family.
5. Broader trainer/PPO resource and optimization constants remain outside this
   calibration family. They require scoped adaptive review; no claim is made
   that the whole trainer is already free of static heuristics.

## Exact next family

Implement and verify the immutable calibration-candidate plus validation-start
receipt, make the forward cohort append-only, and remove ordinary fixed
validation-fraction selection. Then commit, push, and create the next checkpoint
before touching the unchanged-weight promoter or any service state.

