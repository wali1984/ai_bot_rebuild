# Admin Canonical Field Registry

Generated: 2026-06-23  
Branch: claude/website-admin-final

Every admin page must consume fields from this registry.  
If the same service status appears on Overview, Data, and Orchestration it must use the same registry key and value.

---

## SERVICE fields

| Field | Type | Unit | Freshness | Min Role | Source | Display Format |
|---|---|---|---|---|---|---|
| `service.id` | string | — | static | reviewer | backend config | monospace chip |
| `service.name` | string | — | static | reviewer | backend config | heading label |
| `service.status` | `"ok" \| "warn" \| "error" \| "unknown"` | — | ≤30s | reviewer | `/api/v2/admin/services` | status badge |
| `service.heartbeat_at` | ISO-8601 | timestamp | ≤30s | reviewer | `/api/v2/admin/services` | relative age + absolute tooltip |
| `service.lag_ms` | number | ms | ≤30s | reviewer | `/api/v2/admin/services` | `123 ms` |
| `service.error_count` | number | count | ≤60s | reviewer | `/api/v2/admin/services` | number, red when >0 |
| `service.warning_count` | number | count | ≤60s | reviewer | `/api/v2/admin/services` | number, amber when >0 |
| `service.owner` | string | — | static | reviewer | backend config | text label |
| `service.version` | string | semver | static | reviewer | `/api/v2/admin/services` | monospace |

---

## SOURCE fields

| Field | Type | Unit | Freshness | Min Role | Source | Display Format |
|---|---|---|---|---|---|---|
| `source.id` | string | — | static | reviewer | backend config | monospace chip |
| `source.dataset` | string | — | static | reviewer | backend config | label |
| `source.status` | `"ok" \| "warn" \| "error" \| "gap" \| "unknown"` | — | ≤30s | reviewer | `/api/v2/admin/data/sources` | status badge |
| `source.last_record_at` | ISO-8601 | timestamp | ≤30s | reviewer | `/api/v2/admin/data/sources` | relative age |
| `source.lag_ms` | number | ms | ≤30s | reviewer | `/api/v2/admin/data/sources` | `123 ms` |
| `source.throughput` | number | records/min | ≤30s | reviewer | `/api/v2/admin/data/sources` | `1,234 /min` |
| `source.gap_count` | number | count | ≤60s | reviewer | `/api/v2/admin/data/sources` | number, red when >0 |
| `source.duplicate_count` | number | count | ≤60s | reviewer | `/api/v2/admin/data/sources` | number, amber when >0 |
| `source.error_count` | number | count | ≤60s | reviewer | `/api/v2/admin/data/sources` | number, red when >0 |
| `source.downstream_consumers` | string[] | — | static | reviewer | backend config | comma-separated tags |

---

## JOB fields

| Field | Type | Unit | Freshness | Min Role | Source | Display Format |
|---|---|---|---|---|---|---|
| `job.id` | string | — | static | reviewer | `/api/v2/admin/jobs` | monospace |
| `job.type` | string | — | static | reviewer | `/api/v2/admin/jobs` | label |
| `job.status` | `"running" \| "complete" \| "failed" \| "queued" \| "cancelled"` | — | ≤15s | reviewer | `/api/v2/admin/jobs` | status badge |
| `job.progress` | number | 0–100 | ≤15s | reviewer | `/api/v2/admin/jobs` | progress bar |
| `job.current_step` | string | — | ≤15s | reviewer | `/api/v2/admin/jobs` | text |
| `job.started_at` | ISO-8601 | timestamp | static | reviewer | `/api/v2/admin/jobs` | relative age |
| `job.updated_at` | ISO-8601 | timestamp | ≤15s | reviewer | `/api/v2/admin/jobs` | relative age |
| `job.error` | string \| null | — | ≤15s | reviewer | `/api/v2/admin/jobs` | error text, red |
| `job.owner_service` | string | — | static | reviewer | `/api/v2/admin/jobs` | label |

---

## RISK fields

| Field | Type | Unit | Freshness | Min Role | Source | Display Format |
|---|---|---|---|---|---|---|
| `risk.rule_id` | string | — | static | admin | `/api/v2/admin/risk/rules` | monospace |
| `risk.status` | `"allow" \| "block" \| "warn" \| "unknown"` | — | ≤10s | admin | `/api/v2/admin/risk/rules` | status badge |
| `risk.threshold` | number | varies | static | admin | `/api/v2/admin/risk/rules` | numeric |
| `risk.current_value` | number | varies | ≤10s | admin | `/api/v2/admin/risk/rules` | numeric, colored vs threshold |
| `risk.block_count` | number | count | ≤10s | admin | `/api/v2/admin/risk/rules` | number |
| `risk.last_decision_at` | ISO-8601 | timestamp | ≤10s | admin | `/api/v2/admin/risk/rules` | relative age |

