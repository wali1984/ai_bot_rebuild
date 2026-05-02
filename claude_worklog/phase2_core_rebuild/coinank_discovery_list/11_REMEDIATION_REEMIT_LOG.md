# Phase 2D CoinAnk Discovery List - Remediation Re-Emit Log (11)

Third remediation pass on Phase 2D CoinAnk artifacts.

## Why a third pass

Passes 06b and 10 documented the planner-output marker leak and described two
support tools, but materialization of those passes preserved a trailing
`END_FILE: <path>` line inside the body of every emitted file, and the two
support tools never landed on disk.

Observed pollution at start of pass 11 (verified by direct read):

- `v2/backend/app/adapters/symbol_sources/coinank.py` - trailing in-body marker.
- `v2/backend/app/domain/symbols/coinank_rows.py` - trailing in-body marker.
- `v2/backend/app/domain/symbols/normalization.py` - trailing in-body marker.
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` - trailing in-body marker.
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json` - trailing in-body marker, breaks JSON parse.
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json` - trailing in-body marker, breaks JSON parse.
- 7 markdown docs under `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` - trailing in-body marker plus stray markdown fence garbage. Parse-tolerant but cosmetically polluted.

Tools missing from disk at start of pass 11:

- `tools/strip_planner_end_markers.sh`
- `tools/coinank_uploaded_list_to_fixture.py`

Confirmed by Python files compiling (because `from __future__ import annotations` makes the leaked line evaluate as a stringified annotation), JSON files failing to parse, and `ls tools/` returning no match for either tool.

## Pass 11 actions

1. Emit `tools/strip_planner_end_markers.sh` with no internal `END_FILE: ` lines and no surrounding markdown fence. Allowlist covers all 19 known polluted paths plus the script and converter themselves so any future leak gets cleaned in place.
2. Emit `tools/coinank_uploaded_list_to_fixture.py` (stdlib-only ODT to JSON; no `requests`, `urllib`, `socket`, `aiohttp`).
3. Re-emit the two broken JSON files clean (synthetic fixture, supervisor task 042).
4. Re-emit the three Python modules and the test module clean. Each module retains `from __future__ import annotations` as a defense-in-depth against any future leak.
5. Operator runs `bash tools/strip_planner_end_markers.sh` once after materialization to clean the 7 markdown docs that pass 11 does not re-emit.

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
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/11_REMEDIATION_REEMIT_LOG.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/00_SCOPE.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/01_RAW_ROW_SCHEMA.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/02_NORMALIZATION_RULES.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/03_DISCOVERY_ALIAS_POLICY.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/04_UPLOADED_LIST_SOURCE_INVENTORY.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/05_TEST_PLAN.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/06b_REMEDIATION_NOTE.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/09_REMEDIATION_VALIDATION_PLAN.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/10_REMEDIATION_REEMIT_LOG.md
```

Then push and re-trigger supervisor task `042_codex_review_phase2_coinank_discovery_list`.

## Safety boundaries

- No live API calls. No Redis writes. No exchange-action paths.
- The strip script only deletes lines matching `^END_FILE: ` from a fixed allowlist; no other mutations.
- The ODT converter performs no network I/O; only stdlib `zipfile` and `xml.etree.ElementTree` are used.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- No secrets are read or printed.

## Next planner action

After supervisor task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, the planner moves `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to `claude_worklog/requirements_inbox/processed/` and advances to `REQ_0004_TRAINER_GPU_PARITY.md`. If 042 fails, the planner emits a new remediation note and updated test/code blocks under `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` only.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_11_READY
END_FILE: claude_worklog/phase2_core_rebuild/coinank_discovery_list/11_REMEDIATION_REEMIT_LOG.md
