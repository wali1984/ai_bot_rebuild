# Phase 2D CoinAnk Discovery List - Pass 27 Planner Handoff Hold

## 1. Decision

Pass 27 is a no-advancement planner cycle. Pass 26's documented planner
evidence wire (file 27 in this directory,
`27_PASS26_PLANNER_EVIDENCE_WIRE.md`) requires a four-line marker check
to be inserted into
`claude_worklog/tools/claude_master_rebuild_planner.py` inside
`evidence_satisfied_requirements()`. The master planner cannot
materialize that edit because `claude_worklog/tools/` is not in
`ALLOWED_MATERIALIZE_PREFIXES` in
`claude_worklog/tools/claude_master_rebuild_planner.py`:

    ALLOWED_MATERIALIZE_PREFIXES = (
        "claude_worklog/agent_supervisor/tasks/",
        "claude_worklog/phase2_core_rebuild/",
        "claude_worklog/v2_scaffold_reviews/",
        "claude_worklog/security/",
        "claude_worklog/autonomous_control_plane/",
        "v2/",
    )

That is the documented safety boundary. Self-edit of the planner module
is reserved for human application. Pass 27 therefore emits no
BEGIN_FILE block targeting the planner module, no supervisor task that
would script-edit the planner module, and no `processed_requirements.json`
override (the runtime path under
`claude_worklog/agent_supervisor/runtime/master_planner/` is also
outside the allowed prefix set).

Pass 26 stands on disk in file 27 of this directory and awaits human
application of the four-line marker check, followed by the operator
validation and commit sequence already listed in file 27 sections 4
and 4 commit layout.

## 2. State observed by Pass 27

Phase 2D evidence on disk in this directory:

- `00_SCOPE.md` through `26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`
  inclusive.
- `27_PASS26_PLANNER_EVIDENCE_WIRE.md` (Pass 26 closure note).
- `26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md` final line is
  `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`. The post-Pass-21 Codex
  re-review under task 045 returned PASS.

Working tree (relative to `/home/wali/Desktop/AI BOT REBUILD`,
uncommitted at the time of Pass 27):

- Modified: `v2/backend/app/adapters/symbol_sources/coinank.py`
- Modified: `v2/backend/app/domain/symbols/normalization.py`
- Untracked: `v2/backend/app/domain/symbols/coinank_rows.py`
- Untracked: `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
- Untracked: `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
- Untracked: `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
  (Pass 0 through Pass 26 evidence, plus this Pass 27 hold note)
- Untracked: `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
- Untracked: `claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json`

Planner module (`claude_worklog/tools/claude_master_rebuild_planner.py`):

- `evidence_satisfied_requirements()` currently checks markers for
  REQ_0001 (USD-M correction Codex pass), REQ_0003 (ingestor preservation
  matrix plus ingestor GO/NO-GO), and REQ_0005 (legacy service map Codex
  pass). It does not yet check file 26 of this directory for the
  REQ_0002 marker.
- `unprocessed_requirements()` therefore still returns
  `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` even though file 26
  carries `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`.
- `choose_active_requirement()` therefore still returns
  `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md`.

This is the expected pre-Pass-26-commit state.

## 3. Action item required from the human operator

Apply the four-line marker check to
`claude_worklog/tools/claude_master_rebuild_planner.py` per file 27
section 2.1, immediately after the existing REQ_0001 block and before
the REQ_0003 / REQ_0005 blocks:

    coinank_post_pass21 = read_text(WORKSPACE / "claude_worklog/phase2_core_rebuild/coinank_discovery_list/26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md", 2000)
    if "PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS" in coinank_post_pass21:
        satisfied["REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md"] = "phase2_coinank_discovery_list_codex_pass_post_pass21"

Then run the eight operator validation steps in file 27 section 4:

1. `python3 -m py_compile claude_worklog/tools/claude_master_rebuild_planner.py`
2. The Python one-liner asserting
   `evidence_satisfied_requirements()['REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md'] == 'phase2_coinank_discovery_list_codex_pass_post_pass21'`.
