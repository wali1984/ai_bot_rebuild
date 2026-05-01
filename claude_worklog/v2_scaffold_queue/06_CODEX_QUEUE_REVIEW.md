# Codex Queue Review

Verdict: BLOCKED

Scope reviewed: queue definitions only. No implementation code generated, no files written, no Redis writes, no services restarted, and `/home/wali/Desktop/AI BOT` was not touched.

## Findings / Blockers

1. BLOCKER: Task definition JSONs do not carry `status=blocked_approval`.
   - Requirement: `03_SCAFFOLD_BUILD_GUARDRAILS.md:6-25` requires every queue task JSON to include `status = blocked_approval`.
   - Review input asks the same: `04_CODEX_QUEUE_REVIEW_INPUT.md:44-47`.
   - Evidence: task JSONs contain task fields but no `status` key: `015a_repo_package_skeleton.json:1-134`, `015b_database_migration_skeleton.json:1-120`, `015c_api_route_skeleton.json:1-165`, `015d_enterprise_frontend_shell.json:1-171`, `015e_test_ci_skeleton.json:1-122`, `015f_agent_dashboard_integration.json:1-153`.
   - Counter-evidence: state files do carry blocked status, e.g. `state/tasks/015a_repo_package_skeleton.json:1-14`.
   - Required fix: either add `"status": "blocked_approval"` to every task definition JSON or revise the guardrail/review contract to state that status is sourced only from `agent_supervisor/state/tasks/*.json`.

2. BLOCKER: 015E dependency ordering contradicts the wave model.
   - W1 says 015A and 015E are in the same wave and may run in parallel: `01_IMPLEMENTATION_WAVES.md:10-13`, `01_IMPLEMENTATION_WAVES.md:32-33`.
   - The DAG says `015A -> 015E`: `02_TASK_DEPENDENCY_GRAPH.md:14-23`.
   - 015E itself depends on 015A and requires `B_SCAFFOLD_VALIDATION.md`: `015e_test_ci_skeleton.json:25-40`.
   - Required fix: choose one model. If 015E requires 015A, make W1 explicitly sequential or move 015E to W2. If 015E is intended to run parallel with 015A, remove the 015A dependency and the `B_SCAFFOLD_VALIDATION.md` gate.

3. BLOCKER: The declared global gate evidence floor is not present on every task.
   - Queue overview says each task declares the same pre-execution floor: `00_QUEUE_OVERVIEW.md:51-65`.
   - Guardrails require closure files + Codex PASS + planning READY in every `gate_evidence_ref`: `03_SCAFFOLD_BUILD_GUARDRAILS.md:17-18`.
   - 015B only lists a reduced floor and omits several global floor items: `015b_database_migration_skeleton.json:33-40`.
   - 015C, 015D, 015E, and 015F likewise use reduced per-task gate lists: `015c_api_route_skeleton.json:71-79`, `015d_enterprise_frontend_shell.json:77-86`, `015e_test_ci_skeleton.json:34-40`, `015f_agent_dashboard_integration.json:50-63`.
   - Required fix: add the full global floor to every 015A-015F `gate_evidence_ref`, then append per-task gates.

4. BLOCKER: Early task tests reference CI files that are produced later.
   - 015A static tests require `ops/ci/import_cycle_check.py`: `015a_repo_package_skeleton.json:99-109`.
   - 015E is the task that creates `v2/ops/ci/import_cycle_check.py` and depends on 015A: `015e_test_ci_skeleton.json:13-27`.
   - 015B references `ops/ci/schema_drift_check.py`: `015b_database_migration_skeleton.json:85-94`, but 015B does not depend on 015E: `015b_database_migration_skeleton.json:24-26`.
   - Required fix: either move the CI harness earlier, add the necessary 015E dependencies before tasks that require those scripts, or remove unavailable CI checks from earlier task acceptance criteria.

