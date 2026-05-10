# Planner Turn 2Y — Task 195 Dispatch-Hold Extension After Codex Parallel Review Batch 20260510_020600

## Decision

Extend the Phase 2Y task 195 dispatch-hold commit scope to cover the full
seven-subject Codex parallel read-only review batch
`claude_worklog/codex_parallel_reviews/20260510_020600_*` (subjects 01, 02,
03, 04, 05, 08, 09 — fourteen artifacts in total) plus task 195 itself, in
addition to the four Phase 2Y documentation artifacts (08–11) and the
`_fixtures.py` byte change already named in
`PLANNER_TURN_2Y_CODEX_AUTOFIX_VALIDATED_AND_TASK_195_AUTHORED.md` § "Watchdog
dispatch-hold contract".

No change to task 195's `worktree_excluded_paths`, `forbidden_actions`,
`required_output_files`, or `next_gate`. The Codex re-review of Phase 2Y
still dispatches as authored once the worktree is clean per
`requires_clean_worktree: true`.

## Why this extension is needed

The prior planner turn at
`claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Y_CODEX_AUTOFIX_VALIDATED_AND_TASK_195_AUTHORED.md`
listed the dispatch-hold scope at the moment task 195 was authored. At that
point only two Codex parallel review subjects were dirty
(`20260510_020600_01_trainer_prediction_output` and
`20260510_020600_02_orchestrator_decision`, four files). Between that turn
and the present turn:

- Commit `5419427 Create Codex parallel review batch` added nine task
  definitions for the parallel-review batch under
  `claude_worklog/agent_supervisor/tasks/codex_parallel_review_20260510_020600_*.json`
  covering subjects 01, 02, 03, 04, 05, 07, 08, 09, 10.
- The Codex parallel watchdog lane subsequently executed five more of those
  read-only reviews (subjects 03, 04, 05, 08, 09), each emitting a `_REPORT.md`
  and a `_GO_NO_GO.md` under `claude_worklog/codex_parallel_reviews/`.
- Task 195 itself was authored to disk at
  `claude_worklog/agent_supervisor/tasks/195_phase2y_provenance_dedupe_attribution_domain_codex_rereview_after_autofix.json`
  during the prior planner turn and remains untracked.

Per REQ_0011 § "Allowed Codex parallel scope", REQ_0021 § "Scheduling rules",
and REQ_0025 § "Read-only review tasks", the
`claude_worklog/codex_parallel_reviews/` directory is the approved isolated
report path for parallel review output. None of these reports modify `v2/`,
task definitions, the planner/supervisor code, or active dirty files; they
only describe the safety/freshness/typed-contract posture of already-committed
milestones (trainer prediction output, orchestrator decision, risk gateway
default-deny, paper execution ledger, replay/backtest runner, historical PnL
integration, and website explainability contracts). They are durable
non-live artifacts and the watchdog must commit them before task 195
dispatches.

## Updated dispatch-hold commit scope

Before task 195 dispatches, the Codex watchdog (per REQ_0016 § "Operating
loop", REQ_0021 § "If Claude child is inactive and Git is dirty", and
REQ_0014 § "Authority granted") commits the following nineteen paths in a
single commit titled `Codex watchdog recover dirty non-live automation
artifacts`:

- `v2/backend/tests/unit/domain/provenance_dedupe_attribution/_fixtures.py`
- `claude_worklog/agent_supervisor/tasks/195_phase2y_provenance_dedupe_attribution_domain_codex_rereview_after_autofix.json`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/08_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_REVIEW.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/09_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_GO_NO_GO.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/10_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_AUTOFIX.md`
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/11_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_AUTOFIX_VALIDATION_GO_NO_GO.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_01_trainer_prediction_output_GO_NO_GO.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_01_trainer_prediction_output_REPORT.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_02_orchestrator_decision_GO_NO_GO.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_02_orchestrator_decision_REPORT.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_03_risk_gateway_default_deny_GO_NO_GO.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_03_risk_gateway_default_deny_REPORT.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_04_paper_execution_ledger_GO_NO_GO.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_04_paper_execution_ledger_REPORT.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_05_replay_backtest_runner_GO_NO_GO.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_05_replay_backtest_runner_REPORT.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_08_historical_pnl_integration_GO_NO_GO.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_08_historical_pnl_integration_REPORT.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_09_website_explainability_contracts_GO_NO_GO.md`
- `claude_worklog/codex_parallel_reviews/20260510_020600_09_website_explainability_contracts_REPORT.md`

Three operator-managed dirty paths remain in `worktree_excluded_paths` for
this dispatch and are not committed by the watchdog:

