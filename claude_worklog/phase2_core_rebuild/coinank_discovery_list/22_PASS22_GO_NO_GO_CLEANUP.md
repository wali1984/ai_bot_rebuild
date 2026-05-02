# Phase 2D CoinAnk Discovery List - Pass 22 GO/NO-GO Artifact Cleanup

## 1. Decision

Pass 22 is an artifact-only cleanup. It strips cosmetic pollution from
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md`
so that the Phase 2D input set Codex re-reads under supervisor task
`042_codex_review_phase2_coinank_discovery_list` contains only the
single-line marker the planner harness expects:

    PHASE2_COINANK_DISCOVERY_LIST_READY_FOR_CODEX_REVIEW

No code module is touched. No fixture is touched. No test is touched.
No supervisor task JSON is touched. The Pass 21
`coinank_rows._classify_quote_kind` fix remains the load-bearing
behavior change for the BTCUSD_PERP quote classification.

## 2. Root cause of the polluted GO/NO-GO

The original `06_GO_NO_GO.md` was materialized by an earlier planner
emission that left two artifacts inside the file body:

1. A literal `END_FILE: claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md`
   line that should have been a sentinel consumed by the harness, not
   committed content.
2. Two stray triple-backtick fenced-code markers below the END_FILE
   line.

Pass 19 and Pass 20 stripped the same class of pollution from the four
reviewed `.py` files but never touched `06_GO_NO_GO.md` because the
file still parsed as plain text and was outside the
`python -m py_compile` validation surface. Codex review pass 1 still
read the polluted body when forming the Phase 2D context, but the
single-line marker on line 1 was sufficient for the gate to remain
declared "ready for Codex review" and the failure recorded in
`07_CODEX_REVIEW.md` was the BTCUSD_PERP quote-classification finding,
not the cosmetic pollution.

Pass 22 removes the pollution proactively before the post-Pass-21
Codex re-run so that the re-emitted `07_CODEX_REVIEW.md` cannot be
contaminated by stray markers in the input set.

## 3. Pass 22 actions

Re-emit `06_GO_NO_GO.md` as exactly one line:

    PHASE2_COINANK_DISCOVERY_LIST_READY_FOR_CODEX_REVIEW

Author this Pass 22 reconciliation note at
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/22_PASS22_GO_NO_GO_CLEANUP.md`.

No other file under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` is
modified by this pass.

No file under `v2/` is modified by this pass.

The supervisor task at
`claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
is not modified by this pass. Its existing input list already references
`21_REMEDIATION_BTCUSD_PERP_QUOTE_FIX.md`, and Codex will pick up
`22_PASS22_GO_NO_GO_CLEANUP.md` as part of the same Phase 2D directory
the prompt asks Codex to review.

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

## 5. Operator validation steps after Pass 22 materializes

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
   Expected: `1 ...` (one line, single-line marker, no trailing
   `END_FILE:` or fenced-code pollution).
6. `head -n 1 claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md`
   Expected: `PHASE2_COINANK_DISCOVERY_LIST_READY_FOR_CODEX_REVIEW`.
7. `git status --short -- v2/legacy_preserved/ingestors/live_coinank.py legacy_reference`
   Expected: empty.

If steps 1 through 7 all pass, stage and commit Pass 21 + Pass 22 as
one atomic Phase 2D closure:

- `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 21 BTCUSD_PERP
  quote fix)
- `v2/backend/app/domain/symbols/normalization.py` (existing Pass 19/20
  cleanup, currently uncommitted)
- `v2/backend/app/adapters/symbol_sources/coinank.py` (existing Pass
  19/20 cleanup, currently uncommitted)
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
  (synthetic fixture, untracked)
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
  (fixture-only test suite, untracked)
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` (entire
  Phase 2D evidence directory, untracked)
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  (Codex re-arm task, untracked)

Suggested commit message:

    Phase 2D CoinAnk discovery list - passes 21 and 22 closure

    Pass 21 strips trailing _PERP or _NNNNNN dated suffix before
    quote-suffix classification in coinank_rows._classify_quote_kind so
    BTCUSD_PERP resolves to quote_kind=USD and is_perp_inverse=True,
    resolving the Codex finding in 07_CODEX_REVIEW.md. Pass 22 removes
    cosmetic END_FILE and fenced-code pollution from 06_GO_NO_GO.md so
    the post-Pass-21 Codex re-run reads a clean Phase 2D input set.

    Re-arms supervisor task 042 with the cleaned artifact set and the
    21_REMEDIATION_BTCUSD_PERP_QUOTE_FIX.md plus 22_PASS22_GO_NO_GO_CLEANUP.md
    notes in its evidence list.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. No leverage or margin change. No live-trading enablement.
    v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT untouched.

Then push. Supervisor task 042 re-runs Codex against the cleaned
artifact set plus the Pass 21 fixed module.

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

After the operator commits and pushes the Pass 21 + Pass 22 file set,
supervisor task `042_codex_review_phase2_coinank_discovery_list` re-runs
Codex. Codex re-reads the Phase 2D scope (now including the Pass 21 and
Pass 22 closure notes), re-runs `pytest`, and emits `07_CODEX_REVIEW.md`
plus `08_CODEX_GO_NO_GO.md`.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`:

- The next planner pass records REQ_0002 as evidence-satisfied via a
  marker check on `08_CODEX_GO_NO_GO.md` containing
  `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS` and moves the requirement
  from `claude_worklog/requirements_inbox/` into the processed evidence
  index.
- The next planner pass opens REQ_0004 trainer GPU parity scoping under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` with an
  initial scope, function index plan, GPU/CUDA preservation policy, and
  Tier A review plan that explicitly does not mutate the protected
  trainer venv and does not import legacy trainer into the V2 FastAPI
  process.
- A follow-up planner pass authors a non-live trainer subprocess
  adapter contract (input fixtures, output schema, freshness flags,
  worker health telemetry) and a Codex review task for the contract,
  with no GPU code or model code change.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` with a
finding that touches only artifacts under `claude_worklog/` or non-live
modules under `v2/`, the next planner pass emits a single targeted
remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` and does
not advance to REQ_0004.

Any fail demanding modification of
`v2/legacy_preserved/ingestors/live_coinank.py`, `legacy_reference/**`,
secrets, Redis, the exchange path, leverage or margin, or
`/home/wali/Desktop/AI BOT/**` is a hard stop and is escalated to human
review.

PHASE2_COINANK_DISCOVERY_LIST_PASS22_READY
