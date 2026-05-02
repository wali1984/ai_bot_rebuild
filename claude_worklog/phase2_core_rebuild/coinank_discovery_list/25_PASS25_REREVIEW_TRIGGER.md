# Phase 2D CoinAnk Discovery List - Pass 25 Re-Review Trigger

## 1. Decision

Pass 25 unblocks the post-Pass-21 Codex re-review. Passes 21 through 24
have been on disk (untracked) since their respective planner emissions,
but supervisor task `042_codex_review_phase2_coinank_discovery_list`
has not actually re-run Codex against the Pass 21 fixed module set.

The runtime state file at
`claude_worklog/agent_supervisor/state/tasks/042_codex_review_phase2_coinank_discovery_list.json`
records `status: completed` with `last_summary: "required outputs
already exist"`. The supervisor's idempotency check in
`claude_worklog/tools/agent_supervisor.py` short-circuits when both
required output files exist on disk and the task state is `completed`:

    existing_missing = check_required_outputs(task)
    if not existing_missing and str(task.get("status", "")) == "completed":
        result["status"] = "completed"
        result["summary"] = "required outputs already exist"

Both `07_CODEX_REVIEW.md` (stale CODEX_FAIL findings naming the pre-Pass-21
`_classify_quote_kind` blind spot) and `08_CODEX_GO_NO_GO.md` (stale
`PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL`) already exist, so 042
short-circuits without invoking Codex. Re-emitting 042's JSON in
subsequent planner cycles cannot break this lockout because the planner
cannot write under `claude_worklog/agent_supervisor/state/` (the prefix
is not in `ALLOWED_MATERIALIZE_PREFIXES`), so the runtime
`status: completed` field is preserved across cycles.

## 2. Pass 25 unblock strategy

Emit a fresh supervisor task `045_codex_rereview_phase2_coinank_discovery_list_post_pass21`
that:

1. Carries a new `task_id`, which produces a new state file under
   `claude_worklog/agent_supervisor/state/tasks/` initialized at
   `status: pending`. The 042 state file is left untouched (the planner
   has no delete capability and no write path under `state/`).
2. Names new `required_output_files`:
   - `claude_worklog/phase2_core_rebuild/coinank_discovery_list/25_CODEX_REREVIEW_AFTER_PASS21.md`
   - `claude_worklog/phase2_core_rebuild/coinank_discovery_list/26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`
   Neither file exists on disk, so `check_required_outputs` returns a
   non-empty `existing_missing` list and the supervisor cannot
   short-circuit on idempotency.
3. Re-uses the Pass 24 input list verbatim (00-05, 06_GO_NO_GO,
   06b, 09, 19, 20, 21, 22, 23, 24, plus the four reviewed `.py`
   modules, the synthetic JSON fixture, the test file, the requirement,
   and `CLAUDE.md`) and adds this Pass 25 trigger note as input 25.
4. Re-uses the same 18-item Pass 24 verification checklist and adds a
   single new item 19 that documents the supervisor idempotency lockout
   discovery and the new-task-id unblock so Codex understands why the
   review is being re-issued under task id 045 rather than 042.
5. Tells Codex to emit blocks for the two new `25_*.md` and `26_*.md`
   files with the same one-line gate marker semantics as 07/08:
   `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS` or
   `PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL`.

The legacy `07_CODEX_REVIEW.md` and `08_CODEX_GO_NO_GO.md` files stay on
disk as a historical record of the pre-Pass-21 FAIL. The next planner
pass that wires `evidence_satisfied_requirements()` will read the new
`26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md` rather than the stale
`08_CODEX_GO_NO_GO.md`.

## 3. Pass 25 actions

Re-emit `claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json`
with the structure described in section 2.