- `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`
  (single-line tracker edit per Planner Turn 2L).
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Y_CODEX_AUTOFIX_VALIDATED_AND_TASK_195_AUTHORED.md`
  (prior planner-turn note authored by Planner Turn 2Y).
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Y_CODEX_AUTOFIX_VALIDATED_AND_TASK_195_DISPATCH_HOLD_EXTENDED.md`
  (this planner-turn note).

Task 195's `worktree_excluded_paths` array (lines 20–23 of the task JSON)
already names the first two operator-managed paths. This third
operator-managed path follows the identical convention and the operator
commits it separately, mirroring the established Phase 2X / Phase 2Y open-turn
pattern. Because task 195's `worktree_excluded_paths` array currently lists
only two paths, the operator must either commit this turn note before task
195 dispatches (preferred, single commit titled `Add Phase 2Y dispatch-hold
extension planner-turn note`), or the supervisor must extend
`worktree_excluded_paths` to three paths before dispatch — the planner
recommends the operator-commit-first path because it preserves task 195's
on-disk contract verbatim.

## Evidence consulted

- `claude_worklog/agent_supervisor/tasks/195_phase2y_provenance_dedupe_attribution_domain_codex_rereview_after_autofix.json`
  — task definition; `requires_clean_worktree: true`; `worktree_excluded_paths`
  lists exactly two operator-managed paths; `next_gate` is
  `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_REREVIEW_PASS`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Y_CODEX_AUTOFIX_VALIDATED_AND_TASK_195_AUTHORED.md`
  — prior turn note; lists eight dispatch-hold paths and two operator-managed
  paths; on-disk verbatim.
- `git log --oneline -1 5419427` — `Create Codex parallel review batch`;
  added nine codex parallel review task definitions covering subjects 01,
  02, 03, 04, 05, 07, 08, 09, 10.
- `git status --porcelain` — confirms nineteen dirty paths in scope of the
  dispatch-hold (one modified `_fixtures.py`, one untracked task 195 JSON,
  four untracked Phase 2Y docs 08–11, fourteen untracked Codex parallel
  review artifacts at `20260510_020600_*` covering subjects 01, 02, 03, 04,
  05, 08, 09) plus three operator-managed paths (the two prior + this turn
  note) and one operator-managed planner-prompt edit.
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/11_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_AUTOFIX_VALIDATION_GO_NO_GO.md`
  — `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_AUTOFIX_VALIDATED`; the
  predecessor marker that gates task 195.
- `claude_worklog/requirements_inbox/REQ_0011_PARALLEL_CODEX_REVIEW_AND_AUTOFIX_LANE.md`
  § "Allowed Codex parallel scope" — `claude_worklog/codex_parallel_reviews/`
  is implicitly the approved isolated report path because the requirement
  authorizes Codex parallel review of completed milestones.
- `claude_worklog/requirements_inbox/REQ_0021_PARALLEL_CAPACITY_SCHEDULER_FOR_CLAUDE_CODEX.md`
  § "If Claude child is inactive and Git is dirty" — explicitly authorizes
  the watchdog to classify dirty files and commit durable artifacts.
- `claude_worklog/requirements_inbox/REQ_0025_CODEX_HIGH_UTILIZATION_REVIEW_QUEUE.md`
  § "Read-only review tasks" — explicitly names
  `claude_worklog/codex_parallel_reviews/` as the approved isolated report
  path for parallel review output.
- `claude_worklog/requirements_inbox/REQ_0016_CODEX_NON_LIVE_HUMAN_REPLACEMENT_WATCHDOG.md`
  § "Operating loop" steps 8–13 — explicitly authorizes the watchdog to
  secret-scan, commit durable artifacts, and restart the planner when the
  worktree is clean.

## Lane assignment

- **Lane:** `codex_watchdog`.
- **Secondary lane:** none (this is a dispatch-hold extension, not a build
  step; no lineage IDs are introduced; no V2 source/test mutation occurs;
  no execution-side surface is added).
- **MVP relevance:** keeps the Phase 2Y CODEX_REREVIEW path on schedule by
  ensuring task 195's `requires_clean_worktree: true` contract is satisfiable
  in one watchdog cycle. Phase 2Y is REQ_0013 prerequisite 2 of 3 and the
  second of three post-MVP gap-closure milestones (Phase 2X / 2Y / 2Z) before
  any SMC/liquidity feature shadow-mode work opens.
- **Next gate:** unchanged —
  `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_REREVIEW_PASS`.

## Hard safety reaffirmed