3. `python3 claude_worklog/tools/claude_master_rebuild_planner.py --status`
   showing REQ_0002 in `evidence_satisfied_requirements`, absent from
   `unprocessed_requirements`, and `active_requirement` advancing to
   `REQ_0004_TRAINER_GPU_PARITY.md`.
4. `python3 -m py_compile` over the four V2 modules.
5. `python3 -m json.tool` over the two task JSONs and the synthetic
   fixture JSON.
6. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   showing `11 passed`.
7. `git status --short` over protected and historical files showing
   empty.
8. `tail -n 1` over file 26 showing
   `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`.

If steps 1 through 8 all pass, commit per file 27 section 4 commit
layout (Commit A for Pass 21 through Pass 26 and Pass 27 hold note;
Commit B for the planner module four-line edit), then push.

Once the planner edit lands in the working tree and the planner runs
again, REQ_0002 leaves `unprocessed_requirements()` and the next
planner cycle selects `REQ_0004_TRAINER_GPU_PARITY.md` as the new
active requirement.

## 4. Why Pass 27 does not script the planner edit through a supervisor task

A supervisor task whose `script` field invoked `python3` to insert the
four-line marker check would, in principle, bypass the planner-output
prefix restriction. Pass 27 deliberately does not take that route for
three reasons:

1. The `ALLOWED_MATERIALIZE_PREFIXES` constraint is a structural safety
   boundary against self-modification. Routing the same edit through a
   supervisor task script would honor the letter of the constraint
   while violating its intent.
2. The four-line edit is intentionally small and review-cheap. Human
   eyes on the planner diff plus the two-commit layout in file 27
   section 4 is materially safer than a supervisor task that scripts
   the edit and then the planner reads its own freshly-edited code on
   the next cycle.
3. The Pass 21 working tree, the two task JSONs, and the entire
   coinank_discovery_list directory (00 through 27) are all currently
   uncommitted. A supervisor-task-driven planner edit would interleave
   with that uncommitted set in a way the file 27 commit layout
   explicitly avoids.

