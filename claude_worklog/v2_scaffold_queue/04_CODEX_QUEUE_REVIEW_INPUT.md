# 04 — Codex Queue Review Input

## 1. Purpose
This file is the Codex review input bundle for the V2 scaffold implementation queue. Codex MUST adversarially review THIS bundle and produce a separate `05_CODEX_QUEUE_REVIEW.md` (Codex authors that file) plus a one-line GO/NO-GO at `06_CODEX_QUEUE_GO_NO_GO.md` (Codex authors that file). Until Codex returns PASS, every task `015A`–`015F` remains `blocked_approval`.

Codex never authors V2 code; Codex only reviews this queue.

## 2. Files Codex must read
Codex must read every file below in full before producing the review. Summaries are not evidence.

### 2.1 Queue documents (in this directory)
- `claude_worklog/v2_scaffold_queue/00_QUEUE_OVERVIEW.md`
- `claude_worklog/v2_scaffold_queue/01_IMPLEMENTATION_WAVES.md`
- `claude_worklog/v2_scaffold_queue/02_TASK_DEPENDENCY_GRAPH.md`
- `claude_worklog/v2_scaffold_queue/03_SCAFFOLD_BUILD_GUARDRAILS.md`
- `claude_worklog/v2_scaffold_queue/05_SCAFFOLD_QUEUE_GO_NO_GO.md`

### 2.2 Task definition JSONs
- `claude_worklog/agent_supervisor/tasks/015a_repo_package_skeleton.json`
- `claude_worklog/agent_supervisor/tasks/015b_database_migration_skeleton.json`
- `claude_worklog/agent_supervisor/tasks/015c_api_route_skeleton.json`
- `claude_worklog/agent_supervisor/tasks/015d_enterprise_frontend_shell.json`
- `claude_worklog/agent_supervisor/tasks/015e_test_ci_skeleton.json`
- `claude_worklog/agent_supervisor/tasks/015f_agent_dashboard_integration.json`

### 2.3 Upstream planning + architecture
- `claude_worklog/v2_scaffold_planning/01_SCAFFOLD_SCOPE_AND_BOUNDARIES.md`
- `claude_worklog/v2_scaffold_planning/02_PACKAGE_AND_MODULE_MAP.md`
- `claude_worklog/v2_scaffold_planning/03_DATABASE_MIGRATION_PLAN.md`
- `claude_worklog/v2_scaffold_planning/04_API_ROUTE_SCAFFOLD_PLAN.md`
- `claude_worklog/v2_scaffold_planning/05_ENTERPRISE_GUI_SCAFFOLD_PLAN.md`
- `claude_worklog/v2_scaffold_planning/06_AGENT_SUPERVISED_BUILD_SEQUENCE.md`
- `claude_worklog/v2_scaffold_planning/07_TEST_AND_CI_PLAN.md`
- `claude_worklog/v2_scaffold_planning/08_SCAFFOLD_PLANNING_GO_NO_GO.md`
- `claude_worklog/v2_scaffold_planning/09_ENTERPRISE_IMPLEMENTATION_GUARDRAILS.md`
- `claude_worklog/v2_architecture_codex_review/15_ACTUAL_CODEX_RERUN_AFTER_REMEDIATION.md`
- `claude_worklog/v2_architecture_codex_review/16_ACTUAL_CODEX_RERUN_GO_NO_GO.md`
- `claude_worklog/v2_architecture/17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md`
- `CLAUDE.md`

## 3. Adversarial questions Codex must answer
Codex must answer YES/NO with raw evidence pointers (file path + line range) for every question. A question with `unverified` is treated as NO.

### 3.1 Coverage
1. Does the queue cover all six required deliverables (repo skeleton, DB migration skeleton, API route skeleton, enterprise frontend shell, test/CI skeleton, agent/dashboard integration)?
2. Does every task declare `dependencies`, `required outputs`, `safety boundaries`, `observability`, `tests`, `rollback`, `audit evidence`, and `GO/NO-GO marker`?
3. Does every task carry `status=blocked_approval` so the supervisor refuses automatic dispatch?

### 3.2 Boundaries
4. Does any task write outside `v2/**`, `claude_worklog/v2_build/**`, or `claude_worklog/agent_supervisor/**`?
5. Does any task touch `legacy_reference/**`, `../AI BOT/**`, or any `.env`?
6. Does any task write the legacy Redis namespace?
7. Does any task restart legacy services?
8. Does any task enable live trading or place/cancel orders?

### 3.3 Sequence
9. Does the dependency graph form a DAG with no cycles?
10. Is the milestone mapping (B/C/D/E/B-cross) consistent with `17_IMPLEMENTATION_SEQUENCE_AND_MILESTONES.md` §4?
11. Does any task try to elevate its own governance level?

### 3.4 Default-deny
12. Does every task carry the `LIVE TRADING: BLOCKED` invariant?
13. Are all dangerous controls (per `CLAUDE.md` Admin Control Rule §11) listed as default-deny in 015D?
14. Is `live_block_guard` middleware mandated by 015C?

### 3.5 Lineage / explainability
15. Does 015B materialize the schema harness consistent with `12A_DATABASE_LINEAGE_CLOSURE.md` constraints?
16. Does 015C materialize the lineage-validator middleware shell consistent with `12B_API_LINEAGE_ENFORCEMENT_CLOSURE.md` §5?
17. Does 015D render the canonical lineage block per `05_ENTERPRISE_GUI_SCAFFOLD_PLAN.md` §8?

### 3.6 Trainer protected runtime
18. Does 015A declare a subprocess-only adapter location (`v2/backend/app/adapters/trainer/`) without importing legacy trainer modules?
19. Does any task call `pip install` into the trainer venv?

### 3.7 Audit + observability
20. Does every task emit `task.start`, `task.adapter_call`, and `task.complete` events?
21. Does every task hash-chain its audit-ledger rows?
22. Does 015F surface stale-state alerts (`stale_running`, `no_event`, `no_output_growth`, `human_attention_required`) on the dashboard?

### 3.8 Rollback
23. Does every task document a rollback procedure that leaves no orphan files?
24. Is rollback verified by a CI check?

## 4. Output Codex must produce
Codex must author the following files (writes occur under Codex's own session, not this one):

- `claude_worklog/v2_scaffold_queue/05_CODEX_QUEUE_REVIEW.md` — full review with one §3 question per row, raw evidence pointer, and YES/NO/unverified.
- `claude_worklog/v2_scaffold_queue/06_CODEX_QUEUE_GO_NO_GO.md` — single line: `V2_SCAFFOLD_QUEUE_CODEX_PASS` or `V2_SCAFFOLD_QUEUE_CODEX_FAIL`.

The supervisor reads `06_CODEX_QUEUE_GO_NO_GO.md` and refuses to flip any `015X` to `pending` until it equals `V2_SCAFFOLD_QUEUE_CODEX_PASS`.

## 5. What Codex must NOT do
- Codex MUST NOT author any V2 code.
- Codex MUST NOT modify the queue documents 00–05.
- Codex MUST NOT modify any task JSON.
- Codex MUST NOT modify `CLAUDE.md`, the planning package, the architecture set, or the closure files.
- Codex MUST NOT mutate the legacy bot, the trainer venv, the legacy Redis, or any service.

## 6. Codex review timeout
Codex review of this queue is expected within one Codex session. If Codex returns `unverified` on five or more §3 questions, the review fails and the queue is reopened for re-authoring by Claude.

## 7. Status
CODEX QUEUE REVIEW INPUT: PREPARED. AWAITING CODEX RUN.