This planner turn and the watchdog dispatch-hold commit it authorizes do
not modify `/home/wali/Desktop/AI BOT`, do not read or write any Redis key,
do not invoke any Redis command, do not restart any live service, do not
place or cancel exchange orders, do not change leverage or margin, do not
enable live trading, do not deploy, do not run a production migration, do
not expose or commit credentials, do not approve the live gate, do not
invoke any Binance HTTP API or any other live exchange API, do not introduce
any execution-side surface, do not introduce any new lineage ID, do not
modify any byte content of `/home/wali/Desktop/AI BOT`, do not modify any
v2/ source or test file beyond the already-staged `_fixtures.py` autofix
(two literals only), do not modify any prior-milestone byte content under
`claude_worklog/phase2_core_rebuild/` outside the four new Phase 2Y
documentation files (08, 09, 10, 11), do not modify the master planner
prompt, and do not flip
`FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`. The fourteen Codex
parallel review artifacts at `20260510_020600_*` are read-only review
reports under `claude_worklog/codex_parallel_reviews/` per REQ_0025
§ "Read-only review tasks" and contain no V2 source/test mutation, no
Redis call, no live action, and no secret value.

## Path on dispatch

1. The operator commits this planner-turn note in a single commit titled
   `Add Phase 2Y dispatch-hold extension planner-turn note`.
2. The Codex watchdog commits the nineteen dispatch-hold paths in a single
   commit titled `Codex watchdog recover dirty non-live automation artifacts`,
   pushes, and runs the high-confidence secret scan.
3. The supervisor confirms `requires_clean_worktree: true` on task 195
   evaluates clean against the two-path `worktree_excluded_paths` (the
   master planner prompt edit and the prior 2Y open-turn note).
4. Task 195 dispatches as the Codex re-review of Phase 2Y after autofix.
5. On `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_REREVIEW_PASS`,
   the planner authors task 196 to open Phase 2Z degraded-state fail-closed
   gates per Phase 2W's deferral order (REQ_0013 prerequisite 3).
6. On `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_REREVIEW_FAIL`,
   the planner does not advance; instead the planner authors a targeted
   second Codex autofix recovery task constrained to
   `v2/backend/app/{domain,services,composition}/provenance_dedupe_attribution/`,
   `v2/backend/tests/unit/{domain,services,composition}/provenance_dedupe_attribution/`,
   and `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/`
   only.

## Path on FAIL

If any of the following conditions is observed during the watchdog's
dispatch-hold commit, the watchdog stops and surfaces to the planner instead
of committing:

- Any of the nineteen dispatch-hold paths contains a Redis read/write,
  Binance/exchange API call, leverage/margin change, live trading flag flip,
  legacy-bot byte mutation, deployment artifact, or secret value.
- Any of the fourteen Codex parallel review artifacts contains a `v2/`
  source/test diff, a task-definition diff, a planner/supervisor code diff,
  or a `claude_worklog/agent_supervisor/status/` diff.
- The high-confidence secret scan flags any of the nineteen dispatch-hold
  paths.
- The `_fixtures.py` byte change touches more than the two trainer-parity
  literals (`confidence_raw=0.77`, `confidence_calibrated=0.74`) at
  `TRAINER_FIELDS`.

In any of those cases the watchdog leaves `human_attention_required` set,
the planner classifies the failure mode (per REQ_0014 § "Human attention
recovery loop"), and the planner authors a targeted recovery task constrained
to the appropriate non-live scope.

PLANNER_TURN_2Y_CODEX_AUTOFIX_VALIDATED_AND_TASK_195_DISPATCH_HOLD_EXTENDED_READY
END_FILE: claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Y_CODEX_AUTOFIX_VALIDATED_AND_TASK_195_DISPATCH_HOLD_EXTENDED.md

Planner decision: extend the Phase 2Y task 195 dispatch-hold commit scope from the originally-listed eight paths to nineteen paths, covering the full seven-subject Codex parallel review batch at `20260510_020600_*` (01, 02, 03, 04, 05, 08, 09 — fourteen artifacts), the four Phase 2Y docs (08–11), the `_fixtures.py` autofix, and task 195 itself; lane `codex_watchdog`; gate unchanged at `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_REREVIEW_PASS`. The operator commits this turn note first; the watchdog then commits the nineteen paths and dispatches task 195. On PASS the planner opens Phase 2Z (degraded-state fail-closed gates, REQ_0013 prerequisite 3); on FAIL the planner authors a targeted second autofix recovery constrained to the three V2 provenance_dedupe_attribution/ source dirs, the three V2 provenance_dedupe_attribution/ test dirs, and `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/` only. Three operator-managed paths remain excluded (planner prompt + the two 2Y open-turn notes). No `/home/wali/Desktop/AI BOT` mutation, no Redis read/write, no live API call, no leverage/margin change, no deployment, no secret exposure, no execution-side surface, no new lineage ID, and no flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
