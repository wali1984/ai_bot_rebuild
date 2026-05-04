# Planner Next-Milestone Selection — Phase 2E1.E

## Decision

The next safest non-live milestone for REQ_0006 is Phase 2E1.E —
Trainer Parity Composition Root. This milestone authors a single
wiring function `build_trainer_liveness_evaluator(...)` that calls
the γ.real factory `make_real_redis_stream_latest_id_reader` to build
a Redis-backed reader and returns a static-config-bound evaluator
closure that invokes `evaluate_trainer_liveness(reader, ...)` with
the cached config plus caller-supplied per-evaluation histories.

## Why this is the safest next step

All nine predecessor Codex PASS markers are present and clean:

- PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1C_GAMMA_REAL_FACTORY_TRAINER_PARITY_IMPL_CODEX_PASS
- PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS

Phase 2E1.E is a pure-Python wiring layer:

- One factory call at build time. No subsequent Redis calls outside
  the gated `RedisStreamLatestIdReader.latest_stream_id` path.
- No subprocess. No socket. No network. No wall-clock call. The
  supplied `now_ms_clock` is the sole time source forwarded to the
  service.
- No FastAPI lifespan, startup hook, dependency, router registration,
  module-level singleton, or background task.
- Additive only. Modifies zero prior-milestone files. Adds four new
  source files under `v2/backend/app/composition/trainer_parity/`
  (with the `composition/` package marker created on demand) and 25
  new test files under
  `v2/backend/tests/unit/composition/trainer_parity/`.
- Cross-isolation enforced via a forbidden-token guard test plus a
  `git status -s` zero-line gate over every prior-milestone path.
- The composition root is the FIRST trainer-parity milestone that is
  allowed to import the γ.real factory, with exactly one explicit
  forbidden-token-guard exemption for that single import line. The
  factory remains the only redis-importing module in the chain; the
  composition root layers on top via dependency injection.

## Module-location decision

The composition root lives under a NEW top-level package
`v2/backend/app/composition/trainer_parity/`, NOT inside
`v2/backend/app/services/trainer_parity/`. Placing it under the
service directory would force the 2E1.D forbidden-token guard
(`test_service_milestone_forbidden_tokens.py`) to grow per-file
exemptions and would break the 2E1.D import-isolation test
(`test_service_does_not_import_factory_or_url_env.py`), both of
which are explicit cross-isolation invariants of the just-passed
milestone. The 092 task definition's reference to a future
`composition_root.py` under the service directory is treated as
preliminary; the planner overrides it here with the more isolating
location. The 2E1.D service's redis-clean import invariant is
preserved verbatim.

## Predecessors satisfied

- 22_CODEX_GO_NO_GO_AFTER_REMEDIATION.md: PHASE2E1A_TRAINER_PARITY_IMPL_CODEX_PASS
- 34_2E1B_CODEX_GO_NO_GO.md: PHASE2E1B_TRAINER_PARITY_IMPL_CODEX_PASS
- 53_2E1C_ALPHA_CODEX_REREVIEW_GO_NO_GO.md: PHASE2E1C_ALPHA_TRAINER_PARITY_IMPL_CODEX_PASS
- 69_2E1C_BETA_FINAL_CODEX_GO_NO_GO.md: PHASE2E1C_BETA_TRAINER_PARITY_IMPL_CODEX_PASS
- 95_2E1C_GAMMA_CODEX_GO_NO_GO.md: PHASE2E1C_GAMMA_TRAINER_PARITY_IMPL_CODEX_PASS
- 87_2E1C_DELTA_CODEX_GO_NO_GO.md: PHASE2E1C_DELTA_TRAINER_PARITY_IMPL_CODEX_PASS
- 103_2E1C_GAMMA_REAL_CODEX_GO_NO_GO.md: PHASE2E1C_GAMMA_REAL_TRAINER_PARITY_IMPL_CODEX_PASS
- 111_2E1C_GAMMA_REAL_FACTORY_CODEX_GO_NO_GO.md: PHASE2E1C_GAMMA_REAL_FACTORY_TRAINER_PARITY_IMPL_CODEX_PASS
- 124_2E1D_CODEX_REREVIEW_AFTER_AUTOFIX_GO_NO_GO.md: PHASE2E1D_TRAINER_PARITY_SERVICE_COMPOSITION_CODEX_PASS

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

