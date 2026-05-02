# Phase 2D CoinAnk Discovery List - Remediation Final Closure (Pass 19)

## 1. Decision

Pass 19 closes the remediation re-emit loop. Passes 10 through 18 attempted to
land cleanup tools and re-emit polluted files but every prior pass appended
its own `END_FILE: <path>` line as the last line of every emitted file
because the planner emitted a path-suffixed closer (`END_FILE: <path>`)
instead of the bare closer (`END_FILE`) the materializer regex actually
recognises.

Pass 19 stops re-emitting files we cannot safely re-emit, fixes only the
two pollution sites that break parsing, narrows supervisor task 042 to the
files actually on disk, and documents the cosmetic remainder so the
operator can clean it in a single shell loop.

## 2. Root cause

`claude_worklog/tools/claude_master_rebuild_planner.py` runs
`safe_materialize_blocks(stdout)` which calls `parse_begin_file_blocks`.
Its strict regex is

```
^BEGIN_FILE:?\s*(.*?)\n(.*?)\nEND_FILE\s*$
```

The closer must be a line whose only content is `END_FILE` (optional
trailing whitespace). `END_FILE: <path>` does not match. The fallback
regex slices content between successive `BEGIN_FILE:` markers and only
strips a trailing bare `END_FILE`. When the closer was
`END_FILE: <path>`, the fallback never stripped it, so the path-suffixed
closer was written into the file as content.

Every Phase 2D pass from 10 through 17 used the path-suffixed closer.
Pass 18 was truncated by the harness mid-emit and produced a 5-line stub.
Pass 19 uses the bare closer and confines emission to files that actually
need fixing.

## 3. Pass 19 actions

1. Re-emit
   `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
   without the leaked path-suffixed closer line. The previous file ended
   with `END_FILE: v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
   after the closing `}`, breaking `python -m json.tool`. The re-emitted
   file ends with `}` and is valid JSON. The 8 synthetic rows
   (binance_usdm_candidate_btc_perp, binance_usdm_candidate_eth_perp,
   coinm_inverse_perp_must_not_collapse, dated_quarterly_must_not_collapse,
   usdc_pair_separate_from_usdt, ethbtc_must_not_be_usdm,
   stock_like_must_not_auto_eligible,
   chinese_name_preserved_requires_confirmation) are unchanged.

