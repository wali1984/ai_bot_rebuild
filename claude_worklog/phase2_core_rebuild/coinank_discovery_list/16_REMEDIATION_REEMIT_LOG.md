# Phase 2D CoinAnk Discovery List - Remediation Re-Emit Log (16)

Pass 15 emitted only a 137-byte stub. Pass 16 actually materializes
the two support tools that pass 14 designed and re-arms the strip
allowlist to also cover this log.

## Verified state at start of pass 16

A direct `ls tools/` shows that neither
`tools/strip_planner_end_markers.sh` nor
`tools/coinank_uploaded_list_to_fixture.py` exists.

The following artifacts still carry a trailing `END_FILE: <path>` line
that must be stripped:

- `v2/backend/app/adapters/symbol_sources/coinank.py` (line 50).
- `v2/backend/app/domain/symbols/coinank_rows.py` (line 218).
- `v2/backend/app/domain/symbols/normalization.py` (line 219).
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
  (line 152).
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
  (line 79; breaks JSON parse).
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  (line 32; breaks JSON parse and blocks supervisor task 042).
- The 14 markdown docs `00_SCOPE.md`, `01_RAW_ROW_SCHEMA.md`,
  `02_NORMALIZATION_RULES.md`, `03_DISCOVERY_ALIAS_POLICY.md`,
  `04_UPLOADED_LIST_SOURCE_INVENTORY.md`, `05_TEST_PLAN.md`,
  `06_GO_NO_GO.md`, `06b_REMEDIATION_NOTE.md`,
  `09_REMEDIATION_VALIDATION_PLAN.md`,
  `10_REMEDIATION_REEMIT_LOG.md` through
  `14_REMEDIATION_REEMIT_LOG.md` under
  `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` carry
  trailing `END_FILE:` lines plus stray triple-backtick fence noise.
- `15_REMEDIATION_REEMIT_LOG.md` is a 137-byte truncated stub. It is
  consistent with the other Phase 2D markdown docs and is included in
  the strip allowlist for completeness.

The four polluted Python modules still compile silently because each
one starts with `from __future__ import annotations`, which causes the
leaked `END_FILE: <path>` line to parse as a stringified module-level
annotation. The two JSON files do not have that escape hatch and
currently fail `python3 -m json.tool`.

The user-supplied source `/home/wali/Downloads/coinanksymbols.odt` is
not committed and is read only by the operator-invoked converter step.

## Pass 16 actions

1. Emit `tools/strip_planner_end_markers.sh`. Behavior:
   - Re-execs itself from a `mktemp` copy on first invocation. The
     re-exec is gated by `STRIP_PLANNER_REEXEC=1` so the second
     invocation runs the work loop. This guarantees we never read a
     script we are about to truncate.
   - Holds a fixed allowlist of paths. No globbing. No recursion. No
     descent into other directories. Its own path is the last entry
     in the allowlist.
   - For each allowlisted path, runs `awk` with an exact-string
     comparison against the marker `END_FILE: <that-path>`, writes
     the truncated content to a sibling `.strip_planner_end_markers.tmp`
     file, compares with `cmp -s`, and atomically `mv` over the
     original only when the content changed.
   - Prints `stripped: <path>` for each modified file and a final
     `strip_planner_end_markers: cleaned N file(s)` summary, then
     `exit 0`.
   - Performs no destructive operation other than truncate-at-marker.
     Never deletes a file outside its own tmp copies. Never writes
     outside the allowlist. Never contacts the network. Never touches
     Redis. Never touches the legacy bot. Never restarts a service.
     Never enables live trading.
2. Emit `tools/coinank_uploaded_list_to_fixture.py`. Behavior:
   - Imports only stdlib: `json`, `sys`, `xml.etree.ElementTree`,
     `zipfile`, `pathlib`, `typing`. No `requests`, `urllib`,
     `socket`, `aiohttp`, or any other network module.
   - Reads the ODT as a zip and parses `content.xml`.
   - Walks every `<table:table>`, treats the first non-empty
     `<table:table-row>` as the header, and emits each subsequent row
     as a `dict` keyed by the header.
   - Coerces `expireAt` and `updateAt` to `int` when present and
     numeric. Leaves all other fields as raw strings. Preserves
     Chinese-name symbols verbatim because UTF-8 round-trips end to
     end and `ensure_ascii=False` is set on JSON output.
   - Writes a JSON document with `source`, `source_path`, `row_count`,
     `rows` keys to the requested output path.
   - The unconditional `raise SystemExit(main(sys.argv))` at the end
     of the `if __name__ == "__main__":` guard means any leaked
     `END_FILE:` line is never executed when the script runs as a
     CLI. `from __future__ import annotations` provides
     defense-in-depth when the module is imported.
3. Emit this `16_REMEDIATION_REEMIT_LOG.md`. The strip allowlist
   includes this log so the strip script self-cleans it on first run.

