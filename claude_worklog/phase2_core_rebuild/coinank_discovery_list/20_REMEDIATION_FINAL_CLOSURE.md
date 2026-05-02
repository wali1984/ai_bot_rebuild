# Phase 2D CoinAnk Discovery List - Pass 20 Cosmetic Cleanup Closure

## 1. Decision

Pass 20 performs the cosmetic cleanup that Pass 19 deferred to an
operator shell loop. It re-emits the four `v2/backend/**` Python files
cleanly, stripping the trailing `END_FILE: <path>` annotation that
prior passes (10 through 17) leaked. The bare `END_FILE` closer is
now used consistently by the planner, so re-emission is safe and
deterministic, and the planner materializer regex
`^BEGIN_FILE:?\s*(.*?)\n(.*?)\nEND_FILE\s*$` accepts each file.

Pass 20 does not change any Python or test logic. It only removes a
single trailing annotation line from each of the four files.

## 2. Pass 20 actions

Re-emitted with the trailing leaked annotation removed (last line is
now the real terminating Python statement, not an annotation):

- `v2/backend/app/adapters/symbol_sources/coinank.py`
  (file shrinks from 50 lines to 49; new last line: `        return []`)
- `v2/backend/app/domain/symbols/coinank_rows.py`
  (file shrinks from 218 lines to 217; new last line: `    return None`)
- `v2/backend/app/domain/symbols/normalization.py`
  (file shrinks from 219 lines to 218; new last line: `    return "none"`)
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
  (file shrinks from 152 lines to 151; new last line:
  `    assert eth_btc_id not in confirmed`)

Functional contents are byte-identical to the on-disk Pass 19 versions
except for the removal of the single trailing
`END_FILE: <that-same-path>` line.

## 3. Out of scope (deliberately not re-emitted)

Markdown logs in `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
that carry the same trailing annotation are pure text noise; no parser
ever evaluates them, so they remain as documented cosmetic remainder
in Pass 19 section 4. Stale planner-output files under
`claude_worklog/agent_supervisor/planner/` are outside the
allowlisted materialize prefixes and remain untouched.

No `legacy_reference/**` is touched. No
`v2/legacy_preserved/ingestors/live_coinank.py` is touched. No
`/home/wali/Desktop/AI BOT/**` is touched. No `.env` is read or
written. No secret value is read or printed. No live API call is
issued. No Redis key is read, written, or deleted. No exchange action
is taken. No leverage or margin change is issued.

## 4. Operator validation steps after Pass 20 materializes

Run from `/home/wali/Desktop/AI BOT REBUILD`:

1. `python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0.
2. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
   Expected: exit 0.
3. `python3 -m py_compile v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/domain/symbols/normalization.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: no output, exit 0.
4. Tail check on each Python file - the last line must be real code,
   not an `END_FILE: <path>` annotation:
   - `tail -n 1 v2/backend/app/adapters/symbol_sources/coinank.py` => `        return []`
   - `tail -n 1 v2/backend/app/domain/symbols/coinank_rows.py` => `    return None`
   - `tail -n 1 v2/backend/app/domain/symbols/normalization.py` => `    return "none"`
   - `tail -n 1 v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` => `    assert eth_btc_id not in confirmed`
5. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: 11 passed.

If all five pass, stage and commit the Pass 19 + Pass 20 file set:

- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json` (Pass 19)
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json` (Pass 19)
- `v2/backend/app/adapters/symbol_sources/coinank.py` (Pass 20 cosmetic cleanup)
- `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 20 cosmetic cleanup)
- `v2/backend/app/domain/symbols/normalization.py` (Pass 20 cosmetic cleanup)
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` (Pass 20 cosmetic cleanup)
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/19_REMEDIATION_FINAL_CLOSURE.md` (Pass 19)
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/20_REMEDIATION_FINAL_CLOSURE.md` (Pass 20)
- the seventeen Phase 2D markdown logs already on disk (text-only
  cosmetic remainder that does not block parsing)

Suggested commit message:

    Phase 2D CoinAnk discovery list - pass 20 cosmetic cleanup

    Strips the trailing END_FILE: <path> annotation from the four
    v2/backend Python files emitted by passes 10-17 with the broken
    path-suffixed closer. Pass 19 acknowledged these as harmless
    cosmetic remainder under from __future__ import annotations and
    deferred cleanup to an operator shell loop; pass 20 performs the
    cleanup via planner re-emit using the bare END_FILE closer that
    the materializer regex accepts. No Python or test logic changes.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT
    untouched.

Then push. The supervisor will pick up
`042_codex_review_phase2_coinank_discovery_list` (status `pending`)
and run Codex against it.

## 5. Safety boundaries

- No live API calls.
- No Redis writes or deletes.
- No exchange-action paths.
- No leverage or margin change.
- No live-trading enablement.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed.
- No secret value is read or printed.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed. Importing the user's actual ODT into a real fixture is
  deferred to a follow-up requirement once REQ_0002 closes through
  Codex review.

## 6. Next planner action

After the operator commits and pushes the Pass 19 + Pass 20 file set,
supervisor task `042_codex_review_phase2_coinank_discovery_list` runs
Codex against the now-cleaner Phase 2D artifact set with parseable
JSON inputs and Python files free of the cosmetic trailing annotation.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, the
planner moves `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
`claude_worklog/requirements_inbox/processed/` and advances to
`REQ_0004_TRAINER_GPU_PARITY.md` (the next-highest-priority
requirement, given REQ_0003 `live_coinank.py` copy-as-is is already
honored by the untouched preserved ingestor and REQ_0005 startup
script runtime map source-of-truth is sequenced after trainer parity
in the master plan).

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` with
remediation that touches only artifacts under `claude_worklog/` or
`v2/`, the planner emits a single targeted remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` and does
not advance to REQ_0004. Any fail that demands modification of
`v2/legacy_preserved/ingestors/live_coinank.py`, `legacy_reference/**`,
secrets, Redis, the exchange path, leverage or margin, or
`/home/wali/Desktop/AI BOT/**` is a hard stop and is escalated to
human review.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_20_READY
