# Phase 2D CoinAnk Discovery List - Remediation Note (06b)

This note documents a planner-output marker leak in the prior emission of Phase 2D
artifacts and the remediation steps applied before Codex review (task 042).

## Defect

Several materialized files in the Phase 2D batch carry a stray trailing line of the
form `END_FILE: <path>` inside the file body. This is a planner-output policy
artifact that the harness was supposed to treat as a delimiter and strip on
materialization, but did not.

Affected files and severity:

- `v2/backend/app/domain/symbols/coinank_rows.py` - has `from __future__ import annotations`
  at top, so the leaked line parses as a stringified variable annotation. The module
  imports without raising. Functionally tolerated, must still be cleaned.
- `v2/backend/app/adapters/symbol_sources/coinank.py` - same pattern. Tolerated.
- `v2/backend/app/domain/symbols/normalization.py` - same pattern. Tolerated.
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` - was missing
  `from __future__ import annotations`, so the leaked line evaluates `END_FILE: <expr>`
  as a runtime variable annotation, and `<expr>` (a slash-separated path) raises
  NameError on the first identifier (`v2`). HARD BREAK on import. Fix: add
  `from __future__ import annotations` and remove the trailing line.
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json` -
  trailing `END_FILE` after the closing `}` makes the file invalid JSON. HARD
  BREAK on parse. Fix: remove the trailing line.
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  - same JSON parse breakage; the supervisor cannot ingest the task. HARD BREAK.
  Fix: remove the trailing line.
- 7 markdown documents under `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
  (`00_SCOPE.md`, `01_RAW_ROW_SCHEMA.md`, `02_NORMALIZATION_RULES.md`,
  `03_DISCOVERY_ALIAS_POLICY.md`, `04_UPLOADED_LIST_SOURCE_INVENTORY.md`,
  `05_TEST_PLAN.md`, `06_GO_NO_GO.md`). Markdown tolerates trailing lines; functional
  impact is none, but pollution should be cleaned for hygiene.

## Missing artifact

`tools/coinank_uploaded_list_to_fixture.py` is referenced in
`04_UPLOADED_LIST_SOURCE_INVENTORY.md` and supervisor task 042's input list but did
not exist on disk. Added in this remediation as a stdlib-only ODT-to-JSON
converter that performs no network I/O and preserves raw row values verbatim.

## Remediation actions

1. Re-emit corrected versions of the 5 affected `v2/` files (no `END_FILE` line in
   body). The test file additionally gains `from __future__ import annotations`
   for resilience against any future leak.
2. Add `tools/coinank_uploaded_list_to_fixture.py` (stdlib-only, sandbox-safe).
3. Add `tools/strip_planner_end_markers.sh` as a defensive idempotent cleaner that
   scans a fixed allowlist of paths and removes any line matching `^END_FILE: `.
4. Update supervisor task 042 to (a) reference the actual REQ_0002 inbox path,
   (b) include the new tool inputs, (c) add verify items for marker hygiene
   (`python -m py_compile`, `python -m json.tool`).
5. Operator follows `09_REMEDIATION_VALIDATION_PLAN.md` to validate, commit, and
   re-trigger task 042.

## Safety boundaries

- No live API calls.
- No Redis writes.
- No exchange-action paths exercised.
- No mutation of `legacy_reference/**`.
- No mutation of `v2/legacy_preserved/ingestors/live_coinank.py`.
- No secrets read or printed.
- Strip script only deletes lines matching the regex `^END_FILE: ` from a fixed
  allowlist; no other mutations.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_06B_READY
