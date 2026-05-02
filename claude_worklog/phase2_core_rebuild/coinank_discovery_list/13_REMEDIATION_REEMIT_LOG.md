# Phase 2D CoinAnk Discovery List - Remediation Re-Emit Log (13)

Pass 13 lands the two support tools that pass 12 documented but the
harness never materialized. Pass 12's markdown log made it onto disk,
but `tools/strip_planner_end_markers.sh` and
`tools/coinank_uploaded_list_to_fixture.py` did not. A direct
`ls tools/` at the start of pass 13 confirmed both are still absent.

## Verified state at start of pass 13

`ls tools/` shows `tools/strip_planner_end_markers.sh` and
`tools/coinank_uploaded_list_to_fixture.py` are missing.

Direct file reads confirmed the planner-output `END_FILE: <path>`
marker still appears as the last line of every previously-emitted
Phase 2D file:

- `v2/backend/app/adapters/symbol_sources/coinank.py` (line 50).
- `v2/backend/app/domain/symbols/coinank_rows.py` (line 218).
- `v2/backend/app/domain/symbols/normalization.py` (line 219).
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` (line 152).
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json` (line 79; breaks JSON parse).
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json` (line 32; breaks JSON parse and blocks supervisor task 042).
- The 12 markdown docs `00_SCOPE.md` through `12_REMEDIATION_REEMIT_LOG.md`
  under `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
  carry trailing `END_FILE:` lines plus, in some cases, stray markdown
  fence noise. Parse-tolerant but cosmetically polluted.

The four polluted Python modules compile silently because each one
starts with `from __future__ import annotations`, which makes the
leaked `END_FILE: <path>` line parse as a stringified module-level
annotation. JSON files do not have that escape hatch and currently
fail `python3 -m json.tool`.

## Pass 13 actions

1. Emit `tools/strip_planner_end_markers.sh`. The script:
   - Targets a fixed allowlist (no globbing, no recursion).
   - For each allowlisted path, removes the first line that is exactly
     equal to `END_FILE: <that path>` and discards everything after it,
     using an `awk` exact-string compare and an atomic rename.
   - Ends with `exit 0`, so any `END_FILE:` line the harness leaks into
     the script body on first materialization is unreachable on first
     run.
   - Self-cleans on first run because the allowlist includes its own
     path. Subsequent runs are idempotent because the marker is gone.
   - Performs no destructive operation other than the truncate-at-marker.
2. Emit `tools/coinank_uploaded_list_to_fixture.py`. The script:
   - Imports only stdlib (`zipfile`, `xml.etree.ElementTree`, `json`,
     `sys`, `pathlib`). No `requests`, `urllib`, `socket`, `aiohttp`,
     or any other network module.
   - Reads the user-supplied ODT, walks every `<table:table>`, treats
     the first non-empty row as the header, and emits each subsequent
     row as a dict with keys taken from the header.
   - Coerces `expireAt` and `updateAt` to int when present, leaves all
     other fields as raw strings.
   - Writes a JSON document with `source`, `source_path`, `row_count`,
     `rows` keys to the requested output path.
   - The unconditional `raise SystemExit(main())` at the end of the
     `if __name__ == "__main__":` guard means any `END_FILE:` line
     leaked into the body is never executed when the script runs as
     a CLI. `from __future__ import annotations` provides
     defense-in-depth when the file is imported.
3. Emit this `13_REMEDIATION_REEMIT_LOG.md`. No other artifact under
   `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` is
   re-emitted. No `v2/backend/**` artifact is re-emitted. No
   `legacy_reference/**` is touched. No
   `v2/legacy_preserved/ingestors/live_coinank.py` is touched.

## Operator validation steps (run from repo root, in order)

1. `bash tools/strip_planner_end_markers.sh`
   Expected output: a `stripped: <path>` line for every previously
   polluted file (including the two new tool files and this log
   itself), then
   `strip_planner_end_markers: cleaned N file(s)`. N is at least 21
   on the first run after pass 13.
2. `python3 -m py_compile v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/app/domain/symbols/normalization.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py tools/coinank_uploaded_list_to_fixture.py`
   Expected: no output, exit 0.
3. `python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0.
4. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
   Expected: exit 0.
5. `bash -n tools/strip_planner_end_markers.sh`
   Expected: no output, exit 0.
6. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: 10 passed.
7. (Optional, only when the user wants the real fixture from the
   user-supplied ODT)
   `python3 tools/coinank_uploaded_list_to_fixture.py /home/wali/Downloads/coinanksymbols.odt v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list.json`
   The `.odt` itself is not committed. The generated
   `coinank_uploaded_list.json` may be committed only after a manual
   review confirming no Chinese-name symbol leaks into the
   auto-eligible set, no stock-like base appears in any
   `candidate_for_usdm_confirmation=true` row, and no symbol with
   `expireAt > 0` is treated as a perpetual.

## Stage and commit (only after steps 1-6 pass)

```
git add tools/strip_planner_end_markers.sh \
        tools/coinank_uploaded_list_to_fixture.py \
        v2/backend/app/adapters/symbol_sources/coinank.py \
        v2/backend/app/domain/symbols/coinank_rows.py \
        v2/backend/app/domain/symbols/normalization.py \
        v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py \
        v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json \
        claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/00_SCOPE.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/01_RAW_ROW_SCHEMA.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/02_NORMALIZATION_RULES.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/03_DISCOVERY_ALIAS_POLICY.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/04_UPLOADED_LIST_SOURCE_INVENTORY.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/05_TEST_PLAN.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/06b_REMEDIATION_NOTE.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/09_REMEDIATION_VALIDATION_PLAN.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/10_REMEDIATION_REEMIT_LOG.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/11_REMEDIATION_REEMIT_LOG.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/12_REMEDIATION_REEMIT_LOG.md \
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/13_REMEDIATION_REEMIT_LOG.md
```

Commit message suggestion:

```
Phase 2D CoinAnk discovery list - pass 13 land strip + ODT converter

Lands tools/strip_planner_end_markers.sh and
tools/coinank_uploaded_list_to_fixture.py that pass 12 documented
but the harness never materialized. Cleans the leaked planner
END_FILE markers from the 6 v2/backend artifacts, the supervisor
task 042 JSON, and the 13 Phase 2D markdown docs.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Then push and re-trigger supervisor task
`042_codex_review_phase2_coinank_discovery_list`.

## Safety boundaries

- No live API calls. No Redis writes or deletes. No exchange-action
  paths.
- The strip script uses `awk` exact-string compare against a fixed
  allowlist and only truncates at a path-specific `END_FILE:` line.
  No globbing. No recursive descent. No deletion of any file.
- The ODT converter performs no network I/O. Only `zipfile` and
  `xml.etree.ElementTree` are imported; both are stdlib.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed. No secret value is read or
  printed.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed. Only the generated `coinank_uploaded_list.json` may be
  committed, after manual review.

## Next planner action

After supervisor task 042 returns
`PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, the planner moves
`REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
`claude_worklog/requirements_inbox/processed/` and advances to
`REQ_0004_TRAINER_GPU_PARITY.md`. If 042 returns a fail, the planner
emits a new remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` only and
does not advance to REQ_0004.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_13_READY
END_FILE: claude_worklog/phase2_core_rebuild/coinank_discovery_list/13_REMEDIATION_REEMIT_LOG.md
