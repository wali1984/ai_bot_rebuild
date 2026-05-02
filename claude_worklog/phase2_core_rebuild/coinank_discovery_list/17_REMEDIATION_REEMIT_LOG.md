```
# Phase 2D CoinAnk Discovery List - Remediation Re-Emit Log (17)

Pass 16 designed two support tools but the harness never materialized them.
Pass 17 re-emits both tools and adds an extended cleanup scope.

## State observed at start of pass 17

A direct repo grep for `^END_FILE: ` confirms that 21 files in the working
tree carry leaked planner sentinel lines as their last content line:

- 5 v2/backend artifacts:
  - `v2/backend/app/adapters/symbol_sources/coinank.py` (line 50)
  - `v2/backend/app/domain/symbols/coinank_rows.py` (line 218)
  - `v2/backend/app/domain/symbols/normalization.py` (line 219)
  - `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` (line 152)
  - `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json` (line 79; breaks JSON parse)
- 1 supervisor task:
  - `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json` (line 32; breaks JSON parse and blocks supervisor task 042)
- 15 markdown docs in `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`:
  `00_SCOPE.md`, `01_RAW_ROW_SCHEMA.md`, `02_NORMALIZATION_RULES.md`,
  `03_DISCOVERY_ALIAS_POLICY.md`, `04_UPLOADED_LIST_SOURCE_INVENTORY.md`,
  `05_TEST_PLAN.md`, `06_GO_NO_GO.md`, `06b_REMEDIATION_NOTE.md`,
  `09_REMEDIATION_VALIDATION_PLAN.md`,
  `10_REMEDIATION_REEMIT_LOG.md`, `11_REMEDIATION_REEMIT_LOG.md`,
  `12_REMEDIATION_REEMIT_LOG.md`, `13_REMEDIATION_REEMIT_LOG.md`,
  `14_REMEDIATION_REEMIT_LOG.md`, `16_REMEDIATION_REEMIT_LOG.md`.

`15_REMEDIATION_REEMIT_LOG.md` is a 137-byte truncated stub from a failed
pass; it does not carry the END_FILE marker but is included in the strip
allowlist for completeness.

`tools/strip_planner_end_markers.sh` and
`tools/coinank_uploaded_list_to_fixture.py` do not exist on disk: a direct
`ls tools/` confirms.

`v2/legacy_preserved/ingestors/live_coinank.py` is clean (no END_FILE
pollution). `legacy_reference/**` is not touched by this pass.

The four polluted `.py` files compile silently because each opens with
`from __future__ import annotations`, which makes the leaked
`END_FILE: <path>` line parse as a stringified module-level annotation.
The two `.json` files are not so lucky and currently fail
`python3 -m json.tool`.

## Pass 17 actions

1. Emit `tools/strip_planner_end_markers.sh` with the same safety design
   pass 16 documented:
   - `set -eu` and a self-mktemp re-exec so the script can safely strip
     its own potential pollution.
   - A fixed string allowlist of 25 paths (the two new tools, the 5
     v2/backend artifacts, the 1 supervisor task, the 16 Phase 2D
     markdown docs including `15_REMEDIATION_REEMIT_LOG.md` and this
     `17_REMEDIATION_REEMIT_LOG.md`).
   - Per allowlisted path, runs `awk` with an exact-string compare
     against the marker `END_FILE: <that-path>`, writes the truncated
     content to a sibling `.strip_planner_end_markers.tmp`, compares
     with `cmp -s`, atomically `mv` over the original only when the
     content changed.
   - Prints `stripped: <path>` for each modified file and a final
     `strip_planner_end_markers: cleaned N file(s)` summary, then
     `exit 0`. Any END_FILE pollution after `exit 0` is unreachable.
   - No globbing. No recursion. No descent into other directories. No
     destructive operation other than truncate-at-marker.
   - No network I/O. No Redis writes or deletes. No exchange-action
     paths. No live-trading enablement.

2. Emit `tools/coinank_uploaded_list_to_fixture.py` per pass 16 design:
   - Imports only stdlib: `json`, `sys`, `xml.etree.ElementTree`,
     `zipfile`, `pathlib`, `typing`. No `requests`, `urllib`, `socket`,
     `aiohttp`, or any other network module.
   - Reads the ODT as a zip archive and parses `content.xml`.
   - Walks every `<table:table>`, treats the first non-empty
     `<table:table-row>` as the header, emits subsequent rows as a
     `dict` keyed by the header.
   - Coerces `expireAt` and `updateAt` to `int` when numeric. Leaves
     all other fields as raw strings. Preserves Chinese-name symbols
     verbatim because UTF-8 round-trips end to end and
     `ensure_ascii=False` is set on JSON output.
   - Writes a JSON document with `source`, `source_path`, `row_count`,
     `rows` keys to the requested output path.
   - The unconditional `raise SystemExit(main(sys.argv))` at the end of
     the `if __name__ == "__main__":` guard means any leaked END_FILE
     line is never executed when the script runs as a CLI.
     `from __future__ import annotations` provides defense-in-depth
     when the module is imported.

3. Emit this `17_REMEDIATION_REEMIT_LOG.md`. The strip allowlist
   includes this log so the strip script self-cleans it on first run.

No other artifact under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` is re-emitted
in pass 17. No `v2/backend/**` artifact is re-emitted. No
`legacy_reference/**` is touched. No
`v2/legacy_preserved/ingestors/live_coinank.py` is touched.

## Operator validation steps (run from repo root, in order)

All steps run as the `wali` user, from the V2 control plane venv where
applicable, against the local working copy only. Nothing in this list
contacts a live exchange, writes Redis, restarts a service, places or
cancels an order, changes leverage or margin, or enables live trading.

1. `chmod +x tools/strip_planner_end_markers.sh tools/coinank_uploaded_list_to_fixture.py`
2. `bash tools/strip_planner_end_markers.sh`
   Expected: a `stripped: <path>` line for every previously polluted
   file (including this log itself), then
   `strip_planner_end_markers: cleaned N file(s)` where N is at least
   21 on the first run.
3. `python3 -m py_compile v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/app/domain/symbols/normalization.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py tools/coinank_uploaded_list_to_fixture.py`
   Expected: no output, exit 0.
4. `python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0.
5. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
   Expected: exit 0.
6. `bash -n tools/strip_planner_end_markers.sh`
   Expected: no output, exit 0.
7. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: 11 passed.
8. (Optional) Convert the user-supplied ODT:
   `python3 tools/coinank_uploaded_list_to_fixture.py /home/wali/Downloads/coinanksymbols.odt v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list.json`
   The .odt itself is not committed. The generated
   `coinank_uploaded_list.json` may be committed only after a manual
   review confirming no Chinese-name symbol leaks into the
   auto-eligible set, no stock-like base appears in any
   `candidate_for_usdm_confirmation=true` row, and no symbol with
   `expireAt > 0` is treated as a perpetual.

## Stage and commit (only after steps 1-7 pass)

Suggested staged paths:

- `tools/strip_planner_end_markers.sh`
- `tools/coinank_uploaded_list_to_fixture.py`
- `v2/backend/app/adapters/symbol_sources/coinank.py`
- `v2/backend/app/domain/symbols/coinank_rows.py`
- `v2/backend/app/domain/symbols/normalization.py`
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
- The 17 Phase 2D markdown docs in
  `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
  (00 through 16, plus this 17_REMEDIATION_REEMIT_LOG.md).

Suggested commit message:

    Phase 2D CoinAnk discovery list - pass 17 land strip + ODT converter tools

    Materializes tools/strip_planner_end_markers.sh and
    tools/coinank_uploaded_list_to_fixture.py that pass 16 documented but
    the harness never wrote. Strips leaked planner END_FILE sentinel
    lines from the 5 v2/backend artifacts, the supervisor task 042 JSON,
    and the 16 Phase 2D markdown docs.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT untouched.
    The user-supplied /home/wali/Downloads/coinanksymbols.odt is not
    committed.

Then push and re-arm supervisor task
`042_codex_review_phase2_coinank_discovery_list`.

## Safety boundaries

- No live API calls. No Redis writes or deletes. No exchange-action paths.
  No leverage or margin change. No live-trading enablement.
- The strip script uses `awk` exact-string compare against a fixed
  allowlist and only truncates at a path-specific `END_FILE:` line. No
  globbing. No recursive descent. No deletion of any file outside its
  own `.strip_planner_end_markers.tmp` and `mktemp` self-copy.
- The ODT converter performs no network I/O. Only `json`, `sys`,
  `xml.etree.ElementTree`, `zipfile`, `pathlib`, `typing` are imported;
  all stdlib.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed. No secret value is read or printed.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed. Only the generated `coinank_uploaded_list.json` may be
  committed, after manual review per REQ_0002.

## Next planner action

After steps 1-7 pass and the operator commits and pushes, supervisor
task `042_codex_review_phase2_coinank_discovery_list` is ready to run
with parseable JSON inputs and a clean, non-polluted set of artifacts.

After supervisor task 042 returns
`PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, the planner moves
`REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
`claude_worklog/requirements_inbox/processed/` and advances to
`REQ_0004_TRAINER_GPU_PARITY.md`.

If 042 returns a fail, the planner emits a new remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` only and
does not advance to REQ_0004.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_17_READY
```
END_FILE: claude_worklog/phase2_core_rebuild/coinank_discovery_list/17_REMEDIATION_REEMIT_LOG.md

---

Pass-17 BEGIN_FILE blocks emitted above. Two new files (`tools/strip_planner_end_markers.sh`, `tools/coinank_uploaded_list_to_fixture.py`) and one log re-emission. The harness should materialize them; the strip script will then clean its own END_FILE pollution along with the 21 polluted files. Operator validation steps 1–7 are listed in the log; commit and re-arm task 042 follow after a green run.

Want me to `/schedule` an agent in 24h to verify the strip script ran cleanly, JSON parse passes, and supervisor task 042 returned `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`?
