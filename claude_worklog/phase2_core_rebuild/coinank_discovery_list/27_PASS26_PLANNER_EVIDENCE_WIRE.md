# Phase 2D CoinAnk Discovery List - Pass 26 Master Planner Evidence Wire

## 1. Decision

Pass 26 wires `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` into the master
rebuild planner's `evidence_satisfied_requirements()` so the post-Pass-21
Codex re-review PASS recorded in
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`
satisfies REQ_0002 the same way the existing USD-M correction marker
satisfies REQ_0001 and the legacy service map marker satisfies REQ_0005.

After Pass 26 lands, REQ_0002 leaves the `unprocessed_requirements` list
returned by `unprocessed_requirements()` and the planner advances to
`REQ_0004_TRAINER_GPU_PARITY.md` as the next active requirement.

This is the single edit Pass 25 section 7 documented as the next planner
action. No code module under `v2/` is touched. No fixture, test, ingestor,
legacy reference, secret, Redis path, exchange path, or live path is
touched.

## 2. Files changed by Pass 26

### 2.1 `claude_worklog/tools/claude_master_rebuild_planner.py`

Inside `evidence_satisfied_requirements()`, immediately after the
existing REQ_0001 block and before the REQ_0003 / REQ_0005 blocks, add
a four-line marker check:

    coinank_post_pass21 = read_text(WORKSPACE / "claude_worklog/phase2_core_rebuild/coinank_discovery_list/26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md", 2000)
    if "PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS" in coinank_post_pass21:
        satisfied["REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md"] = "phase2_coinank_discovery_list_codex_pass_post_pass21"

The historical `08_CODEX_GO_NO_GO.md` (still on disk with stale
`PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` from before Pass 21) is
deliberately not consulted. Pass 25 section 2 documented why the
post-Pass-21 PASS was redirected to file 26 to bypass the supervisor
idempotency lockout on task 042. File 08 is preserved as historical
evidence, not promoted to a current truth source.

No other line in the planner module is changed by Pass 26. The shape of
`unprocessed_requirements()`, `effective_processed_requirements()`,
`status_payload()`, `safe_materialize_blocks()`,
`ALLOWED_MATERIALIZE_PREFIXES`, and `FORBIDDEN_TEXT` are all preserved
byte-for-byte except for the four-line insertion above.

### 2.2 `claude_worklog/phase2_core_rebuild/coinank_discovery_list/27_PASS26_PLANNER_EVIDENCE_WIRE.md`

This Pass 26 closure note. New file. Documents the planner edit, why,
operator validation steps, safety boundaries, and the next planner
action.

## 3. Files explicitly NOT touched by Pass 26

- `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 21 fix is
  canonical).
- `v2/backend/app/domain/symbols/normalization.py`.
- `v2/backend/app/adapters/symbol_sources/coinank.py`.
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`.
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`.
- `v2/legacy_preserved/ingestors/live_coinank.py`.
- `legacy_reference/**`.
- `/home/wali/Desktop/AI BOT/**`.
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/00_SCOPE.md`
  through `26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md` (already on
  disk; Pass 26 only adds 27).
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/07_CODEX_REVIEW.md`
  and `08_CODEX_GO_NO_GO.md` (preserved as historical pre-Pass-21
  evidence).
- `claude_worklog/agent_supervisor/state/**` (planner has no write
  access; supervisor manages this directory).
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`.
- `claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json`.
- Any `.env`, secret, or credentials file. None is read or printed.
- Any Redis key, queue, or stream. None is read, written, or deleted.
- Any exchange path. No order placed or cancelled. No leverage or
  margin change. No live-trading enablement.

## 4. Operator validation steps after Pass 26 materializes

Run from `/home/wali/Desktop/AI BOT REBUILD`:

1. `python3 -m py_compile claude_worklog/tools/claude_master_rebuild_planner.py`
   Expected: no output, exit 0.
2. `python3 -c "import sys; sys.path.insert(0, 'claude_worklog/tools'); import claude_master_rebuild_planner as p; r = p.evidence_satisfied_requirements(); assert r.get('REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md') == 'phase2_coinank_discovery_list_codex_pass_post_pass21', r; print('REQ_0002 evidence wire ok:', r['REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md'])"`
   Expected: `REQ_0002 evidence wire ok: phase2_coinank_discovery_list_codex_pass_post_pass21`.
3. `python3 claude_worklog/tools/claude_master_rebuild_planner.py --status`
   Expected: JSON payload where the
   `evidence_satisfied_requirements` array includes
   `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md`, the
   `unprocessed_requirements` array no longer contains it, and
   `active_requirement` advances to `REQ_0004_TRAINER_GPU_PARITY.md`
   (or to whichever inbox file sorts first among the still-unprocessed
   set, expected to be REQ_0004 given the current inbox).
4. `python3 -m py_compile v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/domain/symbols/normalization.py v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: no output, exit 0 (Pass 21-25 working tree still parses).
5. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null && python3 -m json.tool < claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json > /dev/null && python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0 for all three.
6. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: `11 passed`.
7. `git status --short -- v2/legacy_preserved/ingestors/live_coinank.py legacy_reference claude_worklog/phase2_core_rebuild/coinank_discovery_list/07_CODEX_REVIEW.md claude_worklog/phase2_core_rebuild/coinank_discovery_list/08_CODEX_GO_NO_GO.md claude_worklog/agent_supervisor/state`
   Expected: empty (no protected/historical file or supervisor state
   path modified by Pass 26).
8. `tail -n 1 claude_worklog/phase2_core_rebuild/coinank_discovery_list/26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`
   Expected: `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`.