2. Re-emit
   `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
   without the leaked path-suffixed closer line and with two prompt
   updates:

   - The input file list no longer references
     `tools/coinank_uploaded_list_to_fixture.py` or
     `tools/strip_planner_end_markers.sh`. Pass 16 designed both, pass 17
     re-emitted both, and the materializer refused both because `tools/`
     is not in `ALLOWED_MATERIALIZE_PREFIXES`. They are not on disk and
     are not required for REQ_0002 evidence: the synthetic fixture
     already covers all 8 policy cases the requirement names.
   - Verification items 12 and 15 (the two items that named the missing
     tools) are removed. Item 13 from the previous prompt becomes new
     item 12, narrowed to "all four reviewed .py files parse via
     `python -m py_compile`" plus an explicit acknowledgement that
     harmless leaked annotation lines documented in this closure are not
     blocking. Item 14 from the previous prompt becomes new item 13,
     scoped to the two JSON files we actually fixed in this pass.

3. Emit this `19_REMEDIATION_FINAL_CLOSURE.md`. No other Phase 2D
   markdown is re-emitted. No `v2/backend/**` artifact is re-emitted.
   No `legacy_reference/**`, `v2/legacy_preserved/ingestors/live_coinank.py`,
   or `/home/wali/Desktop/AI BOT/**` is touched.

## 4. Cosmetic remainder

The following files still carry a single trailing
`END_FILE: <path>` annotation from prior passes. None of them break
parsing or runtime; they are cosmetic only and explicitly acknowledged
by supervisor task 042's verification item 12.

Source files (parse silently because each opens with
`from __future__ import annotations`, which makes the leaked line
parse as a stringified module-level annotation that is never evaluated):

- `v2/backend/app/adapters/symbol_sources/coinank.py`
- `v2/backend/app/domain/symbols/coinank_rows.py`
- `v2/backend/app/domain/symbols/normalization.py`
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`

Markdown logs (text noise only, no parser involved):

- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/00_SCOPE.md`
- `01_RAW_ROW_SCHEMA.md`, `02_NORMALIZATION_RULES.md`,
  `03_DISCOVERY_ALIAS_POLICY.md`,
  `04_UPLOADED_LIST_SOURCE_INVENTORY.md`, `05_TEST_PLAN.md`,
  `06_GO_NO_GO.md`, `06b_REMEDIATION_NOTE.md`,
  `09_REMEDIATION_VALIDATION_PLAN.md`,
  `10_REMEDIATION_REEMIT_LOG.md`, `11_REMEDIATION_REEMIT_LOG.md`,
  `12_REMEDIATION_REEMIT_LOG.md`, `13_REMEDIATION_REEMIT_LOG.md`,
  `14_REMEDIATION_REEMIT_LOG.md`, `16_REMEDIATION_REEMIT_LOG.md`,
  `17_REMEDIATION_REEMIT_LOG.md`.

Stale planner output files (already-committed leftovers from a prior
planner cycle, not under any Phase 2D scope):

- `claude_worklog/agent_supervisor/planner/HUMAN_ACTION_REQUIRED.md`
- `claude_worklog/agent_supervisor/planner/NEXT_TASKS.json`
- `claude_worklog/agent_supervisor/planner/PLANNER_DECISION.md`
- `claude_worklog/agent_supervisor/planner/PLANNER_GO_NO_GO.md`

These four sit outside `ALLOWED_MATERIALIZE_PREFIXES` (the planner output
prefix is `claude_worklog/agent_supervisor/planner/`, not
`claude_worklog/agent_supervisor/tasks/`) and so cannot be cleaned via
the planner channel. They do not block any Phase 2D gate.

## 5. Operator cosmetic-cleanup procedure (optional, run only after pass 19 lands)

Pass 19 does not require cleanup of the cosmetic remainder before
supervisor task 042 runs. If the operator chooses to clean the remainder
manually after task 042 returns PASS, the safe procedure is:

```bash
# Run from /home/wali/Desktop/AI BOT REBUILD
for path in \
  v2/backend/app/adapters/symbol_sources/coinank.py \
  v2/backend/app/domain/symbols/coinank_rows.py \
  v2/backend/app/domain/symbols/normalization.py \
  v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py \
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
  claude_worklog/phase2_core_rebuild/coinank_discovery_list/13_REMEDIATION_REEMIT_LOG.md \
  claude_worklog/phase2_core_rebuild/coinank_discovery_list/14_REMEDIATION_REEMIT_LOG.md \
  claude_worklog/phase2_core_rebuild/coinank_discovery_list/16_REMEDIATION_REEMIT_LOG.md \
  claude_worklog/phase2_core_rebuild/coinank_discovery_list/17_REMEDIATION_REEMIT_LOG.md \
  claude_worklog/agent_supervisor/planner/HUMAN_ACTION_REQUIRED.md \
  claude_worklog/agent_supervisor/planner/NEXT_TASKS.json \
  claude_worklog/agent_supervisor/planner/PLANNER_DECISION.md \
  claude_worklog/agent_supervisor/planner/PLANNER_GO_NO_GO.md
do
  if [ -f "$path" ] && [ "$(tail -n 1 "$path")" = "END_FILE: $path" ]; then
    tmp=$(mktemp "$path.strip.XXXXXX")
    head -n -1 "$path" > "$tmp"
    mv "$tmp" "$path"
    echo "stripped: $path"
  fi
done
```

This loop is a one-liner deliberately not landed as a permanent script,
because `tools/` is outside the planner allowlist and the cleanup is a
single-shot. It is allowlist-only (each path is named explicitly), it
strips a line only when that line is exactly `END_FILE: <that-same-path>`,
and it makes no network call, no Redis call, no exchange call.

## 6. Operator validation steps after pass 19 materializes

Run from `/home/wali/Desktop/AI BOT REBUILD`:

1. `python3 -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null`
   Expected: exit 0.
2. `python3 -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null`
   Expected: exit 0.
3. `python3 -m py_compile v2/backend/app/adapters/symbol_sources/coinank.py v2/backend/app/domain/symbols/coinank_rows.py v2/backend/app/domain/symbols/normalization.py v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: no output, exit 0.
4. `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
   Expected: 11 passed.

If all four pass, stage and commit:

- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/19_REMEDIATION_FINAL_CLOSURE.md`
- the four `v2/backend/**` artifacts already on disk
  (coinank.py, coinank_rows.py, normalization.py,
  test_coinank_uploaded_list.py) - these still carry the cosmetic
  END_FILE annotation but are functionally correct
- the seventeen Phase 2D markdown logs already on disk

Suggested commit message:

    Phase 2D CoinAnk discovery list - pass 19 closes remediation loop

    Re-emits the two JSON files broken by leaked planner sentinel lines:
    coinank_uploaded_list_synthetic.json and supervisor task
    042_codex_review_phase2_coinank_discovery_list.json. Updates task
    042 prompt to drop references to tools/* files that the
    materializer cannot land (allowlist excludes tools/) and to
    explicitly acknowledge the cosmetic END_FILE annotation in the
    four reviewed .py files. Adds 19_REMEDIATION_FINAL_CLOSURE.md
    documenting root cause, scope, and operator cleanup procedure.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT
    untouched.

Then push and re-arm supervisor task
`042_codex_review_phase2_coinank_discovery_list`.

## 7. Safety boundaries

- No live API calls. No Redis writes or deletes. No exchange-action
  paths. No leverage or margin change. No live-trading enablement.
- The optional cosmetic-cleanup loop in section 5 uses an exact-string
  compare against an explicit allowlist and only truncates at a
  path-specific `END_FILE:` line. No globbing. No recursive descent.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed. No secret value is read or
  printed.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed. Importing the user's actual ODT into a real fixture is
  deferred to a follow-up requirement once REQ_0002 closes.

## 8. Next planner action

After steps 1-4 in section 6 pass and the operator commits and pushes,
supervisor task `042_codex_review_phase2_coinank_discovery_list` runs
with parseable JSON inputs and a prompt scoped to files that exist.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, the
planner moves `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
`claude_worklog/requirements_inbox/processed/` and advances to
`REQ_0004_TRAINER_GPU_PARITY.md`.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` with
remediation that touches only artifacts under `claude_worklog/` or
`v2/`, the planner emits a single targeted remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` and does
not advance to REQ_0004. Any fail that demands modification of
`v2/legacy_preserved/ingestors/live_coinank.py`, `legacy_reference/**`,
secrets, Redis, the exchange path, leverage or margin, or
`/home/wali/Desktop/AI BOT/**` is a hard stop and is escalated to
human review.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_19_READY