Author this Pass 25 reconciliation note at
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/25_PASS25_REREVIEW_TRIGGER.md`.

No code module is touched. No fixture is touched. No test is touched.
No closure note 19-24 is touched. The Pass 21
`coinank_rows._classify_quote_kind` fix remains the single load-bearing
behavior change. Task 042's JSON and runtime state are not touched.

## 4. Out of scope

- No change to `v2/backend/app/domain/symbols/coinank_rows.py`.
- No change to `v2/backend/app/domain/symbols/normalization.py`.
- No change to `v2/backend/app/adapters/symbol_sources/coinank.py`.
- No change to `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`.
- No change to `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`.
- No change to `v2/legacy_preserved/ingestors/live_coinank.py`.
- No change to `legacy_reference/**`.
- No change to `/home/wali/Desktop/AI BOT/**`.
- No change to `claude_worklog/agent_supervisor/tasks/042_*.json`.
- No change to `claude_worklog/agent_supervisor/state/**` (the planner
  cannot write here; resetting 042's runtime state is intentionally not
  attempted, and is not required for the unblock).
- No change to `claude_worklog/phase2_core_rebuild/coinank_discovery_list/07_CODEX_REVIEW.md`
  or `08_CODEX_GO_NO_GO.md` (they remain as historical pre-Pass-21
  evidence; the Pass 25 trigger explicitly redirects the new gate marker
  to `26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`).
- No change to the planner master tool `evidence_satisfied_requirements()`
  (gated on Codex returning CODEX_PASS in the post-Pass-21 re-review;
  that wiring belongs to the next planner pass).
- No `.env` file is read or printed. No secret value is read or printed.
- No live API call. No Redis read, write, or delete. No exchange action.
- No leverage or margin change. No live-trading enablement.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed; ingesting the actual ODT into a real fixture remains a
  follow-up after REQ_0002 closes through the post-Pass-21 Codex
  re-review.

## 5. Operator validation steps after Pass 25 materializes

Run from `/home/wali/Desktop/AI BOT REBUILD`:

1. `python3 -m py_compile v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/domain/symbols/normalization.py v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: no output, exit 0.
2. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json > /dev/null`
   Expected: exit 0.
3. `python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0.
4. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: `11 passed`.
5. `python3 -c "import json; d=json.load(open('claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json')); assert d['task_id']=='045_codex_rereview_phase2_coinank_discovery_list_post_pass21'; assert d['status']=='pending'; assert d['risk_level']=='L1'; assert sorted(d['required_output_files'])==sorted(['claude_worklog/phase2_core_rebuild/coinank_discovery_list/25_CODEX_REREVIEW_AFTER_PASS21.md','claude_worklog/phase2_core_rebuild/coinank_discovery_list/26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md']); assert d['go_no_go_marker']=='PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS'; print('045 pass25 task ok')"`
   Expected: `045 pass25 task ok`.
6. `git status --short -- v2/legacy_preserved/ingestors/live_coinank.py legacy_reference claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json claude_worklog/phase2_core_rebuild/coinank_discovery_list/07_CODEX_REVIEW.md claude_worklog/phase2_core_rebuild/coinank_discovery_list/08_CODEX_GO_NO_GO.md`
   Expected: empty (none of these protected/historical files modified by Pass 25).

If steps 1 through 6 all pass, stage and commit Pass 21 + Pass 22 +
Pass 23 + Pass 24 + Pass 25 as one atomic Phase 2D closure:

- `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 21 BTCUSD_PERP fix)
- `v2/backend/app/domain/symbols/normalization.py` (Pass 19/20 cleanup)
- `v2/backend/app/adapters/symbol_sources/coinank.py` (Pass 19/20 cleanup)
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
  (entire Phase 2D evidence directory through Pass 25)
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  (Pass 24 re-arm task, untracked)
- `claude_worklog/agent_supervisor/tasks/045_codex_rereview_phase2_coinank_discovery_list_post_pass21.json`
  (Pass 25 re-review trigger task)

Suggested commit message:

    Phase 2D CoinAnk discovery list - passes 21 through 25 closure

    Pass 21 strips trailing _PERP or _NNNNNN dated suffix before
    quote-suffix classification in coinank_rows._classify_quote_kind so
    BTCUSD_PERP resolves to quote_kind=USD and is_perp_inverse=True,
    resolving the Codex finding in 07_CODEX_REVIEW.md. Passes 22 through
    24 stripped cosmetic END_FILE pollution and outer markdown fence
    wrappers from the Phase 2D artifact set so Codex reads a uniformly
    clean input set. Pass 25 unblocks the supervisor idempotency lockout
    on task 042 by emitting a fresh task 045 with new task_id and new
    required_output_files (25_CODEX_REREVIEW_AFTER_PASS21.md and
    26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md) so Codex actually
    re-evaluates the Pass 21 fixed module set against the synthetic
    fixture rather than short-circuiting on the stale pre-Pass-21
    07_CODEX_REVIEW.md and 08_CODEX_GO_NO_GO.md.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. No leverage or margin change. No live-trading enablement.
    v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT untouched.
    claude_worklog/agent_supervisor/state/** untouched.
    07_CODEX_REVIEW.md and 08_CODEX_GO_NO_GO.md preserved as historical
    pre-Pass-21 evidence.

Then push. The next planner cycle materializes Pass 25 + 045 and the
master rebuild planner's `run_generated_tasks` runs 045 because:

- 045 is materialized in the same planner cycle that emits it.
- 045's `status` field is `pending` and `risk_level` is `L1`, so
  `generated_task_ids` includes it.
- 045's required outputs `25_*.md` and `26_*.md` do not exist on disk,
  so the supervisor's idempotency check at agent_supervisor.py:2185-2188
  sees `existing_missing = ["25_*.md", "26_*.md"]` and falls through to
  the actual Codex execution branch.
- Codex reads the on-disk Pass 21 fixed `coinank_rows.py` (the working
  tree is the source of truth even when uncommitted), runs
  `pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`,
  observes `11 passed`, and emits the two new files.

## 6. Safety boundaries

- No live API calls.
- No Redis writes, reads, or deletes.
- No exchange-action paths.
- No leverage or margin change.
- No live-trading enablement.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- `.env` files and secret values are not read or printed.
- `claude_worklog/agent_supervisor/state/**` is not written by the
  planner; the new state file for task 045 is created by the supervisor
  itself when it first observes the new task definition.
- The historical `07_CODEX_REVIEW.md` and `08_CODEX_GO_NO_GO.md` are
  preserved as pre-Pass-21 evidence and explicitly out of scope for
  this pass.

## 7. Next planner action

After supervisor task 045 runs and emits `25_CODEX_REREVIEW_AFTER_PASS21.md`
plus `26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`:

If `26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md` contains
`PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`:

- The next planner pass extends `evidence_satisfied_requirements()` in
  `claude_worklog/tools/claude_master_rebuild_planner.py` with a marker
  check on
  `claude_worklog/phase2_core_rebuild/coinank_discovery_list/26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md`
  containing `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, mapping
  `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
  `phase2_coinank_discovery_list_codex_pass_post_pass21`. That single
  edit is the only change in that planner pass.
- The follow-up planner pass opens REQ_0004 trainer GPU parity scoping
  under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` with an
  initial scope, function index plan, GPU/CUDA preservation policy, and
  Tier A review plan that explicitly does not mutate the protected
  trainer venv and does not import legacy trainer into the V2 FastAPI
  process.
- A subsequent planner pass authors a non-live trainer subprocess
  adapter contract (input fixtures, output schema, freshness flags,
  worker health telemetry) and a Codex review task for the contract,
  with no GPU code or model code change.

If `26_CODEX_REREVIEW_GO_NO_GO_AFTER_PASS21.md` contains
`PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` with a finding that touches
only artifacts under `claude_worklog/` or non-live modules under `v2/`,
the next planner pass emits a single targeted remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` and does
not advance to REQ_0004.

Any fail demanding modification of
`v2/legacy_preserved/ingestors/live_coinank.py`, `legacy_reference/**`,
secrets, Redis, the exchange path, leverage or margin, or
`/home/wali/Desktop/AI BOT/**` is a hard stop and is escalated to human
review.

PHASE2_COINANK_DISCOVERY_LIST_PASS25_READY
