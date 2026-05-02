# Phase 2D CoinAnk Discovery List - Remediation Re-Emit Log (12)

Pass 12 is a focused materialization pass. Pass 11 documented the cleanup plan
but its support tools never landed on disk. Pass 12 lands the two missing
tools and lets the strip script clean every leaked `END_FILE:` marker in
place. No re-emission of the six already-on-disk artifacts is required —
they are byte-correct except for the trailing `END_FILE: <path>` line that
the harness leaks during materialization, and the strip script removes
exactly that line.

## Verified state at start of pass 12

Direct file reads confirmed the following pollution survived pass 11:

- `v2/backend/app/adapters/symbol_sources/coinank.py` — last line is
  `END_FILE: v2/backend/app/adapters/symbol_sources/coinank.py`. Compiles
  silently because of `from __future__ import annotations`.
- `v2/backend/app/domain/symbols/coinank_rows.py` — same pattern.
- `v2/backend/app/domain/symbols/normalization.py` — same pattern.
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py` — same
  pattern.
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
  — last line is `END_FILE: ...`, breaks `python -m json.tool` parse.
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  — last line is `END_FILE: ...`, breaks `python -m json.tool` parse, which
  blocks supervisor task 042 from running until cleaned.
- The seven markdown docs `00_SCOPE.md` through `11_REMEDIATION_REEMIT_LOG.md`
  under `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` carry
  trailing `END_FILE:` lines plus, in some cases, stray markdown fence noise.
  Parse-tolerant but cosmetically polluted.

Tools missing from disk at start of pass 12:

- `tools/strip_planner_end_markers.sh`
- `tools/coinank_uploaded_list_to_fixture.py`

Confirmed by `ls tools/` returning no match for either name.

## Pass 12 actions

1. Emit `tools/strip_planner_end_markers.sh`. The script truncates each
   allowlisted file at the first line equal to `END_FILE: <that path>`,
   using `awk` exact-string compare. The allowlist contains every
   currently-known polluted file, the two new tool files, and this very
   pass-12 log so future runs of the script remain idempotent. The script
   ends with an explicit `exit 0` so any leaked tail line is unreachable
   even on first run before self-cleanup.
2. Emit `tools/coinank_uploaded_list_to_fixture.py`. Stdlib-only ODT
   reader. Uses `zipfile` and `xml.etree.ElementTree`. No imports of
   `requests`, `urllib`, `socket`, `aiohttp`, or any network module.
   Starts with `from __future__ import annotations` so any leaked
   `END_FILE:` line is parsed as a stringified module-level annotation
   and is a no-op at import time.
3. Emit this `12_REMEDIATION_REEMIT_LOG.md` so the audit trail records
   why pass 12 was needed and how the operator validates and commits.

No other artifact under `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
is re-emitted. No `v2/backend/**` artifact is re-emitted. No
`legacy_reference/**` is touched. No `v2/legacy_preserved/ingestors/live_coinank.py`
is touched.

## Operator validation steps (run from repo root, in order)

1. `bash tools/strip_planner_end_markers.sh`
   Expected output: a `stripped: <path>` line for every previously polluted
   file, then `strip_planner_end_markers: cleaned N file(s)`.
2. `python3 -m py_compile v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/app/domain/symbols/normalization.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py tools/coinank_uploaded_list_to_fixture.py`
   Expected: no output, exit 0.
3. `python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0.
4. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
   Expected: exit 0.
5. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: 10 passed.
6. (Optional, only when the user wants the real fixture)
   `python3 tools/coinank_uploaded_list_to_fixture.py /home/wali/Downloads/coinanksymbols.odt v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list.json`
   The `.odt` itself is not committed. The generated `coinank_uploaded_list.json`
   may be committed only after a manual review confirming no Chinese-name
   symbol leaks into the auto-eligible set, no stock-like base appears in any
   `candidate_for_usdm_confirmation=true` row, and no symbol with `expireAt > 0`
   is treated as a perpetual.

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
        claude_worklog/phase2_core_rebuild/coinank_discovery_list/12_REMEDIATION_REEMIT_LOG.md
```

Commit message suggestion:

```
Phase 2D CoinAnk discovery list - pass 12 strip + ODT converter

Lands tools/strip_planner_end_markers.sh and tools/coinank_uploaded_list_to_fixture.py.
Cleans leaked planner END_FILE markers from the seven Phase 2D artifacts and the
two JSON files that were blocking supervisor task 042.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
```

Then push and re-trigger supervisor task `042_codex_review_phase2_coinank_discovery_list`.

## Safety boundaries

- No live API calls. No Redis writes or deletes. No exchange-action paths.
- The strip script uses `awk` exact-string compare against a fixed allowlist
  and only truncates at a path-specific `END_FILE:` line. No globbing, no
  recursive descent, no deletion of any file.
- The ODT converter performs no network I/O. Only `zipfile` and
  `xml.etree.ElementTree` are imported; both are stdlib.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed. No secret value is read or printed.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not committed.
  Only the generated `coinank_uploaded_list.json` may be committed, after
  manual review.

## Next planner action

After supervisor task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`,
the planner moves `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
`claude_worklog/requirements_inbox/processed/` and advances to
`REQ_0004_TRAINER_GPU_PARITY.md`. If task 042 returns a fail, the planner
emits a new remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` only and does
not advance to REQ_0004.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_12_READY
END_FILE: claude_worklog/phase2_core_rebuild/coinank_discovery_list/12_REMEDIATION_REEMIT_LOG.md
