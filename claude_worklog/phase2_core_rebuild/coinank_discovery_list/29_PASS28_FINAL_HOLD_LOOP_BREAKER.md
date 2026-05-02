# Phase 2D CoinAnk Discovery List - Pass 28 Final Hold / Loop Breaker

## 1. Decision

Pass 28 is the FINAL planner-driven hold note for REQ_0002 before the
four-line evidence wire lands in
`claude_worklog/tools/claude_master_rebuild_planner.py`. Pass 27 (file
28 in this directory, `28_PASS27_PLANNER_HANDOFF_HOLD.md`) already
documented the structural deadlock:

- REQ_0002 work is functionally complete. The Pass 21 V2 working tree
  (`coinank_rows.py`, `normalization.py`,
  `adapters/symbol_sources/coinank.py`, the synthetic fixture, and the
  unit test) is on disk uncommitted and parses cleanly.
- File 26 (`26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`) carries
  `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS` from the post-Pass-21
  Codex re-review.
- `claude_worklog/tools/claude_master_rebuild_planner.py` is outside
  `ALLOWED_MATERIALIZE_PREFIXES` (lines 38-45 of the planner module),
  and Pass 27 section 4 explicitly rejected routing the four-line edit
  through a supervisor task because that would honor the letter of the
  self-modification safety boundary while violating its intent.

The four-line marker check, the eight operator validation steps, the
suggested commit layout, and the suggested commit message are all
already documented in `27_PASS26_PLANNER_EVIDENCE_WIRE.md` sections
2.1 and 4. Pass 28 does not duplicate them. Pass 28 only sets the
loop-breaker rule below.

## 2. Loop breaker rule

Future planner cycles invoked while REQ_0002 still appears in
`unprocessed_requirements()` (i.e., before the four-line marker check
lands in `evidence_satisfied_requirements()`) MUST NOT:

- emit any new BEGIN_FILE block targeting
  `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`,
- emit any new supervisor task JSON targeting REQ_0002 under
  `claude_worklog/agent_supervisor/tasks/`,
- emit any new BEGIN_FILE block targeting `v2/backend/app/...` or
  `v2/backend/tests/...` for CoinAnk-discovery-related code (the Pass
  21 working tree is canonical and any further code edit before
  REQ_0002 closes would interleave with the uncommitted Pass 21 set).

The planner has already exhausted the safe non-self-editing action
set for REQ_0002. Adding more hold notes would only increase commit
churn without changing the structural lock.

The only safe planner-driven actions available before the four-line
wire lands are:

- emit zero BEGIN_FILE blocks (silent pass), or
- emit work for a requirement that is neither already satisfied nor
  blocked by sequencing.

REQ_0001 (`phase2_usdm_correction_codex_pass`), REQ_0003
(`phase2_ingestor_preservation_ready`), and REQ_0005
(`legacy_service_map_codex_pass`) are already satisfied by markers
read by `evidence_satisfied_requirements()` at planner module lines
119-130.