Authoring docs (emitted this turn):

- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/125_PHASE_2E1E_COMPOSITION_ROOT_SPEC.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/126_PHASE_2E1E_COMPOSITION_ROOT_TEST_PLAN.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/127_PHASE_2E1E_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md
- claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/128_PHASE_2E1E_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md

Supervisor tasks (emitted this turn):

- claude_worklog/agent_supervisor/tasks/096_trainer_parity_2e1e_composition_root_implementation.json
- claude_worklog/agent_supervisor/tasks/097_trainer_parity_2e1e_composition_root_codex_review.json

Planner artifacts (emitted this turn):

- claude_worklog/autonomous_control_plane/PLANNER_NEXT_MILESTONE_2E1E.md (this file)
- claude_worklog/autonomous_control_plane/PLANNER_TURN_2E1E_OPEN_COMPOSITION_ROOT.md

## Stale evidence acknowledgement

Files 112-115 under
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/` retain
a single trailing standalone `END_FILE: <path>` line from the prior-
prior planner turn. The 2E1.D Codex re-review (124) explicitly
declared this leakage cosmetic and the milestone closed PASS without
the markdown cleanup. The planner does NOT re-emit those four files
this turn. The planner-tool regex hardening (planned for 093, never
dispatched in its original form) is no longer load-bearing because
this turn closes every block with the bare `END_FILE` form that the
strict materializer regex matches cleanly. If a future Codex
watchdog cycle wants to clean those four markdowns for hygiene, the
diff is bounded to those four files only.

## Dispatch sequence directive

1. Supervisor commits this turn's working-tree artifacts (the four
   spec markdown files, the two task JSON files, the two planner-turn
   artifacts) plus the prior already-modified
   `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.

2. Supervisor dispatches
   `096_trainer_parity_2e1e_composition_root_implementation`. 096
   emits the four authored source files plus the 27 test-tree files
   (25 tests + 2 package markers) plus 129 (implementation report)
   and 130 (impl GO/NO-GO marker).

3. On 096 PASS marker
   `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED`,
   supervisor dispatches
   `097_trainer_parity_2e1e_composition_root_codex_review`. 097
   emits 131 (Codex review report) and 132 (Codex GO/NO-GO marker).

4. On 097 PASS marker
   `PHASE2E1E_TRAINER_PARITY_COMPOSITION_ROOT_CODEX_PASS`, the
   trainer-liveness assembly stack is fully wired end-to-end. The
   planner closes Phase 2E1 (trainer liveness foundation) under
   REQ_0006 and opens the next REQ_0006 sub-phase (trainer prediction
   worker health metrics or trainer GPU / checkpoint runner) under a
   fresh consolidated milestone turn.

## REQ_0007 / REQ_0014 fallback

- 096 FAIL with concrete blockers and zero safety violation:
  supervisor dispatches a narrow REQ_0007 / REQ_0014 autofix task
  scoped to the three authored source files (`__init__.py`,
  `errors.py`, `runtime.py`) plus the 25 new test files only.
- 097 FAIL with concrete blockers and zero safety violation:
  same scope as the 096 fallback.
- Any safety violation in 096 or 097: surface to human attention; no
  autofix permitted.

## End-marker discipline this turn

This turn's eight emitted blocks (125, 126, 127, 128, 096.json,
097.json, this markdown, and the planner turn note) all close with
the bare `END_FILE` form so the strict materializer regex
`^BEGIN_FILE:?\s*(.*?)\n(.*?)\nEND_FILE\s*$` matches cleanly. No
emitted block uses the `END_FILE: <path>` close form. This turn
therefore introduces zero new trailing-marker leakage to the working
tree.

PHASE2E1E_PLANNER_NEXT_MILESTONE_DECISION_READY
