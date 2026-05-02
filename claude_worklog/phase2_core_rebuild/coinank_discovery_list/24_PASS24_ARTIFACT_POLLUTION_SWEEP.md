# Phase 2D CoinAnk Discovery List - Pass 24 Artifact Pollution Sweep

## 1. Decision

Pass 24 extends Pass 22's gate-marker cleanup to every remaining Codex-input
artifact under `claude_worklog/phase2_core_rebuild/coinank_discovery_list/`
that still carried the legacy planner pollution pattern of a trailing
`END_FILE: <path>` line plus stray fenced-code markers (and, in the 06b /
09 cases, a leaked outer ` ```markdown ` wrapper). Pass 22 deliberately
scoped to `06_GO_NO_GO.md` because that single file is the one the harness
inspects for the gate marker; Pass 24 widens that hygiene rule symmetrically
to every other file Codex reads under supervisor task 042 so the post
Pass 21 / Pass 22 / Pass 23 / Pass 24 Codex re-review consumes a uniformly
clean Phase 2D input set.

No code module is touched. No fixture is touched. No test is touched. The
Pass 21 `coinank_rows._classify_quote_kind` fix remains the single
load-bearing behavior change for the BTCUSD_PERP quote classification.

## 2. Files re-emitted by Pass 24

Each file is re-emitted with the prior body content preserved verbatim and
the trailing planner pollution stripped. The `06b` and `09` notes are also
unwrapped from their leaked outer ` ```markdown ` ... ` ``` ` fence pair so
that section headers render as Markdown rather than as the body of one big
fenced code block.

- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/00_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/01_RAW_ROW_SCHEMA.md`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/02_NORMALIZATION_RULES.md`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/03_DISCOVERY_ALIAS_POLICY.md`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/04_UPLOADED_LIST_SOURCE_INVENTORY.md`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/05_TEST_PLAN.md`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/06b_REMEDIATION_NOTE.md`
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/09_REMEDIATION_VALIDATION_PLAN.md`

The seven `PHASE2_COINANK_..._READY` semantic sentinels at the tail of each
file are preserved exactly. No section header is renamed. No requirement,
classification rule, identity construction rule, alias policy clause,
inventory entry, or test-plan item is altered. Only stripped-out pollution.

## 3. Files explicitly NOT touched by Pass 24

- `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 21 BTCUSD_PERP fix
  is canonical).
- `v2/backend/app/domain/symbols/normalization.py`.
- `v2/backend/app/adapters/symbol_sources/coinank.py`.
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`.
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`.
- `v2/legacy_preserved/ingestors/live_coinank.py`.
- `legacy_reference/**`.
- `/home/wali/Desktop/AI BOT/**`.
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/06_GO_NO_GO.md`
  (Pass 22 already produced the single-line gate marker).
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/19_REMEDIATION_FINAL_CLOSURE.md`
  through `23_PASS23_CODEX_REARM.md` (these were emitted with the corrected
  bare `END_FILE` closer and never carried the leaked path-suffixed line).
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/10_REMEDIATION_REEMIT_LOG.md`
  through `17_REMEDIATION_REEMIT_LOG.md` and `18_REMEDIATION_CLOSURE.md`
  (intermediate remediation logs not in supervisor task 042's Codex input
  list; their pollution is historical and out of scope for the Codex re-run).
- Any `.env`, secret, or credentials file. None is read or printed.
- Any Redis key, queue, or stream. None is read, written, or deleted.
- Any exchange path. No order placed or cancelled. No leverage or margin
  change. No live-trading enablement.

## 4. Pass 24 supervisor task 042 update

Re-emit `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
with two and only two semantic changes versus the Pass 23 emission:

1. Add `24_PASS24_ARTIFACT_POLLUTION_SWEEP.md` to the explicit Codex input
   file list so Codex consumes this Pass 24 closure note as part of its
   Phase 2D review context.
2. Refresh the first prompt sentence from
   `"after the Pass 21 BTCUSD_PERP quote-classification fix and the
   Pass 22 / Pass 23 cosmetic and task-input cleanup"` to
   `"after the Pass 21 BTCUSD_PERP quote-classification fix and the
   Pass 22 / Pass 23 / Pass 24 cosmetic and task-input cleanup"` so Codex
   understands all four load-bearing closure passes are in scope.
3. Append two new verification items to the end of the prompt's numbered
   checklist, preserving every prior item:
   - Item 17: `Pass 24 stripped the leaked trailing END_FILE: <path>
     pollution and stray outer ` ``` ` fence wrappers from
     00_SCOPE.md, 01_RAW_ROW_SCHEMA.md, 02_NORMALIZATION_RULES.md,
     03_DISCOVERY_ALIAS_POLICY.md, 04_UPLOADED_LIST_SOURCE_INVENTORY.md,
     05_TEST_PLAN.md, 06b_REMEDIATION_NOTE.md, and
     09_REMEDIATION_VALIDATION_PLAN.md so each of the eight files ends
     with its PHASE2_*_READY semantic sentinel and no trailing planner
     pollution.`
   - Item 18: `06b_REMEDIATION_NOTE.md and 09_REMEDIATION_VALIDATION_PLAN.md
     no longer wrap their entire body in a leaked outer ` ``` ` markdown
     fence, so their section headers render as Markdown headings.`

The `task_id`, `agent`, `risk_level`, `cwd`, `emit_files`,
`allowed_output_prefixes`, `required_output_files`, `depends_on`,
`max_attempts`, `priority`, `auto_commit`, `status`,
`phase2_requirements`, and `go_no_go_marker` fields are byte-identical to
the Pass 23 emission of 042.

## 5. Operator validation steps after Pass 24 materializes

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
   Expected: `1 ...`.
6. For each file in the Pass 24 sweep:

       grep -c "^END_FILE:" \
         claude_worklog/phase2_core_rebuild/coinank_discovery_list/00_SCOPE.md \
         claude_worklog/phase2_core_rebuild/coinank_discovery_list/01_RAW_ROW_SCHEMA.md \
         claude_worklog/phase2_core_rebuild/coinank_discovery_list/02_NORMALIZATION_RULES.md \
         claude_worklog/phase2_core_rebuild/coinank_discovery_list/03_DISCOVERY_ALIAS_POLICY.md \
         claude_worklog/phase2_core_rebuild/coinank_discovery_list/04_UPLOADED_LIST_SOURCE_INVENTORY.md \
         claude_worklog/phase2_core_rebuild/coinank_discovery_list/05_TEST_PLAN.md \
         claude_worklog/phase2_core_rebuild/coinank_discovery_list/06b_REMEDIATION_NOTE.md \
         claude_worklog/phase2_core_rebuild/coinank_discovery_list/09_REMEDIATION_VALIDATION_PLAN.md

   Expected: every file reports `0`.
7. `tail -n 1 claude_worklog/phase2_core_rebuild/coinank_discovery_list/00_SCOPE.md`
   Expected: `PHASE2_COINANK_DISCOVERY_LIST_SCOPE_READY`.
8. Repeat the `tail -n 1` check for `01`-`05`, `06b`, `09` and confirm each
   ends with its corresponding `PHASE2_COINANK_..._READY` sentinel.
9. `git status --short -- v2/legacy_preserved/ingestors/live_coinank.py legacy_reference`
   Expected: empty.
10. `python3 -c "import json; d=json.load(open('claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json')); assert '24_PASS24_ARTIFACT_POLLUTION_SWEEP.md' in d['prompt'], 'pass 24 input refresh missing'; print('042 pass24 input refresh ok')"`
    Expected: `042 pass24 input refresh ok`.

If steps 1 through 10 all pass, stage and commit Pass 21 + Pass 22 + Pass 23
+ Pass 24 as one atomic Phase 2D closure:

- `v2/backend/app/domain/symbols/coinank_rows.py` (Pass 21 BTCUSD_PERP fix)
- `v2/backend/app/domain/symbols/normalization.py` (existing 19/20 cleanup)
- `v2/backend/app/adapters/symbol_sources/coinank.py` (existing 19/20 cleanup)
- `v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json`
  (synthetic fixture, untracked)
- `v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py`
  (fixture-only test suite, untracked)
- `claude_worklog/phase2_core_rebuild/coinank_discovery_list/` (entire
  Phase 2D evidence directory, with the Pass 24 cleaned scope/rules notes)
- `claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json`
  (Codex re-arm task, refreshed by Pass 24)

Suggested commit message:

    Phase 2D CoinAnk discovery list - passes 21, 22, 23, and 24 closure

    Pass 21 strips trailing _PERP or _NNNNNN dated suffix before
    quote-suffix classification in coinank_rows._classify_quote_kind so
    BTCUSD_PERP resolves to quote_kind=USD and is_perp_inverse=True,
    resolving the Codex finding in 07_CODEX_REVIEW.md. Pass 22 reduces
    06_GO_NO_GO.md to its single-line gate marker. Pass 23 re-arms
    supervisor task 042 with the Pass 22 and Pass 23 notes added to the
    Codex input list. Pass 24 sweeps the leaked trailing END_FILE pollution
    and stray outer fence wrappers from 00_SCOPE.md, 01_RAW_ROW_SCHEMA.md,
    02_NORMALIZATION_RULES.md, 03_DISCOVERY_ALIAS_POLICY.md,
    04_UPLOADED_LIST_SOURCE_INVENTORY.md, 05_TEST_PLAN.md,
    06b_REMEDIATION_NOTE.md, and 09_REMEDIATION_VALIDATION_PLAN.md and
    refreshes supervisor task 042 to acknowledge the Pass 24 sweep.

    No live API calls. No Redis writes or deletes. No exchange-action
    paths. No leverage or margin change. No live-trading enablement.
    v2/legacy_preserved/ingestors/live_coinank.py untouched.
    legacy_reference/** untouched. /home/wali/Desktop/AI BOT untouched.

Then push. Supervisor task 042 re-runs Codex against the cleaned artifact
set plus the Pass 21 fixed module.

## 6. Safety boundaries

- No live API calls.
- No Redis reads, writes, or deletes.
- No exchange-action paths.
- No leverage or margin change.
- No live-trading enablement.
- `v2/legacy_preserved/ingestors/live_coinank.py` is not touched.
- `legacy_reference/**` is not touched.
- `/home/wali/Desktop/AI BOT/**` is not touched.
- No `.env` file is read or printed.
- No secret value is read or printed.
- The user-supplied `/home/wali/Downloads/coinanksymbols.odt` is not
  committed; ingesting the actual ODT into a real fixture remains a
  follow-up after REQ_0002 closes through Codex review.

## 7. Next planner action

After the operator commits and pushes the Pass 21 + Pass 22 + Pass 23 +
Pass 24 file set, supervisor task
`042_codex_review_phase2_coinank_discovery_list` re-runs Codex. Codex
re-reads the cleaned Phase 2D scope (now including this Pass 24 closure
note), re-runs `pytest`, and emits `07_CODEX_REVIEW.md` plus
`08_CODEX_GO_NO_GO.md`.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`:

- The next planner pass extends `evidence_satisfied_requirements()` in
  `claude_worklog/tools/claude_master_rebuild_planner.py` with a marker
  check on
  `claude_worklog/phase2_core_rebuild/coinank_discovery_list/08_CODEX_GO_NO_GO.md`
  containing `PHASE2_COINANK_DISCOVERY_LIST_CODEX_PASS`, mapping
  `REQ_0002_COINANK_UPLOADED_SYMBOL_LIST.md` to
  `phase2_coinank_discovery_list_codex_pass`. That single edit is the only
  change in that planner pass.
- The follow-up planner pass opens REQ_0004 trainer GPU parity scoping
  under `claude_worklog/phase2_core_rebuild/trainer_gpu_parity/` with an
  initial scope, function index plan, GPU/CUDA preservation policy, and
  Tier A review plan that explicitly does not mutate the protected
  trainer venv and does not import legacy trainer into the V2 FastAPI
  process.
- A subsequent planner pass authors a non-live trainer subprocess adapter
  contract (input fixtures, output schema, freshness flags, worker health
  telemetry) and a Codex review task for the contract, with no GPU code
  or model code change.

If task 042 returns `PHASE2_COINANK_DISCOVERY_LIST_CODEX_FAIL` with a
finding that touches only artifacts under `claude_worklog/` or non-live
modules under `v2/`, the next planner pass emits a single targeted
remediation note under
`claude_worklog/phase2_core_rebuild/coinank_discovery_list/` and does not
advance to REQ_0004.

Any fail demanding modification of
`v2/legacy_preserved/ingestors/live_coinank.py`, `legacy_reference/**`,
secrets, Redis, the exchange path, leverage or margin, or
`/home/wali/Desktop/AI BOT/**` is a hard stop and is escalated to human
review.

PHASE2_COINANK_DISCOVERY_LIST_PASS24_READY