REQ_0004 (`REQ_0004_TRAINER_GPU_PARITY.md`) is sequenced behind
REQ_0002 per Pass 26 section 6 and Pass 27 section 7. The
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` directory
remains unopened until REQ_0002 closes through the four-line wire.
Opening it now would pre-empt the documented sequencing and risk
diverging the Pass 21 commit boundary.

The net effect of Pass 28 is therefore: emit only this one file as a
loop-breaker marker, and rely on the harness to recognize the
no-advancement state on subsequent planner runs.

## 3. Action item still required from the human operator

Apply the four-line marker check from
`27_PASS26_PLANNER_EVIDENCE_WIRE.md` section 2.1 to
`claude_worklog/tools/claude_master_rebuild_planner.py`. Insert it
inside `evidence_satisfied_requirements()`, immediately after the
existing REQ_0001 block at planner module lines 119-121 and before
the REQ_0003 block at planner module lines 123-126:

    coinank_post_pass21 = read_text(WORKSPACE / "claude_worklog/phase2_core_rebuild/coinank_discovery_list/26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md", 2000)
    if "PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS" in coinank_post_pass21:
        satisfied["REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md"] = "phase2_coinank_discovery_list_codex_pass_post_pass21"

Then run the eight validation steps in
`27_PASS26_PLANNER_EVIDENCE_WIRE.md` section 4 (Python compile,
evidence-wire one-liner assertion, planner `--status` JSON inspection,
V2 module compile, three JSON parses, the eleven-test pytest run, the
protected-and-historical-files `git status --short` check empty, and
the `tail -n 1` over file 26 showing
`PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`).

If steps 1 through 8 pass, commit per `27_PASS26_PLANNER_EVIDENCE_WIRE.md`
section 4 commit layout (Commit A for the Pass 21 through Pass 26
content already on disk plus Pass 27 hold note plus this Pass 28 final
hold loop breaker; Commit B for the planner module four-line edit
applied by the operator). Then push.

## 4. State of REQ_0002 evidence at Pass 28

Phase 2D directory contents:

- `00_SCOPE.md` through `26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`
  inclusive (Pass 0 through Pass 25 evidence).
- `27_PASS26_PLANNER_EVIDENCE_WIRE.md` (Pass 26 closure documenting
  the four-line wire and operator validation).
- `28_PASS27_PLANNER_HANDOFF_HOLD.md` (Pass 27 no-advancement hold
  documenting the structural deadlock and why supervisor-task scripting
  of the planner edit is rejected).
- `29_PASS28_FINAL_HOLD_LOOP_BREAKER.md` (this file; Pass 28 sets the
  loop-breaker rule above so subsequent planner cycles do not stack
  duplicate hold notes).

V2 working tree (uncommitted, Pass 21 canonical):

- `v2/backend/app/adapters/symbol_sources/coinank.py` (modified)
- `v2/backend/app/domain/symbols/normalization.py` (modified)
- `v2/backend/app/domain/symbols/coinank_rows.py` (new)
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json` (new)
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` (new)

Supervisor task JSONs (uncommitted):

- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
- `claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json`

Planner module (`claude_worklog/tools/claude_master_rebuild_planner.py`):

- `evidence_satisfied_requirements()` at lines 116-132 still recognizes
  REQ_0001, REQ_0003, REQ_0005 only.
- `unprocessed_requirements()` at lines 142-144 therefore still
  returns `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md`.
- `choose_active_requirement()` at lines 163-164 therefore still
  returns `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md`.
- This is the expected pre-four-line-wire state.

## 5. Files explicitly NOT touched by Pass 28

- `claude_worklog/tools/claude_master_rebuild_planner.py` (planner
  cannot self-edit; the four-line wire is reserved for human
  application).
- All V2 source under `v2/backend/app/...` and
  `v2/backend/tests/...` (Pass 21 working tree is canonical; further
  CoinAnk-discovery edits before REQ_0002 closes would interleave with
  the uncommitted Pass 21 set).
- `v2/legacy_preserved/ingestors/live_coinank.py` (copy-as-is per
  REQ_0003).
- `legacy_reference/**`.
- `/home/wali/Desktop/AI BOT/**`.
- Any `.env`, secrets, or credentials file. None is read or printed.
- Any Redis path, key, queue, or stream. None is read, written, or
  deleted.
- Any exchange path. No order placed or cancelled. No leverage or
  margin change. No live-trading enablement.
- `claude_worklog/agent_supervisor/state/**` (planner has no write
  access there).
- `claude_worklog/agent_supervisor/runtime/master_planner/processed_requirements.json`
  (outside the allowed prefix set).
- Historical `07_CODEX_REVIEW.md` and `08_CODEX_GO_NO_GO.md` (preserved
  as pre-Pass-21 evidence; not promoted to current truth).
- Files 00 through 28 in this directory (preserved). Pass 28 only
  adds file 29.

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
- No supervisor task generated by Pass 28 (Pass 28 is a documentation
  pass only; Pass 25's task 045 remains the most recent supervisor
  task in the Phase 2D series, and its required outputs are already
  on disk).
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed; ingesting the actual ODT into a real fixture remains a
  follow-up after REQ_0002 closes through the four-line wire and a
  future replacement-of-synthetic-fixture pass.

## 7. Next planner cycle expectation

After the human applies the four-line marker check per Pass 27 section
2.1, runs Pass 27 section 4 validation, and commits and pushes per
Pass 27 section 4 commit layout:

- `evidence_satisfied_requirements()` returns REQ_0002 with reason
  `phase2_coinank_discovery_list_codex_pass_post_pass21`.
- `unprocessed_requirements()` no longer contains REQ_0002.
- `choose_active_requirement()` returns
  `REQ_0004_TRAINER_GPU_PARITY.md`.

The next planner cycle then opens
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` with the five
scope artifacts already enumerated in `27_PASS26_PLANNER_EVIDENCE_WIRE.md`
section 6 and `28_PASS27_PLANNER_HANDOFF_HOLD.md` section 7
(`00_SCOPE.md`, `01_TRAINER_ATLAS_PLAN.md`,
`02_GPU_CUDA_PRESERVATION_POLICY.md`, `03_TIER_A_REVIEW_PLAN.md`,
`04_SUBPROCESS_ADAPTER_CONTRACT_SKETCH.md`) plus a Codex review task
under
`claude_worklog/agent_supervisor/tasks/050_codex_review_phase2_trainer_gpu_parity_scope.json`
that requires `04_GO_NO_GO.md` containing
`PHASE2_TRAINER_GPU_PARITY_SCOPE_READY_FOR_CODEX_REVIEW` and emits
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
under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` and
does not advance to a contract-implementation pass.

Any fail demanding modification of the protected trainer venv, the
GPU / CUDA stack, `legacy_reference/**`, secrets, Redis, the exchange
path, leverage, margin mode, or `/home/wali/Desktop/AI BOT/**` is a
hard stop and is escalated to human review.

PHASE2_COINANK_DISCOVERY_LIST_PASS28_FINAL_HOLD_LOOP_BREAKER
