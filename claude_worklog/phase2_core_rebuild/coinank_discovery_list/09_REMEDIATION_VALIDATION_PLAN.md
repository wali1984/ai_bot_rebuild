# Phase 2D CoinAnk Discovery List - Remediation Validation Plan (09)

Operator-driven validation steps to run before re-triggering Codex review
(supervisor task 042).

## Steps (in order)

1. Strip any leaked planner end markers (idempotent):

       bash tools/strip_planner_end_markers.sh

2. Confirm Python files parse:

       python -m py_compile \
         v2/backend/app/domain/symbols/coinank_rows.py \
         v2/backend/app/adapters/symbol_sources/coinank.py \
         v2/backend/app/domain/symbols/normalization.py \
         v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py \
         tools/coinank_uploaded_list_to_fixture.py

3. Confirm JSON files parse:

       python -m json.tool < v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json > /dev/null
       python -m json.tool < claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json > /dev/null

4. Run unit tests against the synthetic fixture:

       PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py

5. (Optional, requires user-supplied ODT) Run the converter against the local
   upload to produce a fixture from the real list. Do not commit the `.odt`.

       python3 tools/coinank_uploaded_list_to_fixture.py \
         /home/wali/Downloads/coinanksymbols.odt \
         v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list.json

   Then spot-check the produced JSON against `01_RAW_ROW_SCHEMA.md`.

6. Stage and commit only after steps 1-4 pass:

       git add v2/backend/app/domain/symbols/coinank_rows.py \
               v2/backend/app/adapters/symbol_sources/coinank.py \
               v2/backend/app/domain/symbols/normalization.py \
               v2/backend/tests/unit/symbol_universe/test_coinank_uploaded_list.py \
               v2/backend/tests/fixtures/symbol_universe/coinank_uploaded_list_synthetic.json \
               tools/coinank_uploaded_list_to_fixture.py \
               tools/strip_planner_end_markers.sh \
               claude_worklog/phase2_core_rebuild/coinank_discovery_list/06b_REMEDIATION_NOTE.md \
               claude_worklog/phase2_core_rebuild/coinank_discovery_list/09_REMEDIATION_VALIDATION_PLAN.md \
               claude_worklog/agent_supervisor/tasks/042_codex_review_phase2_coinank_discovery_list.json
       git commit -m "Remediate Phase 2D CoinAnk planner marker leak; add ODT converter"

7. Push and re-trigger supervisor task `042_codex_review_phase2_coinank_discovery_list`.

## Safety boundaries

- No live API calls. No Redis writes. No exchange-action paths.
- Step 5 reads a file outside the repo root (`/home/wali/Downloads/coinanksymbols.odt`)
  but writes only into `v2/backend/tests/fixtures/symbol_universe/`.
- Step 1 only deletes lines matching `^END_FILE: ` from a fixed allowlist of
  paths; no other mutations.
- Step 6 stages explicit paths only; no `git add -A`.

PHASE2_COINANK_DISCOVERY_LIST_REMEDIATION_09_READY
