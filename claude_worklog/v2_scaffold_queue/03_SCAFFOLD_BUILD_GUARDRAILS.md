# 03 — Scaffold Build Guardrails

## 1. Authority
This file extends `claude_worklog/v2_scaffold_planning/09_ENTERPRISE_IMPLEMENTATION_GUARDRAILS.md` with queue-specific guardrails. Both must be satisfied before any `015X` task dispatches. Where this file and `09` overlap, the stricter rule wins.

## 2. Mandatory blocks per task (cross-checked at dispatch)
The supervisor refuses to dispatch a queue task whose JSON does not include all of:

1. `task_id` matching the file stem.
2. `agent` ∈ {`claude`}.
3. `risk_level` ∈ {`L1`, `L2`} (no L3+ in the scaffold queue).
4. `cwd` = `/home/wali/Desktop/AI BOT REBUILD`.
5. `emit_files` = `true`.
6. `allowed_output_prefixes` (non-empty, every entry under `v2/`, `claude_worklog/v2_build/`, or `claude_worklog/agent_supervisor/`).
7. `required_output_files` (non-empty).
8. `prompt` (non-empty, includes hard prohibitions from `CLAUDE.md`).
9. `depends_on` (may be empty for 015A; required for 015B–F).
10. `gate_evidence_ref[]` resolving to closure files + Codex PASS + planning-package READY.
11. `safety_boundary` block (forbidden writes, forbidden reads, forbidden runtime actions).
12. `observability` block (events, metrics, logs, dashboard surfaces).
13. `tests` block (unit, integration, contract, e2e per applicability).
14. `rollback` block (rollback procedure + rollback verification).
15. `audit_evidence` block (audit-ledger rows emitted, hash-chain link).
16. `go_no_go_marker` (single line that the validation artifact must produce).
17. `status` = `blocked_approval` (initial state).

## 3. Forbidden writes (queue-wide, supervisor-enforced)
- `legacy_reference/**`
- `../AI BOT/**`
- any `.env` or secrets file
- legacy Redis namespace (any key not under `${V2_REDIS_PREFIX}*`)
- the trainer venv (`pip install`, `python -m venv`, `pyvenv.cfg` writes)
- `/home/wali/Desktop/AI BOT/**`

## 4. Forbidden runtime actions (queue-wide)
- placing or cancelling exchange orders
- changing leverage or margin mode
- writing to the legacy Redis instance
- restarting the live trainer, live trader, orchestrator, Redis, or VPN
- enabling live trading
- mutating the running live bot
- self-healing the running live bot
- importing legacy trainer modules into the FastAPI process

## 5. Mandatory contract block for every new module
Per `09_ENTERPRISE_IMPLEMENTATION_GUARDRAILS.md` §3, every new module under `v2/` MUST declare:
- Owner component
- Input contracts
- Output contracts
- Failure modes
- Retry behavior
- Idempotency behavior
- Observability events
- Health/heartbeat semantics
- Configuration/hot-reload behavior

Modules that do not declare all nine fail CI under `ops/ci/import_cycle_check.py` (the script also greps for the contract docstring header).

## 6. Mandatory definition for every website / admin feature
Per `09_ENTERPRISE_IMPLEMENTATION_GUARDRAILS.md` §4, every page/component MUST declare:
- Public vs admin visibility
- RBAC scope
- Audit logging
- Explanation text
- Approval requirements
- Animation/UX class
- Mobile/iPhone behavior
- Error/empty/loading states

The frontend lint rule `no-undocumented-page` (added by 015E) fails any page folder missing a `rbac.ts` + `meta.ts` pair declaring these fields.

## 7. Default-deny invariants
- `LIVE TRADING: BLOCKED` banner is rendered by the page shell on every route.
- All dangerous controls render disabled with a `RequiresApprovalBadge`.
- `live_block_guard` middleware is mounted in front of every `/api/v1/live/**` route at startup. The middleware-order startup assertion (added by 015C) refuses to start if the order is wrong.

## 8. Observability minimum
Every task MUST emit:
- `task.start` event (with `gate_evidence_ref` resolved).
- `task.adapter_call` event for each adapter invocation (DB, Redis, subprocess).
- `task.complete` event with `materialized_files[]` and `validation_artifact_path`.
- A row in `claude_worklog/agent_supervisor/runs/<task_id>/<ts>/summary.json`.

A task that completes without these events is treated as `human_attention_required` by the dashboard's stale-state alert (per `agent_supervisor_reliability/02_IMPLEMENTATION_REPORT.md` §1.10).

## 9. Test minimum per task
- 015A: lint + type-check + import-cycle smoke. No domain tests yet.
- 015B: integration-test placeholder under `backend/tests/integration/` proving Alembic up/down round-trip on an ephemeral PG; no real migration files yet.
- 015C: contract-test placeholder under `backend/tests/contract/` loading `05_API_CONTRACTS.md` §13 vectors as YAML stubs (no handlers yet, but the loader works).
- 015D: Playwright nav-smoke test asserting all 26 pages render their placeholder + the `LIVE TRADING: BLOCKED` banner persists across route changes.
- 015E: a one-shot `make ci` invocation that runs lint, type, import-cycle, schema-drift, and the (currently empty) test suites and exits 0.
- 015F: a unit test asserting the `/api/v1/_meta/agent-health` endpoint returns the supervisor's `agent_health.json` shape, plus a Playwright check that the dashboard banner reflects `human_attention_required` count.

## 10. Rollback minimum per task
- Each task documents its `rollback` block: the exact set of files to remove and the exact validation-artifact rows to delete.
- A rollback that leaves any orphan file under `v2/**` reopens the task; the supervisor's path-orphan check (added by 015E to `ops/ci/import_cycle_check.py`) flags orphan files at the next CI run.

## 11. Audit-evidence minimum per task
- Each task emits a `governance.task_dispatched` audit-ledger row at start.
- Each task emits a `governance.task_validated` row at end.
- Each row carries `prior_event_hash`, `event_hash`, `task_id`, `risk_level`, `actor_subject`, `gate_evidence_ref[]`, `materialized_files[]`, and `validation_artifact_path`.
- Hash-chain breaks freeze the queue.

## 12. GO/NO-GO marker discipline
- Every task's validation artifact MUST end with exactly one line of either `<TASK>_VALIDATION_READY` or `<TASK>_VALIDATION_BLOCKED`.
- The supervisor reads only the last non-empty line of each validation artifact when deciding whether to release the next dependency edge.
- A validation artifact whose last line is anything else is treated as `BLOCKED`.

## 13. Status
GUARDRAILS: ENUMERATED. ENFORCEMENT: SUPERVISOR + CI. APPLIES TO: 015A–015F.