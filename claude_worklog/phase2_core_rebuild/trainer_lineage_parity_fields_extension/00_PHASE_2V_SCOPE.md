# Phase 2V — Trainer Lineage Parity Fields Extension — Scope

## Objective

Close the five remaining trainer-prediction lineage gaps in the V2 non-live proof projection so that `TRAINER_LINEAGE_AND_READINESS` can flip from `BLOCKED` to `READY` for the live-gate review, while preserving all hard non-live boundaries.

## Single consolidated milestone

This phase is a single consolidated Lane A (`paper_backtest_mvp`) milestone under the Claude Code Max20 consolidated default. It is not split into sub-phases.

## In-scope edits

1. `v2/backend/app/proof/non_live_operational_proof.py`
   - Extend `ProofScenario` with five deterministic fixture fields:
     - `model_version: str`
     - `checkpoint_id: str`
     - `confidence_raw: float`
     - `confidence_calibrated: float`
     - `trainer_worker_liveness: str` (one of `alive`, `degraded`, `worker_dead`)
   - Update `_base_lineage` to emit those fields on every projection row (replay/backtest, paper ledger, risk gateway, decision explainability, shadow comparison).
   - Keep `confidence` field for backward compatibility (set equal to `confidence_calibrated`).
   - Populate fixture values for the five existing scenarios:
     - `safe_long_paper_intent` — alive
     - `stale_data_blocked` — degraded
     - `duplicate_signal_blocked` — alive
     - `hedge_close_residual_exposure_blocked` — alive
     - `lab_hedge_unwind_short_squeeze` — worker_dead (fixture exposes legacy "process alive but worker dead" signal)
   - All values are deterministic non-live fixture identities. No model files, no checkpoints, no GPU runtime are loaded.

2. `claude_worklog/tools/build_autonomous_live_readiness_builder.py`
   - In `build_trainer_gate`, replace the hardcoded `False` entries for `model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `trainer_worker_liveness` with reads from the per-row payload of `decision_explainability_result.json`.
   - A field is considered covered when every explanation row has a non-empty, non-`evidence_missing` value.
   - Marker logic remains: any gap → `TRAINER_LINEAGE_AND_READINESS_BLOCKED`; zero gaps → `TRAINER_LINEAGE_AND_READINESS_READY`.
   - Update `_trainer_report` to emit the success-path summary line when there are no gaps.

3. `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py`
   - Extend `test_required_lineage_fields_are_present` to require the five new fields on every scenario row of `replay_backtest_result.json`.

4. `v2/backend/tests/unit/proof/test_trainer_lineage_parity_fields_coverage.py` (new)
   - Generate the proof harness output to `tmp_path / "proof"`.
   - Invoke `build_trainer_gate` against the regenerated artifact.
   - Assert `marker == "TRAINER_LINEAGE_AND_READINESS_READY"` and `gaps == []`.

5. `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/06_IMPLEMENTATION_REPORT.md`
6. `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/07_GO_NO_GO.md`
   - Single line exactly `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_READY_FOR_CODEX_REVIEW`.

7. Regenerated runtime artifacts (committed to make the marker flip visible):
   - `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/GO_NO_GO.md`
   - `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/trainer_lineage_coverage.json`
   - `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/trainer_evidence_gaps.md`
   - `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/TRAINER_LINEAGE_AND_READINESS_REPORT.md`
   - Mirror under `v2/frontend/public/trainer_lineage_and_readiness/latest/`.

## Out of scope at Phase 2V

- Adding new lineage IDs beyond the five named fields.
- Loading any actual model file, checkpoint, or GPU runtime.
- Modifying `v2/backend/app/domain/`, `v2/backend/app/services/`, `v2/backend/app/composition/`, or any frontend source other than the public trainer-lineage mirror.
- Modifying any prior-milestone artifact byte content under `claude_worklog/phase2_core_rebuild/` other than this Phase 2V directory.
- Modifying `/home/wali/Desktop/AI BOT`.
- Writing Redis, restarting live services, placing/cancelling orders, changing leverage/margin, enabling live trading, deploying, or exposing secrets.

## Validation gate

`pytest v2/backend/tests/unit/proof -q` must pass.

After the implementation runs `python3 claude_worklog/tools/build_autonomous_live_readiness_builder.py`, the regenerated `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/GO_NO_GO.md` must contain exactly `TRAINER_LINEAGE_AND_READINESS_READY`.

## Final live gate

Live trading remains `blocked_human_only`. This phase prepares the trainer lineage evidence the live-gate reviewer reads; it does not approve, request, or simulate live approval.

PHASE_2V_SCOPE