5. BLOCKER: 015D required outputs do not match its own prompt or frontend guardrails.
   - Guardrail requires every page folder to have `rbac.ts` and `meta.ts`: `03_SCAFFOLD_BUILD_GUARDRAILS.md:59-70`.
   - 015D prompt requires every page folder to include `index.tsx + route.ts + rbac.ts + meta.ts`: `015d_enterprise_frontend_shell.json:168`.
   - Required outputs list these files only for `mission_control`; the other page folders list only `index.tsx`: `015d_enterprise_frontend_shell.json:27-58`.
   - Required fix: enumerate `route.ts`, `rbac.ts`, and `meta.ts` for every required page folder, or explicitly narrow the requirement and update guardrails/tests.

6. BLOCKER: Audit evidence blocks do not specify required ledger row fields.
   - Guardrail requires each audit row to carry `prior_event_hash`, `event_hash`, `task_id`, `risk_level`, `actor_subject`, `gate_evidence_ref[]`, `materialized_files[]`, and `validation_artifact_path`: `03_SCAFFOLD_BUILD_GUARDRAILS.md:98-102`.
   - Task audit blocks list events and a generic hash-chain expression but do not require the full field set: `015a_repo_package_skeleton.json:122-129`, `015b_database_migration_skeleton.json:107-115`, `015c_api_route_skeleton.json:151-159`, `015d_enterprise_frontend_shell.json:157-165`, `015e_test_ci_skeleton.json:108-117`, `015f_agent_dashboard_integration.json:139-148`.
   - Required fix: add the required audit row field schema to every task’s `audit_evidence` block.

7. BLOCKER: Observability requires a run summary file, but task observability does not require it.
   - Guardrail requires a row/file at `claude_worklog/agent_supervisor/runs/<task_id>/<ts>/summary.json`: `03_SCAFFOLD_BUILD_GUARDRAILS.md:77-84`.
   - Task observability blocks list stdout/stderr logs but not `summary.json`: `015a_repo_package_skeleton.json:78-98`, `015b_database_migration_skeleton.json:64-84`, `015c_api_route_skeleton.json:104-124`, `015d_enterprise_frontend_shell.json:108-129`, `015e_test_ci_skeleton.json:64-85`, `015f_agent_dashboard_integration.json:88-111`.
   - Required fix: require `summary.json` emission in every task observability block, or document that the supervisor emits it independently and validates it.

8. BLOCKER: Codex queue GO/NO-GO marker names are inconsistent.
   - Queue review input expects `V2_SCAFFOLD_QUEUE_CODEX_PASS` or `V2_SCAFFOLD_QUEUE_CODEX_FAIL`: `04_CODEX_QUEUE_REVIEW_INPUT.md:84-90`.
   - Current requested output contract requires `V2_SCAFFOLD_QUEUE_CODEX_REVIEW_PASS` or `V2_SCAFFOLD_QUEUE_CODEX_REVIEW_BLOCKED`.
   - Required fix: normalize the supervisor-read marker, queue review input, and Codex output contract to one exact pair of strings.

## Passing / Mostly Adequate Areas

- Six required deliverables are covered in queue scope: `00_QUEUE_OVERVIEW.md:8-18`.
- Safety boundaries consistently prohibit legacy bot mutation, legacy Redis writes, service restarts, live trading, and order placement at the queue level: `00_QUEUE_OVERVIEW.md:22-33`, `03_SCAFFOLD_BUILD_GUARDRAILS.md:27-44`.
- The dependency graph is acyclic as written: `02_TASK_DEPENDENCY_GRAPH.md:14-23`.
- 015C mandates `live_block_guard`: `015c_api_route_skeleton.json:100-102`.
- 015F surfaces stale-state alerts, including `stale_running`, `no_event`, `no_output_growth`, and `human_attention_required`: `015f_agent_dashboard_integration.json:150`.

## Required Fix Summary

Before dispatching any 015A-015F task, fix the task JSON/status source-of-truth, resolve 015E wave/dependency ordering, apply the full global gate floor to every task, remove or reorder unavailable CI checks, complete 015D page required outputs, strengthen audit and observability schemas, and normalize the Codex review marker contract.

Final queue decision: BLOCKED.
