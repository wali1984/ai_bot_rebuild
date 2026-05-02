# Phase 2D CoinAnk Discovery List - Remediation Re-Emit Log (10)

This log records the second remediation pass on Phase 2D CoinAnk artifacts.

## Why a second pass

The first remediation (06b) and validation plan (09) described the cleanup steps
and the two missing tools, but the planner-output materialization itself
re-introduced trailing `END_FILE: <path>` lines into the bodies of the affected
files, and the two tools described in 06b/09 were never written to disk:

- `tools/coinank_uploaded_list_to_fixture.py` - missing.
- `tools/strip_planner_end_markers.sh` - missing.

Six artifacts still carried in-body `END_FILE: ` pollution at re-emit time:

- `v2/backend/app/adapters/symbol_sources/coinank.py`
- `v2/backend/app/domain/symbols/coinank_rows.py`
- `v2/backend/app/domain/symbols/normalization.py`
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`

## Re-emit actions

1. Emit `tools/strip_planner_end_markers.sh` first so it is on disk regardless of
   whether subsequent files re-acquire any pollution. The script `exit 0`s early
   so any trailing leak is unreachable, and it only deletes lines matching the
   regex `^END_FILE: ` from a fixed allowlist of paths.
2. Emit `tools/coinank_uploaded_list_to_fixture.py` (stdlib-only ODT->JSON).
   No `requests`/`urllib.request`/`socket` use; only `zipfile` + `xml.etree`.
3. Re-emit the five `v2/` files clean. All Python files start with
   `from __future__ import annotations` so any future leaked `END_FILE: <path>`
   trailing line evaluates as a stringified annotation rather than a runtime
   `NameError` on `v2`.
4. Re-emit supervisor task 042 JSON clean and update its inputs list to include
   `10_REMEDIATION_REEMIT_LOG.md`.

## Operator validation steps (run from repo root)

1. `bash tools/strip_planner_end_markers.sh`
2. `python -m py_compile v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/app/domain/symbols/normalization.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py tools/coinank_uploaded_list_to_fixture.py`
3. `python -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
4. `python -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
5. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
6. (Optional) `python3 tools/coinank_uploaded_list_to_fixture.py /home/wali/Downloads/coinanksymbols.odt v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list.json` to materialize the real fixture from the user-supplied ODT. The `.odt` itself is not committed.

## Stage and commit (only after steps 1-5 pass)

```
git add tools/strip_planner_end_markers.sh \
        tools/coinank_uploaded_list_to_fixture.py \
        v2/backend/app/adapters/symbol_sources/coinank.py \
        v2/backend/app/domain/symbols/coinank_rows.py \
        v2/backend/app/domain/symbols/normalization.py \
        v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py \
        v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json \
        claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/10_REMEDIATION_REEMIT_LOG.md
```

Then push and re-trigger supervisor task `042_codex_review_phase2_coinank_discovery_list`.

## Safety boundaries

- No live API calls. No Redis writes. No exchange-action paths.
- The strip script only deletes lines matching `^END_FILE: ` from a fixed
  allowlist; no other mutations.
- The ODT converter performs no network I/O; it uses only stdlib `zipfile` and
  `xml.etree.ElementTree`.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- No secrets are read or printed.

## Next planner action

After supervisor task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`,
the planner moves `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
`claude_worklog/requirements_inbox/processed/` and advances to
`REQ_0004_TRAINER_GPU_PARITY.md`. If 042 fails, the planner emits a new
remediation note `11_REMEDIATION_NOTE.md` and updated test/code blocks under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` only.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_10_READY
END_FILE: claude_worklog/phase2_core_rebuild/coinank_discovery_list/10_REMEDIATION_REEMIT_LOG.md
