# Phase 2V — Trainer Lineage Parity Fields Test Plan

## Tests modified

### `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py`

Extend `test_required_lineage_fields_are_present` so its `required` set additionally requires:
- `model_version`
- `checkpoint_id`
- `confidence_raw`
- `confidence_calibrated`
- `trainer_worker_liveness`

These five fields must be present on every scenario in `replay_backtest_result.json["scenarios"]`.

The other six tests in the file remain unchanged. The forbidden-token scan (`test_harness_does_not_use_live_side_effect_terms`) keeps the live-side-effect blocklist intact.

## Tests added

### `v2/backend/tests/unit/proof/test_trainer_lineage_parity_fields_coverage.py`

Three deterministic tests:

1. `test_decision_explainability_result_carries_five_trainer_fields`
   - Calls `build_non_live_proof()`.
   - Asserts every row of `decision_explainability_result["explanations"]` carries the five new fields with the expected per-scenario values from the spec table.

2. `test_paper_ledger_events_carry_five_trainer_fields`
   - Calls `build_non_live_proof()`.
   - Asserts every event in `paper_ledger_result["events"]` carries the five new fields (because `_ledger_event` consumes `_base_lineage`).

3. `test_build_trainer_gate_marker_flips_to_ready`
   - Imports `build_trainer_gate` from `claude_worklog/tools/build_autonomous_live_readiness_builder.py` via direct module load (using `importlib.util.spec_from_file_location`) to avoid forcing a package layout under `claude_worklog/tools/`.
   - Writes the proof output to `tmp_path / "proof"` via `write_non_live_proof`.
   - Stages a redirected `TRAINER` and `PUBLIC_TRAINER` path on the loaded module so the test does not touch the production runtime artifact directories.
   - Invokes `build_trainer_gate()` with the staged proof output as input.
   - Asserts the returned status `marker == "TRAINER_LINEAGE_AND_READINESS_READY"`, `gaps == []`, and the regenerated `GO_NO_GO.md` contains exactly `TRAINER_LINEAGE_AND_READINESS_READY`.

If, for environmental simplicity, redirection of the module-level paths is not desirable, the test may instead drive a copy of `build_trainer_gate`'s coverage logic directly against the proof artifact dictionary by importing a small refactored helper. The implementer chooses the cleanest path consistent with the no-mock policy already in force on the harness tests.

## No mocks, no patching

The tests must remain deterministic and free of `unittest.mock`, `monkeypatch.setattr`, or `pytest-mock`. The proof contract is data-only; the trainer gate logic is data-only; both are testable from real data.

## Validation command

```
PYTHONPATH=. python3 -m pytest v2/backend/tests/unit/proof -q
```

This must pass before the milestone is sealed.

## Re-run command for the autonomous builder

```
PYTHONPATH=. python3 claude_worklog/tools/build_autonomous_live_readiness_builder.py
```

After this command:
- `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/GO_NO_GO.md` contains exactly `TRAINER_LINEAGE_AND_READINESS_READY`.
- `v2/frontend/public/trainer_lineage_and_readiness/latest/GO_NO_GO.md` contains exactly `TRAINER_LINEAGE_AND_READINESS_READY`.
- `trainer_lineage_coverage.json` `coverage` block lists every field as `true`, `gaps` is `[]`, `marker` is `TRAINER_LINEAGE_AND_READINESS_READY`.

## Forbidden in tests

- No live side-effect tokens (existing forbidden-token scan still applies project-wide).
- No network call, no Redis, no exchange API, no Binance read-only call.
- No reading or writing under `/home/wali/Desktop/AI BOT`.
- No reading or writing of any file containing secret material.

PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_TEST_PLAN_READY