---

## TRADER fields

| Field | Type | Unit | Freshness | Min Role | Source | Display Format |
|---|---|---|---|---|---|---|
| `trader.id` | string | — | static | admin | `/api/v2/admin/traders` | monospace |
| `trader.mode` | `"paper" \| "live" \| "replay" \| "backtest"` | — | ≤15s | admin | `/api/v2/admin/traders` | mode badge |
| `trader.status` | `"active" \| "idle" \| "error" \| "stopped"` | — | ≤15s | admin | `/api/v2/admin/traders` | status badge |
| `trader.heartbeat_at` | ISO-8601 | timestamp | ≤15s | admin | `/api/v2/admin/traders` | relative age |
| `trader.strategy_ids` | string[] | — | ≤30s | admin | `/api/v2/admin/traders` | tags |
| `trader.symbols` | string[] | — | ≤30s | admin | `/api/v2/admin/traders` | tags |
| `trader.position_count` | number | count | ≤15s | admin | `/api/v2/admin/traders` | number |
| `trader.order_count` | number | count | ≤15s | admin | `/api/v2/admin/traders` | number |
| `trader.pnl` | number | USD | ≤15s | admin | `/api/v2/admin/traders` | `$1,234.56` |
| `trader.risk_status` | `"ok" \| "warn" \| "blocked"` | — | ≤10s | admin | `/api/v2/admin/traders` | status badge |

---

## INCIDENT fields (for AdminIncidentCard)

| Field | Type | Unit | Freshness | Min Role | Source | Display Format |
|---|---|---|---|---|---|---|
| `incident.id` | string | — | static | reviewer | `/api/v2/admin/incidents` | monospace |
| `incident.severity` | `"critical" \| "high" \| "medium" \| "low"` | — | ≤10s | reviewer | `/api/v2/admin/incidents` | severity badge |
| `incident.missing_source` | string | — | ≤30s | reviewer | `/api/v2/admin/incidents` | label |
| `incident.expected_endpoint` | string | — | static | reviewer | `/api/v2/admin/incidents` | monospace URL |
| `incident.owner_service` | string | — | static | reviewer | `/api/v2/admin/incidents` | label |
| `incident.last_success_at` | ISO-8601 \| null | timestamp | ≤30s | reviewer | `/api/v2/admin/incidents` | relative age or "never" |
| `incident.current_error` | string | — | ≤30s | reviewer | `/api/v2/admin/incidents` | error text |
| `incident.affected_pages` | string[] | — | static | reviewer | `/api/v2/admin/incidents` | page route list |
| `incident.remediation_action` | string | — | static | reviewer | `/api/v2/admin/incidents` | action description |
| `incident.incident_id` | string | — | static | reviewer | `/api/v2/admin/incidents` | monospace reference |

---

## CONTROL ACTION fields (for ControlActionDialog)

| Field | Type | Required | Note |
|---|---|---|---|
| `control.action_id` | string | yes | Maps to `DangerousControlId` in constants |
| `control.description` | string | yes | Human-readable description shown in confirmation |
| `control.dry_run_result` | string \| null | no | Backend dry-run output shown before confirmation |
| `control.reason` | string | yes | Operator must enter mandatory reason |
| `control.confirmed` | boolean | yes | Explicit checkbox confirmation |
| `control.audit_id` | string | yes | Backend returns after action — must be displayed |
| `control.error` | string \| null | no | Backend error displayed on failure |
| `control.backend_response` | unknown | no | Full backend response shown in audit panel |

---

## Missing Source Sentinel

When any admin page cannot load a required data source, it MUST render an `AdminIncidentCard` with all `incident.*` fields populated.  
It must NOT show "Connecting…", "Loading…", or an empty panel.

The page must display:
- `incident.missing_source` — the specific dataset name
- `incident.expected_endpoint` — the API route or topic that should serve it
- `incident.owner_service` — which backend service owns this data
- `incident.last_success_at` — when it last worked
- `incident.current_error` — the exact error or "no response"
- `incident.affected_pages` — all admin pages that consume this source
- `incident.remediation_action` — what an operator should do
- `incident.incident_id` — a stable reference for tracking
