# Phase 2D CoinAnk Discovery List - Pass 23 Codex Re-Arm

## 1. Decision

Pass 23 observes that Pass 21 and Pass 22 are materialized on disk and ready
for Codex re-review. The planner re-arms supervisor task 042 by re-emitting
its JSON with `22_PASS22_GO_NO_GO_CLEANUP.md` and this Pass 23 note added to
the explicit Codex input list, and refreshes the prompt sentence that names
the load-bearing remediation to acknowledge Pass 21 (code), Pass 22
(artifact cleanup), and Pass 23 (task-input cleanup). No code module is
touched. No fixture is touched. No test is touched. No commit is performed
by this planner pass; the operator commits Pass 21 + Pass 22 + Pass 23 as
one Phase 2D closure before the supervisor re-runs Codex.

## 2. State observed by Pass 23

- `v2/backend/app/domain/symbols/coinank_rows.py`: `_classify_quote_kind`
  strips trailing `_PERP` and `_NNNNNN` before quote-suffix classification
  (Pass 21).
- `v2/backend/app/domain/symbols/normalization.py`: Pass 19/20 cosmetic
  cleanup applied; module compiles cleanly under `python -m py_compile`.
- `v2/backend/app/adapters/symbol_sources/coinank.py`: Pass 19/20 cosmetic
  cleanup applied; module compiles cleanly under `python -m py_compile`.
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`:
  synthetic fixture present and parses under `python -m json.tool`.
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`:
  11-test suite present.
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md`:
  exactly one line `PHASE2_COINANK_DISCOVERY_LIST_READY_FOR_CODEX_REVIEW`
  (Pass 22).
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/21_REMEDIATION_BTCUSD_PERP_QUOTE_FIX.md`:
  Pass 21 closure note.
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/22_PASS22_GO_NO_GO_CLEANUP.md`:
  Pass 22 closure note.
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`:
  pending L1 Codex re-review task; before Pass 23 its explicit input list
  ended at `21_REMEDIATION_BTCUSD_PERP_QUOTE_FIX.md`.

## 3. Pass 23 actions

Re-emit `042_codex_review_phase2_coinank_discovery_list.json` with two
additions and no other behavior change:

1. Add `22_PASS22_GO_NO_GO_CLEANUP.md` and `23_PASS23_CODEX_REARM.md` to the
   explicit Codex input file list so Codex consumes the Pass 22 cosmetic
   cleanup decision and this Pass 23 task-input refresh as part of its
   Phase 2D review context.
2. Refresh the first prompt sentence to read "after the Pass 21 BTCUSD_PERP
   quote-classification fix and the Pass 22 / Pass 23 cosmetic and
   task-input cleanup" so Codex understands all three load-bearing closure
   passes are in scope.

The `task_id`, `agent`, `risk_level`, `cwd`, `emit_files`,
`allowed_output_prefixes`, `required_output_files`, `depends_on`,
`max_attempts`, `priority`, `auto_commit`, `status`, `phase2_requirements`,
and `go_no_go_marker` fields are byte-identical to the pre-Pass-23 emission
of 042. The verification checklist in the prompt body adds two new items
(Pass 22 single-line gate marker, Pass 23 task-input refresh) but does not
remove any prior verification item.

Author this Pass 23 reconciliation note at
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/23_PASS23_CODEX_REARM.md`.

No other file under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` is modified by
this pass.

No file under `v2/` is modified by this pass.

## 4. Out of scope

