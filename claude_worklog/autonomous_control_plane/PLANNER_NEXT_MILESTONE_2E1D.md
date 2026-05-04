# Planner Next-Milestone Selection — Phase 2E1.D

## Decision

The next safest non-live milestone for REQ_0006 is Phase 2E1.D —
Trainer Parity Service Composition. This milestone composes the
α / β / γ / δ / γ.real / γ.real.factory layers into a single in-process
service callable that turns a `StreamLatestIdReader` plus prior
per-stream observation histories into a populated
`LivenessSignalSnapshot` and updated histories.

## Why this is the safest next step

All seven predecessor Codex PASS markers are present and clean:

- PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_GAMMA_REAL_FACTORY_TRAINER_PARITY_IMPL_CODEX_PASS

Phase 2E1.D is a pure-Python orchestration layer:

- No Redis import. No Redis read at construction. No Redis read at
  unit test time (the reader is injected; tests use hand-written
  fakes).
- No subprocess. No socket. No network. No wall-clock call. The
  supplied `now_ms_clock` is the sole time source.
- No FastAPI lifespan, startup hook, dependency, router registration,
  module-level singleton, or background task.
- Additive only. Modifies zero prior-milestone files. Adds four new
  source files under `v2/backend/app/services/trainer_parity/` and
  32 new test files under `v2/backend/tests/unit/services/trainer_parity/`.
- Cross-isolation enforced via a forbidden-token guard test plus a
  `git status -s` zero-line gate over every prior-milestone path.
- The factory remains the ONLY trainer-parity module that imports
  `redis`. The 2E1.D service receives a reader through dependency
  injection; the composition root that wires the factory into the
  service is deferred to 2E1.E.

## Predecessors satisfied

- 22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md: PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS
- 34_2E1B_CODEX_GO_NO_GO.md: PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS
- 53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md: PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS
- 69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md: PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS
- 95_2E1C_GAMMA_CODEX_GO_NO_GO.md: PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS
- 87_2E1C_DELTA_CODEX_GO_NO_GO.md: PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS
- 103_2E1C_GAMMA_REAL_CODEX_GO_NO_GO.md: PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS
- 111_2E1C_GAMMA_REAL_FACTORY_CODEX_GO_NO_GO.md: PHASE2E1C_GAMMA_REAL_FACTORY_TRAINER_PARITY_IMPL_CODEX_PASS

## Hard stops not triggered

- No legacy mutation (`/home/wali/Desktop/AI BOT` untouched).
- No Redis writes or deletes.
- No exchange action.
- No live trainer / trader / orchestrator / Redis / VPN restart.
- No subprocess at unit-test time.
- No deploy intent.
- No production migration.
- No secret exposure.
- No L4 / L5 behavior.

## Artifacts authored or referenced in this turn

Authoring docs (already on disk from the prior planner turn — body
content correct, only the trailing standalone `END_FILE: <path>`
marker line is leaked and is the responsibility of the 093 recovery
task in this turn):

- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/112_PHASE_2E1D_SERVICE_COMPOSITION_SPEC.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/113_PHASE_2E1D_SERVICE_COMPOSITION_TEST_PLAN.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/114_PHASE_2E1D_SERVICE_COMPOSITION_SAFETY_BOUNDARIES.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/115_PHASE_2E1D_SERVICE_COMPOSITION_GO_NO_GO_REQUEST.md

Supervisor tasks (already on disk from the prior planner turn — JSON
body correct, only the trailing standalone `END_FILE: <path>` marker
line is leaked, which makes the JSON files invalid for parsing and is
the responsibility of the 093 recovery task in this turn):

- claude_worklog/agent_supervisor/tasks/091_trainer_parity_2e1d_service_composition_implementation.json
- claude_worklog/agent_supervisor/tasks/092_trainer_parity_2e1d_service_composition_codex_review.json

New planner artifacts emitted in this turn:

- claude_worklog/autonomous_control_plane/PLANNER_NEXT_MILESTONE_2E1D.md (this file, completed and rewritten)
- claude_worklog/agent_supervisor/tasks/093_codex_recovery_2e1d_end_file_marker_leakage_cleanup.json (Codex recovery task)

## Recovery action taken in this turn

Per REQ_0015 § "Planner-Level Human Attention Codex Autorecovery"
trigger list, the prior planner turn left a trailing standalone
`END_FILE: <path>` marker line at the bottom of six materialized
files (091.json, 092.json, 112.md, 113.md, 114.md, 115.md). For the
two JSON files this leakage is a hard blocker because the supervisor
parses tasks via `json.load`, and a stray `END_FILE: ...` line after
the closing brace makes the file invalid JSON. For the four markdown
files the leakage is cosmetic but still must be removed for evidence
hygiene.

Root cause: `claude_worklog/tools/claude_master_rebuild_planner.py`
function `parse_begin_file_blocks` uses the regex
`^BEGIN_FILE:?\s*(.*?)\n(.*?)\nEND_FILE\s*$` which only matches a
bare `END_FILE` closing line, but the prior planner turn emitted
`END_FILE: <path>` (trailing path) closing markers. The strict regex
fell back to the marker-only fallback, which strips a bare `END_FILE`
suffix but does not strip an `END_FILE: <path>` suffix, so the
trailing line was written into the materialized file body.

Recovery decision: dispatch a single L1 Codex recovery task
(`093_codex_recovery_2e1d_end_file_marker_leakage_cleanup`) that

1. inspects each of the six leaked files,
2. removes only the trailing standalone `END_FILE: <path>` line if and
   only if that line is the absolute last line of the file and its
   path-after-colon equals the file's own repo-relative path,
3. validates that the two JSON files parse via `json.load` after the
   strip,
4. validates that the four markdown files still end on a non-empty
   line after the strip,
5. extends the materializer regex in
   `claude_worklog/tools/claude_master_rebuild_planner.py` so that
   future emissions tolerate `END_FILE` and `END_FILE: <path>`
   identically,
6. runs the high-confidence secret scan over every modified file,
7. commits and pushes the recovery diff.

The 093 task ONLY strips the leaked marker line and ONLY patches the
materializer regex. It does NOT modify the body content of 091, 092,
112, 113, 114, or 115. It does NOT modify any prior-milestone source
or test file. It does NOT touch `/home/wali/Desktop/AI BOT`. It does
NOT read or write Redis. It does NOT restart any live service. It
does NOT place exchange orders. It does NOT change leverage or
margin. It does NOT enable live trading. It does NOT deploy.

On 093 success, the supervisor dispatches 091. On 091 success
(`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_IMPL_AND_VALIDATION_PASSED`
in 117), the supervisor dispatches 092. On 092 success
(`PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS` in 119),
the trainer-liveness assembly stack is complete and the planner opens
2E1.E (composition root that wires the γ.real factory into
`evaluate_trainer_liveness`) under a fresh spec turn.

On 093 FAIL with concrete blockers and no safety violation, the
supervisor dispatches a narrow REQ_0007 / REQ_0014 autofix task
scoped to the same six files plus the materializer regex only.

On any safety violation, surface to human attention; no autofix is
permitted.