If steps 1 through 8 all pass, stage and commit Pass 26 on top of the
already on-disk Pass 21 through Pass 25 working tree. Two commits is
the recommended layout:

Commit A (Pass 21 through Pass 25 closure, per Pass 25 section 5
suggested message):

- `v2/backend/app/domain/symbols/coinank_rows.py`
- `v2/backend/app/domain/symbols/normalization.py`
- `v2/backend/app/adapters/symbol_sources/coinank.py`
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` (00 through 26)
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
- `claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json`

Commit B (Pass 26 planner evidence wire):

- `claude_worklog/tools/claude_master_rebuild_planner.py`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/27_PASS26_PLANNER_EVIDENCE_WIRE.md`

Suggested commit message for Commit B:

    Phase 2D CoinAnk discovery list - pass 26 planner evidence wire

    Adds REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md to the master rebuild
    planner's evidence_satisfied_requirements() via the post-Pass-21
    Codex re-review marker file
    26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md. REQ_0002 now leaves the
    unprocessed-requirements list and the next planner cycle advances
    to REQ_0004 trainer GPU parity scoping.

    Single edit: four-line marker check inserted into
    evidence_satisfied_requirements() between the REQ_0001 block and
    the REQ_0003 block. Historical 08_CODEX_GO_NO_GO.md is intentionally
    not consulted because it preserves the pre-Pass-21 CODEX_FAIL state;
    file 26 is the post-Pass-21 truth source per Pass 25 section 2.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. No leverage or margin change. No live-trading enablement.
    v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT untouched.
    claude_worklog/agent_supervisor/state/** untouched. Historical
    07_CODEX_REVIEW.md and 08_CODEX_GO_NO_GO.md preserved.

Then push.

## 5. Safety boundaries

- No live API calls.
- No Redis reads, writes, or deletes.
- No exchange-action paths.
- No leverage or margin change.
- No live-trading enablement.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- `.env` files and secret values are not read or printed.
- `claude_worklog/agent_supervisor/state/**` is not written by Pass 26.
- Historical `07_CODEX_REVIEW.md` and `08_CODEX_GO_NO_GO.md` are
  preserved.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed; ingesting the actual ODT into a real fixture remains a
  follow-up after REQ_0002 closes through Pass 26 evidence wiring.

## 6. Next planner action

After Pass 26 commits and pushes, the next planner cycle observes
REQ_0002 in `evidence_satisfied_requirements()` and selects
`REQ_0004_TRAINER_GPU_PARITY.md` as the new active requirement.

The next planner pass opens a new Phase 2 directory
`claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` and emits:

- `00_SCOPE.md` documenting the parity-rebuild objective vs a
  basic-trainer replacement and the read-only posture toward the
  protected trainer venv.
- `01_TRAINER_ATLAS_PLAN.md` referencing the existing
  `claude_worklog/trainer_atlas/TRAINER_SIZE_RECONCILIATION.md`
  authoritative size measurement and listing the function index, class
  index, import graph, config/env usage, Redis usage, reward paths,
  confidence paths, feature paths, signal paths, checkpoint paths,
  runtime entrypoints, and chunk hash deliverables.
- `02_GPU_CUDA_PRESERVATION_POLICY.md` that explicitly forbids:
  - mutating the protected trainer venv,
  - upgrading PyTorch or any CUDA-related package,
  - importing legacy trainer modules into the V2 FastAPI process,
  - running live trainer or live prediction worker processes,
  - placing or cancelling exchange orders,
  - changing leverage or margin mode.
- `03_TIER_A_REVIEW_PLAN.md` covering reward, MASS / state-space,
  feature ingestion / freshness, confidence calculation, signal
  publishing, orchestrator handoff, Redis writes, checkpoint
  save/load/promotion, `trainer_stale` logic, paper / live branching,
  and prediction-to-signal conversion.
- `04_SUBPROCESS_ADAPTER_CONTRACT_SKETCH.md` describing a non-live
  trainer subprocess adapter contract (input fixtures, output schema,
  feature_snapshot_id, prediction_id, confidence attribution, freshness
  flags, worker health telemetry) without any GPU or model code change.
- A Codex review task under
  `claude_worklog/agent_supervisor/tasks/050_codex_review_phase2_trainer_gpu_parity_scope.json`
  that reviews 00 through 04 only, requires `04_GO_NO_GO.md` containing
  `PHASE2_TRAINER_GPU_PARITY_SCOPE_READY_FOR_CODEX_REVIEW`, and emits
  `05_CODEX_REVIEW.md` plus `06_CODEX_GO_NO_GO.md` with the gate marker
  `PHASE2_TRAINER_GPU_PARITY_SCOPE_CODEX_PASS` or
  `PHASE2_TRAINER_GPU_PARITY_SCOPE_CODEX_FAIL`.

That follow-up pass introduces no GPU code change, no model code
change, no checkpoint mutation, no trainer venv mutation, no live API
call, no Redis write, no exchange action, and no leverage or margin
change.

If the trainer GPU parity scope Codex review returns
`PHASE2_TRAINER_GPU_PARITY_SCOPE_CODEX_FAIL` with a finding that
touches only artifacts under `claude_worklog/` or non-live planning
notes, the next planner pass emits a single targeted remediation note
under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` and does
not advance to a contract-implementation pass.

Any fail demanding modification of the protected trainer venv, GPU /
CUDA stack, `legacy_reference/**`, secrets, Redis, the exchange path,
leverage or margin, or `/home/wali/Desktop/AI BOT/**` is a hard stop
and is escalated to human review.

PHASE2_COINANK_DISCOVERY_LIST_PASS26_READY