No other artifact under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` is
re-emitted in pass 16. No `v2/backend/**` artifact is re-emitted. No
`legacy_reference/**` is touched. No
`v2/legacy_preserved/ingestors/live_coinank.py` is touched.

## Operator validation steps (run from repo root, in order)

All steps run as the `wali` user, from the V2 control plane venv where
applicable, against the local working copy only. Nothing in this list
contacts a live exchange, writes Redis, restarts a service, places or
cancels an order, changes leverage or margin, or enables live trading.

1. `bash tools/strip_planner_end_markers.sh`
   Expected output: a `stripped: <path>` line for every previously
   polluted file (including the two new tool files and this log
   itself), then `strip_planner_end_markers: cleaned N file(s)`. N is
   at least 23 on the first run after pass 16.
2. `python3 -m py_compile v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/app/domain/symbols/normalization.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py tools/coinank_uploaded_list_to_fixture.py`
   Expected: no output, exit 0.
3. `python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0.
4. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
   Expected: exit 0.
5. `bash -n tools/strip_planner_end_markers.sh`
   Expected: no output, exit 0.
6. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: 11 passed.
7. (Optional, only when the user wants the real fixture from the
   user-supplied ODT.)
   `python3 tools/coinank_uploaded_list_to_fixture.py /home/wali/Downloads/coinanksymbols.odt v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list.json`
   The `.odt` itself is not committed. The generated
   `coinank_uploaded_list.json` may be committed only after a manual
   review confirming no Chinese-name symbol leaks into the
   auto-eligible set, no stock-like base appears in any
   `candidate_for_usdm_confirmation=true` row, and no symbol with
   `expireAt > 0` is treated as a perpetual.

## Stage and commit (only after steps 1-6 pass)

Suggested staged paths:

- `tools/strip_planner_end_markers.sh`
- `tools/coinank_uploaded_list_to_fixture.py`
- `v2/backend/app/adapters/symbol_sources/coinank.py`
- `v2/backend/app/domain/symbols/coinank_rows.py`
- `v2/backend/app/domain/symbols/normalization.py`
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
- All 16 Phase 2D markdown docs in
  `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
  (`00_SCOPE.md`, `01_RAW_ROW_SCHEMA.md`, `02_NORMALIZATION_RULES.md`,
  `03_DISCOVERY_ALIAS_POLICY.md`,
  `04_UPLOADED_LIST_SOURCE_INVENTORY.md`, `05_TEST_PLAN.md`,
  `06_GO_NO_GO.md`, `06b_REMEDIATION_NOTE.md`,
  `09_REMEDIATION_VALIDATION_PLAN.md`,
  `10_REMEDIATION_REEMIT_LOG.md`, `11_REMEDIATION_REEMIT_LOG.md`,
  `12_REMEDIATION_REEMIT_LOG.md`, `13_REMEDIATION_REEMIT_LOG.md`,
  `14_REMEDIATION_REEMIT_LOG.md`, `15_REMEDIATION_REEMIT_LOG.md`,
  `16_REMEDIATION_REEMIT_LOG.md`).

Suggested commit message:

    Phase 2D CoinAnk discovery list - pass 16 land strip + ODT converter tools

    Lands tools/strip_planner_end_markers.sh and
    tools/coinank_uploaded_list_to_fixture.py that passes 14 and 15
    documented but the harness never materialized. The strip script
    cleans the leaked planner END_FILE markers from the 6 v2/backend
    artifacts, the supervisor task 042 JSON, and the 16 Phase 2D
    markdown docs in a single run.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. v2/legacy_preserved/ingestors/live_coinank.py is not
    touched. legacy_reference/** is not touched. /home/wali/Desktop/AI
    BOT is not touched. The user-supplied
    /home/wali/Downloads/coinanksymbols.odt is not committed.

Then push and re-arm supervisor task
`042_codex_review_phase2_coinank_discovery_list`.

## Safety boundaries

- No live API calls. No Redis writes or deletes. No exchange-action
  paths. No leverage or margin change. No live-trading enablement.
- The strip script uses `awk` exact-string compare against a fixed
  allowlist and only truncates at a path-specific `END_FILE:` line.
  No globbing. No recursive descent. No deletion of any file outside
  its own `.strip_planner_end_markers.tmp` and `mktemp` self-copy.
- The ODT converter performs no network I/O. Only `json`, `sys`,
  `xml.etree.ElementTree`, `zipfile`, `pathlib`, `typing` are
  imported; all stdlib.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed. No secret value is read or
  printed.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed. Only the generated `coinank_uploaded_list.json` may be
  committed, after manual review per REQ_0002.

## Next planner action

After steps 1-6 pass and the operator commits and pushes, supervisor
task `042_codex_review_phase2_coinank_discovery_list` is ready to run
with a parseable JSON definition and a clean, non-polluted set of
inputs.

After supervisor task 042 returns
`PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, the planner moves
`REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
`claude_worklog/requirements_inbox/processed/` and advances to
`REQ_0004_TRAINER_GPU_PARITY.md`.

If 042 returns a fail, the planner emits a new remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` only and
does not advance to REQ_0004.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_16_READY
END_FILE: claude_worklog/phase2_core_rebuild/coinank_discovery_list/16_REMEDIATION_REEMIT_LOG.md
