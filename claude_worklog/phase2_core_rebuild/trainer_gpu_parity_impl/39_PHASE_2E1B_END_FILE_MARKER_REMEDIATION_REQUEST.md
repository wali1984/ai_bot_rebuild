# Phase 2E1.B — END_FILE Marker Remediation Request

## Context

Task 056 emitted the eight Phase 2E1.B domain modules and eleven Phase 2E1.B unit tests using BEGIN_FILE / END_FILE materialization blocks. The harness materialized each block but left the trailing `END_FILE: <path>` marker line inside the materialized file as bare top-level text. For Python files this is a `SyntaxError` at compile time — pytest cannot collect the test package, and `import v2.backend.app.domain.trainer_parity` cannot succeed.

The planner discovered this in the turn that produced
`claude_worklog/autonomous_control_plane/PLANNER_PHASE2E1B_END_FILE_MARKER_DISCOVERY.md`.

`32_2E1B_GO_NO_GO.md` has been downgraded to `PHASE2E1B_TRAINER_PARITY_IMPL_BLOCKED` so neither task 058 (local validation) nor task 057 (Codex review) can dispatch against the broken tree.

## Required remediation

Strip the trailing `END_FILE: <path>` line from each of the following 19 files. The strip must:

1. Use the **Edit** tool, never the BEGIN_FILE / END_FILE materialization path (BEGIN_FILE / END_FILE re-emission is the cause of the defect).
2. Remove **only** the final line of each file, and **only if** that line equals exactly `END_FILE: ` followed by the file's repo-relative path.
3. Leave the rest of the file byte-identical.
4. Not introduce any new imports, comments, blank lines, or trailing whitespace beyond the natural single trailing newline at end-of-file.

### Source files (8)

- `v2/backend/app/domain/trainer_parity/__init__.py`
- `v2/backend/app/domain/trainer_parity/errors.py`
- `v2/backend/app/domain/trainer_parity/feature_status_flags.py`
- `v2/backend/app/domain/trainer_parity/freshness_metadata.py`
- `v2/backend/app/domain/trainer_parity/stage_a_record.py`
- `v2/backend/app/domain/trainer_parity/stage_b_record.py`
- `v2/backend/app/domain/trainer_parity/lineage_validator.py`
- `v2/backend/app/domain/trainer_parity/explainability_validator.py`

### Test files (11)

- `v2/backend/tests/unit/domain/trainer_parity/__init__.py` (special case: this file's only content is the `END_FILE:` marker. After remediation it must be a zero-byte or single-newline file so the package is importable. The Edit operation should replace the single existing line with an empty file body — equivalent to `python -c "open(p,'w').close()"` semantics — but performed via Edit.)
- `v2/backend/tests/unit/domain/trainer_parity/conftest.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_stage_a_record_invariants.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_stage_b_record_invariants.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_feature_status_flags.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_feature_freshness_envelope.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_freshness_metadata.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_lineage_validator_stage_a.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_lineage_validator_stage_b.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_explainability_validator.py`
- `v2/backend/tests/unit/domain/trainer_parity/test_public_surface.py`

## Required verification

After all 19 strips:

1. `rg "^END_FILE:" v2/backend/app/domain/trainer_parity/` — must return zero hits.
2. `rg "^END_FILE:" v2/backend/tests/unit/domain/trainer_parity/` — must return zero hits.
3. For each of the 8 source modules, run `python -m py_compile <file>` using the V2 control-plane Python interpreter (NOT the legacy trainer venv) and capture exit code. Each must be 0.
4. For each of the 11 test files, run `python -m py_compile <file>` and capture exit code. Each must be 0.
5. Confirm `v2/backend/tests/unit/domain/trainer_parity/__init__.py` is either zero bytes or a single newline.

If any verification fails, the remediation task halts and writes `PHASE2E1B_END_FILE_MARKER_REMEDIATION_FAILED` to `41_2E1B_END_FILE_REMEDIATION_GO_NO_GO.md`.

## Required outputs from the remediation task

- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/40_2E1B_END_FILE_REMEDIATION_REPORT.md` — the per-file before/after summary, the four verification block results, and the explicit confirmation that no logic changed.
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/41_2E1B_END_FILE_REMEDIATION_GO_NO_GO.md` — exactly one line: `PHASE2E1B_END_FILE_MARKER_REMEDIATION_PASSED` or `PHASE2E1B_END_FILE_MARKER_REMEDIATION_FAILED`.
- On PASS, `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/32_2E1B_GO_NO_GO.md` re-emitted as `PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`.
- On FAIL, `32_2E1B_GO_NO_GO.md` left as `PHASE2E1B_TRAINER_PARITY_IMPL_BLOCKED`.

## Forbidden in remediation scope

- No edits to V2 logic — every diff must be a deletion of a single trailing `END_FILE:` line, except for `v2/backend/tests/unit/domain/trainer_parity/__init__.py` which becomes empty.
- No new modules.
- No spec changes.
- No test additions or removals.
- No legacy-tree access.
- No Redis access.
- No subprocess other than `python -m py_compile` and `grep` / `rg`.
- No network access.
- No `.env` access.
- No commit or push (the supervisor performs commit on its own cycle once 058 PASS is reached).

## Predecessor chain

- Predecessor: task 056 (implementation files emitted) — satisfied.
- Successor: task 058 (local validation) — re-eligible only after `41_2E1B_END_FILE_REMEDIATION_GO_NO_GO.md` reads `PHASE2E1B_END_FILE_MARKER_REMEDIATION_PASSED` and `32_2E1B_GO_NO_GO.md` reads `PHASE2E1B_TRAINER_PARITY_IMPL_READY_FOR_CODEX_REVIEW`.

PHASE2E1B_END_FILE_MARKER_REMEDIATION_REQUEST_RECORDED