If a future operator later decides a supervisor-driven planner edit is
acceptable, that decision belongs in a separate planner pass under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` (or under
a new directory) and is out of scope for Pass 27.

## 5. Files NOT touched by Pass 27

- Anything under `legacy_reference/**`.
- Anything under `/home/wali/Desktop/AI BOT/**`.
- `v2/legacy_preserved/ingestors/live_coinank.py`.
- Any `.env`, secret, or credentials file.
- Any Redis path, key, queue, or stream.
- Any exchange path. No order placed or cancelled. No leverage change.
  No margin-mode change. No live-trading enablement.
- `claude_worklog/agent_supervisor/state/**` (planner has no write
  access there).
- `claude_worklog/agent_supervisor/runtime/master_planner/processed_requirements.json`
  (outside the allowed prefix set).
- `claude_worklog/tools/claude_master_rebuild_planner.py` (planner
  cannot self-edit; deferred to human application of file 27 section
  2.1).
- Files 00 through 27 in this directory (preserved as Pass 0 through
  Pass 26 evidence). Pass 27 only adds file 28.
- `v2/backend/app/domain/symbols/coinank_rows.py`,
  `v2/backend/app/domain/symbols/normalization.py`,
  `v2/backend/app/adapters/symbol_sources/coinank.py`,
  `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`,
  and `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
  (Pass 21 working tree is canonical).
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  and `claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json`
  (Pass 24 and Pass 25 task JSONs are canonical).

## 6. Safety boundaries

- No live API call.
- No Redis read, write, or delete.
- No exchange-action path.
- No leverage change. No margin-mode change.
- No live-trading enablement.
- No mutation of the legacy bot, the legacy reference tree, or the
  protected trainer venv.
- No ingestor change. No `feature_pipeline.py` change.
- No GPU code change. No model code change. No checkpoint mutation.
- No secret value read or printed.
- No supervisor task generated by Pass 27 (Pass 27 is a documentation
  pass only; Pass 25's task 045 remains the most recent supervisor
  task in the Phase 2D series, and its required outputs are already on
  disk).
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed; ingesting the actual ODT into a real fixture remains a
  follow-up after REQ_0002 closes through the file 27 four-line wire
  and a future replacement-of-synthetic-fixture pass.

## 7. Next planner cycle expectation

After the human applies file 27 section 2.1 and runs file 27 section
4 validation steps and commits and pushes per file 27 section 4 commit
layout, the planner module's `evidence_satisfied_requirements()`
returns REQ_0002 with reason
`phase2_coinank_discovery_list_codex_pass_post_pass21`,
`unprocessed_requirements()` no longer contains REQ_0002, and
`choose_active_requirement()` returns
`REQ_0004_TRAINER_GPU_PARITY.md`.

The next planner cycle then opens
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` with the five
scope artifacts already documented in file 27 section 6:

- `00_SCOPE.md` (parity-rebuild objective vs basic-trainer replacement;
  read-only posture toward the protected trainer venv).
- `01_TRAINER_ATLAS_PLAN.md` (cites
  `claude_worklog/trainer_atlas/TRAINER_SIZE_RECONCILIATION.md` as the
  authoritative size measurement; lists function index, class index,
  import graph, config/env usage, Redis-usage map, reward paths,
  confidence paths, feature paths, signal paths, checkpoint paths,
  runtime entrypoints, chunk hash deliverables).
- `02_GPU_CUDA_PRESERVATION_POLICY.md` (forbids mutating the protected
  trainer venv, upgrading PyTorch or any CUDA-related package,
  importing legacy trainer modules into the V2 FastAPI process,
  running live trainer or live prediction worker processes, placing
  or cancelling exchange orders, leverage change, margin-mode change).
- `03_TIER_A_REVIEW_PLAN.md` (covers reward, MASS / state-space,
  feature ingestion / freshness, confidence calculation, signal
  publishing, orchestrator handoff, Redis-write inventory, checkpoint
  save/load/promotion, `trainer_stale` logic, paper / live branching,
  and prediction-to-signal conversion).
- `04_SUBPROCESS_ADAPTER_CONTRACT_SKETCH.md` (non-live trainer
  subprocess adapter contract: input fixtures, output schema,
  feature_snapshot_id, prediction_id, confidence attribution, freshness
  flags, worker health telemetry; no GPU or model code change).

Plus a Codex review task under
`claude_worklog/agent_supervisor/tasks/050_codex_review_phase2_trainer_gpu_parity_scope.json`
that reviews 00 through 04 only, requires `04_GO_NO_GO.md` containing
`PHASE2_TRAINER_GPU_PARITY_SCOPE_READY_FOR_CODEX_REVIEW`, and emits
`05_CODEX_REVIEW.md` plus `06_CODEX_GO_NO_GO.md` with the gate marker
`PHASE2_TRAINER_GPU_PARITY_SCOPE_CODEX_PASS` or
`PHASE2_TRAINER_GPU_PARITY_SCOPE_CODEX_FAIL`.

That follow-up cycle introduces no GPU code change, no model code
change, no checkpoint mutation, no trainer venv mutation, no live API
call, no Redis write, no exchange-action path, no leverage change,
and no margin-mode change.

If the trainer GPU parity scope Codex review returns
`PHASE2_TRAINER_GPU_PARITY_SCOPE_CODEX_FAIL` with a finding that
touches only artifacts under `claude_worklog/` or non-live planning
notes, the next planner pass emits a single targeted remediation note
under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` and does
not advance to a contract-implementation pass.

Any fail demanding modification of the protected trainer venv, the
GPU / CUDA stack, `legacy_reference/**`, secrets, Redis, the exchange
path, leverage, margin mode, or `/home/wali/Desktop/AI BOT/**` is a
hard stop and is escalated to human review.

PHASE2_COINANK_DISCOVERY_LIST_PASS27_HANDOFF_HOLD
