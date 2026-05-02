```markdown
# B — Agent Supervisor + Dashboard Integration Validation (015F)

## 1. Scope
Materialize backend READ-ONLY services and API surfaces that read the agent
supervisor artifacts produced by `claude_worklog/tools/agent_supervisor.py`,
plus React panels, hooks, integration tests, and Playwright e2e tests so the
V2 GUI surfaces every stale-state alert enumerated in
`claude_worklog/agent_supervisor_reliability/02_IMPLEMENTATION_REPORT.md`
§1.10 / §1.11.

This is **not** a V2 build promotion. No live trader, live trainer, Redis,
or legacy bot is touched. LIVE TRADING: BLOCKED.

## 2. Boundaries observed (CLAUDE.md compliance)
- Wrote only under `v2/**` and `claude_worklog/v2_build/**`.
- Did **not** edit `legacy_reference/**`, `../AI BOT/**`, any `.env`, or any
  secrets file.
- Did **not** write under `claude_worklog/agent_supervisor/**`. The reader
  service uses Python `open(..., "r")` exclusively; an integration-test
  invariant snapshots the full supervisor tree before/after every endpoint
  call and asserts size+mtime stability.
- Did **not** place or cancel exchange orders, change leverage/margin mode,
  write legacy Redis keys, restart any live service, or enable live trading.
- Did **not** import legacy trainer modules into the FastAPI process or the
  frontend bundle. The reader walks JSON files only.
- Did **not** install packages into the trainer venv or upgrade
  PyTorch/CUDA. No new Python dependencies added.
- Did **not** add an npm dependency on `@tanstack/react-query`. The hooks
  conform to React-Query's surface (`{data, error, isLoading, isFetching,
  refetch}`) but ship via a self-contained `usePollingQuery` so the
  milestone-E "no React Query" deviation is preserved.

## 3. Files materialized

| Path | Role |
| --- | --- |
| `v2/backend/app/services/agent_supervisor_reader.py` | READ-ONLY reader of queue_status.json, agent_health.json, supervisor_heartbeat.json, runs/<id>/summary.json, events.jsonl |
| `v2/backend/app/api/v1/health.py` | Adds GET `/agent-health`, `/queue-status`, `/build-status`, `/audit-chain` under `/api/v1/_meta/` |
| `v2/backend/tests/integration/test_agent_supervisor_endpoints.py` | Integration tests with synthetic fixtures + read-only invariant |
| `v2/frontend/src/hooks/usePollingQuery.ts` | React-Query-shape hook helper (self-contained, no extra deps) |
| `v2/frontend/src/hooks/useAgentHealth.ts` | Hook for `/api/v1/_meta/agent-health` |
| `v2/frontend/src/hooks/useQueueStatus.ts` | Hook for `/api/v1/_meta/queue-status` |
| `v2/frontend/src/hooks/useBuildStatus.ts` | Hook for `/api/v1/_meta/build-status` |
| `v2/frontend/src/hooks/useAuditChain.ts` | Hook for `/api/v1/_meta/audit-chain` |
| `v2/frontend/src/components/dashboard/AgentHealthPanel.tsx` | Heartbeat + agent-health panel |
| `v2/frontend/src/components/dashboard/QueueStatusPanel.tsx` | Queue counts + gate panel |
| `v2/frontend/src/components/dashboard/StaleStateAlertsPanel.tsx` | Surfaces every §1.10 alert category with task ids |
| `v2/frontend/src/components/dashboard/BuildValidationPanel.tsx` | Recent runs + audit-chain integrity |
| `v2/frontend/src/pages/mission-control/index.tsx` | Wires all four panels into Mission Control |
| `v2/frontend/tests/e2e/stale_state_alerts.spec.ts` | Playwright e2e for stale-state surfacing |
| `claude_worklog/v2_build/B_AGENT_DASHBOARD_INTEGRATION_VALIDATION.md` | This validation report |

## 4. Backend reader contract

The reader resolves its supervisor root by precedence:
1. explicit `root` argument (used by tests);
2. env var `V2_SUPERVISOR_ROOT` (used by tests via monkeypatch);
3. default `<repo_root>/claude_worklog/agent_supervisor`, derived from
   `__file__.parents[4]`.

Public functions:
- `read_agent_health(root=None)` — returns
  `{_meta, agent_health, heartbeat, heartbeat_age_s, heartbeat_stale,
  heartbeat_missing}`. `heartbeat_stale` flips at age ≥ 600s per
  02 §1.11.
- `read_queue_status(root=None)` — returns
  `{_meta, data}` where `data` is the full queue_status.json payload.
- `read_build_status(root=None, limit=25)` — sorts run summaries by
  `start_time` descending. Unparseable summaries surface as entries with
  `error` populated; the reader never silently drops a run dir.
- `read_audit_chain(root=None, limit=100)` — tail of events.jsonl, plus
  a chain-integrity check that flags every `cur < prev` pair.

All reads use `path.open("r", ...)`. There is no `"w"`, `"a"`, `"x"`, or
`"r+"` mode anywhere in the module.

## 5. Endpoint contract (`/api/v1/_meta/*`)

| Method | Path | Source files | Behaviour |
| --- | --- | --- | --- |
| GET | `/api/v1/_meta/agent-health` | `status/agent_health.json` + `status/supervisor_heartbeat.json` | Adds derived `heartbeat_age_s`, `heartbeat_stale`, `heartbeat_missing` |
| GET | `/api/v1/_meta/queue-status` | `status/queue_status.json` | Pass-through `{_meta, data}`; `data=null` if missing |
| GET | `/api/v1/_meta/build-status?limit=N` | `runs/<task_id>/summary.json` | Sorted desc by `start_time`; unparseable runs include an `error` field |
| GET | `/api/v1/_meta/audit-chain?limit=N` | `events.jsonl` | Tail + `chain_intact`/`chain_breaks` |

`limit` is bounded server-side (`build-status`: 1..200; `audit-chain`:
1..1000) using `fastapi.Query`. The endpoints sit under `/_meta` so the
existing live-block guard never matches their path.

## 6. Frontend stale-state mapping

The StaleStateAlertsPanel renders one region per alert category. The
mapping below is the single source of truth between supervisor field
names (02 §1.10) and DOM-test attributes:

| §1.10 alert | queue_status.json field | data-testid (group) | per-row attributes |
| --- | --- | --- | --- |
| stale_running | `stale_running_tasks: string[]` | `stale-state-stale-running` | `data-alert-kind="stale_running"`, `data-task-id` |
| no_event | `no_event_tasks: string[]` | `stale-state-no-event` | `data-alert-kind="no_event"`, `data-task-id` |
| no_output_growth | `no_output_growth_tasks: string[]` | `stale-state-no-output-growth` | `data-alert-kind="no_output_growth"`, `data-task-id` |
| blocked_quota | `blocked_quota: {task_id, agent, resume_after_utc}` | `stale-state-blocked-quota` | `data-alert-kind="blocked_quota"`, `data-task-id`, `data-resume-after` |
| human_attention_required | `human_attention_required_tasks: HumanAttentionTask[]` | `stale-state-human-attention-required` | `data-alert-kind="human_attention_required"`, `data-task-id`, `data-attention-reason` |

Every category exposes a `data-count` attribute on its group element so
the e2e test can assert presence/absence without scraping text.

## 7. React Query hook surface

`usePollingQuery<T>(key, fetcher, {enabled, refetchIntervalMs})` returns:
- `data: T | null`
- `error: Error | null`
- `isLoading: boolean` (true until first fetch resolves or rejects)
- `isFetching: boolean` (true during any in-flight fetch)
- `refetch: () => void`

Cancellation is handled via a ref, preventing post-unmount setState.
Polling intervals: 10s (queue-status), 15s (agent-health), 30s
(build-status, audit-chain). The hooks are pure and degrade gracefully on
fetch failure (panels render an `aria-live` error region).

## 8. Backend integration tests (`v2/backend/tests/integration/test_agent_supervisor_endpoints.py`)

Each test materializes a synthetic supervisor tree under `tmp_path`,
points `V2_SUPERVISOR_ROOT` at it via monkeypatch, and exercises the
four endpoints through `fastapi.testclient.TestClient`.

Coverage:
- `test_agent_health_returns_heartbeat_and_health` — happy path.
- `test_agent_health_flags_stale_heartbeat` — heartbeat age ≥ 600s
  flips `heartbeat_stale`.
- `test_agent_health_handles_missing_heartbeat` — `heartbeat_missing=True`
  when files absent.
- `test_queue_status_passes_through_payload` — happy path.
- `test_queue_status_surfaces_alert_arrays` — every §1.10 alert
  category returned verbatim through the endpoint.
- `test_queue_status_handles_missing_file` — `_meta.error="missing"`.
- `test_build_status_returns_summaries_sorted_desc` — sort order and
  agent passthrough.
- `test_build_status_respects_limit_query` — `?limit=N` truncates.
- `test_build_status_includes_unparseable_runs` — bad JSON surfaces as
  an entry with `error != null` rather than being dropped.
- `test_audit_chain_returns_intact_chain` — happy path.
- `test_audit_chain_detects_break` — out-of-order timestamps reported.
- `test_audit_chain_missing_events_file` — empty + `_meta.exists=False`.
- `test_endpoints_do_not_mutate_supervisor_root` — snapshot/diff
  invariant proves READ-ONLY contract end-to-end.

## 9. Playwright e2e (`v2/frontend/tests/e2e/stale_state_alerts.spec.ts`)

Tests are hermetic: every backend endpoint is mocked at the network
boundary via `page.route(...)`. The existing LiveBlockBanner fetch is
mocked to a `state: "blocked"` payload to keep the banner visible.

Coverage:
- `surfaces all five alert categories with task ids` — exercises
  stuck_task / silent_task / frozen_task / quota_task_42 / broken_task,
  asserting `data-alert-kind` + `data-task-id` for each, plus
  `data-attention-reason` for the human-attention category.
- `renders empty-state for each category when feed is clean` —
  guards against false positives (`data-alert-total="0"` and every
  group `data-count="0"`).

## 10. Verification commands

# Backend unit/integration (use the v2 dev venv, not the trainer venv)
cd "$(git rev-parse --show-toplevel)/v2"
python -m pytest backend/tests/integration/test_agent_supervisor_endpoints.py -q

# Static checks
python -m ruff check backend
python -m mypy backend/app/services/agent_supervisor_reader.py backend/app/api/v1/health.py

# Frontend e2e (requires `npm install` in v2/frontend)
cd v2/frontend
npm run test:e2e -- stale_state_alerts

## 11. Evidence pointers

- §1.10 alert taxonomy:
  `claude_worklog/agent_supervisor_reliability/02_IMPLEMENTATION_REPORT.md`
  lines 62–75.
- queue_status.json producer (alert arrays):
  `claude_worklog/tools/agent_supervisor.py`.
- supervisor_heartbeat.json schema:
  live sample at `claude_worklog/agent_supervisor/status/supervisor_heartbeat.json`.
- runs/<task_id>/summary.json schema:
  live sample at `claude_worklog/agent_supervisor/runs/`.
- events.jsonl:
  live sample at `claude_worklog/agent_supervisor/events.jsonl`.

## 12. Safety checklist
- [x] No writes to `claude_worklog/agent_supervisor/**`.
- [x] No writes to `legacy_reference/**` or `../AI BOT/**`.
- [x] No `.env` reads or writes.
- [x] No exchange orders placed or cancelled.
- [x] No leverage / margin-mode change.
- [x] No legacy Redis writes.
- [x] No live trader / live trainer restart.
- [x] LIVE TRADING: BLOCKED (default).
- [x] No new Python dependencies; no trainer-venv mutation.
- [x] No new npm dependencies; React Query surface is self-contained.

## 13. Final marker

B_AGENT_DASHBOARD_INTEGRATION_VALIDATION_READY