- No change to `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 21
  remains the load-bearing fix for BTCUSD_PERP).
- No change to `v2/backend/app/domain/symbols/normalization.py`.
- No change to `v2/backend/app/adapters/symbol_sources/coinank.py`.
- No change to `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`.
- No change to `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`.
- No change to `v2/legacy_preserved/ingestors/live_coinank.py`.
- No change to `legacy_reference/**`.
- No change to `/home/wali/Desktop/AI BOT/**`.
- No `.env` file is read or printed. No secret value is read or printed.
- No live API call. No Redis read, write, or delete. No exchange action.
- No leverage or margin change. No live-trading enablement.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed; ingesting the actual ODT into a real fixture remains a
  follow-up after REQ_0002 closes through Codex review.

## 5. Operator validation steps after Pass 23 materializes

Run from `/home/wali/Desktop/AI BOT REBUILD`:

1. `python3 -m py_compile v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/domain/symbols/normalization.py v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: no output, exit 0.
2. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
   Expected: exit 0.
3. `python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0.
4. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: `11 passed`.
5. `wc -l claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md`
   Expected: `1 ...`.
6. `head -n 1 claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md`
   Expected: `PHASE2_COINANK_DISCOVERY_LIST_READY_FOR_CODEX_REVIEW`.
7. `git status --short -- v2/legacy_preserved/ingestors/live_coinank.py legacy_reference`
   Expected: empty.
8. `python3 -c "import json,sys; d=json.load(open('claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json')); assert '22_PASS22_GO_NO_GO_CLEANUP.md' in d['prompt'] and '23_PASS23_CODEX_REARM.md' in d['prompt'], 'pass 23 input refresh missing'; print('042 pass23 input refresh ok')"`
   Expected: `042 pass23 input refresh ok`.

If steps 1 through 8 all pass, stage and commit Pass 21 + Pass 22 + Pass 23
as one atomic Phase 2D closure:

- `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 21 BTCUSD_PERP quote
  fix)
- `v2/backend/app/domain/symbols/normalization.py` (existing Pass 19/20
  cleanup, currently uncommitted)
- `v2/backend/app/adapters/symbol_sources/coinank.py` (existing Pass 19/20
  cleanup, currently uncommitted)
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
  (synthetic fixture, untracked)
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
  (fixture-only test suite, untracked)
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` (entire
  Phase 2D evidence directory, untracked)
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  (Codex re-arm task, untracked)

Suggested commit message:

    Phase 2D CoinAnk discovery list - passes 21, 22, and 23 closure

    Pass 21 strips trailing _PERP or _NNNNNN dated suffix before
    quote-suffix classification in coinank_rows._classify_quote_kind so
    BTCUSD_PERP resolves to quote_kind=USD and is_perp_inverse=True,
    resolving the Codex finding in 07_CODEX_REVIEW.md. Pass 22 removes
    cosmetic trailing markers from 06_GO_NO_GO.md so the gate marker file
    is exactly one line. Pass 23 re-arms supervisor task 042 with
    22_PASS22_GO_NO_GO_CLEANUP.md and 23_PASS23_CODEX_REARM.md added to
    the explicit Codex input list and the prompt refreshed to acknowledge
    all three closure passes.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. No leverage or margin change. No live-trading enablement.
    v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT untouched.

Then push. Supervisor task 042 re-runs Codex against the cleaned artifact
set plus the Pass 21 fixed module.

## 6. Safety boundaries

- No live API calls.
- No Redis writes, reads, or deletes.
- No exchange-action paths.
- No leverage or margin change.
- No live-trading enablement.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed.
- No secret value is read or printed.

## 7. Next planner action

After the operator commits and pushes the Pass 21 + Pass 22 + Pass 23 file
set, supervisor task `042_codex_review_phase2_coinank_discovery_list`
re-runs Codex. Codex re-reads the cleaned Phase 2D scope, re-runs `pytest`,
and emits `07_CODEX_REVIEW.md` plus `08_CODEX_GO_NO_GO.md`.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`:

- The next planner pass extends `evidence_satisfied_requirements()` in
  `claude_worklog/tools/claude_master_rebuild_planner.py` with a marker
  check on
  `claude_worklog/phase2_core_rebuild/coinank_discovery_list/08_CODEX_GO_NO_GO.md`
  containing `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, mapping
  `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
  `phase2_coinank_discovery_list_codex_pass`. That single edit is the only
  change in that planner pass.
- The follow-up planner pass opens REQ_0004 trainer GPU parity scoping
  under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` with an
  initial scope, function index plan, GPU/CUDA preservation policy, and
  Tier A review plan that explicitly does not mutate the protected trainer
  venv and does not import legacy trainer into the V2 FastAPI process.
- A subsequent planner pass authors a non-live trainer subprocess adapter
  contract (input fixtures, output schema, freshness flags, worker health
  telemetry) and a Codex review task for the contract, with no GPU code or
  model code change.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` with a
finding that touches only artifacts under `claude_worklog/` or non-live
modules under `v2/`, the next planner pass emits a single targeted
remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` and does not
advance to REQ_0004.

Any fail demanding modification of
`v2/legacy_preserved/ingestors/live_coinank.py`, `legacy_reference/**`,
secrets, Redis, the exchange path, leverage or margin, or
`/home/wali/Desktop/AI BOT/**` is a hard stop and is escalated to human
review.

PHASE2_COINANK_DISCOVERY_LIST_PASS23_READY
