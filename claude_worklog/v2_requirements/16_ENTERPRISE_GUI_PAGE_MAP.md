# 16 Enterprise GUI Page Map

## Requirement ID
V2-GUI-PAGE-MAP-001

## Rule
No demo/sample pages. Every page must bind to actual system data and/or actual control APIs with safety gates.

| Page | Purpose | Visible data | Controls | Admin-only controls | Safety gates | Underlying API/data source |
|---|---|---|---|---|---|---|
| Mission Control | Global runtime command center | platform status, key health, alerts, readiness summary | safe operator toggles, incident acknowledge | global emergency policy override | live mutation gates, role gates | monitor snapshots, health APIs, alert streams |
| Market Universe Manager | Manage tradable symbols and states | symbol list, eligibility factors, status flags, universe versions | add/remove/update symbols, state changes | force apply/rollback universe version | approval + validation + audit required | universe service, exchange metadata, audit ledger |
| Exchange Manager | Manage exchange connectors/accounts | connector health, capabilities, rate limits, account binding | enable/disable connector (safe mode) | credential binding, live endpoint enablement | connector health + auth + RBAC | connector registry, connector health APIs |
| Ingestor Manager | Supervise data ingestion services | ingestor status, lag, feed freshness | restart-safe internal control endpoints (if policy allows) | topology and schedule policy edits | data freshness + auth | ingestor telemetry APIs, heartbeat keys |
| Feature Flow Map | Visualize feature data flow end-to-end | source->feature lineage, transform health | trace filters | pipeline graph edits | approval + config audit | feature pipeline telemetry, lineage store |
| Feature Freshness Monitor | Detect stale/missing feature keys | freshness ages, missing/stale counts, source coverage | thresholds (safe bounds) | threshold policy changes | stale-protection and RBAC | freshness monitor APIs, Redis read-only metrics |
| Trainer Control Center | Control trainer modes and policy state | trainer health, mode, loop cadence, model status | bounded mode toggles (safe) | live-train policy, advanced trainer config | live gate + approval | trainer control API, heartbeat, diagnostics |
| Prediction Monitor | Observe prediction throughput and quality | prediction rates, confidence distributions, per-symbol state | filter/time window controls | override retention policy | read-only unless admin policy action | prediction stream, analytics store |
| Signal Explainability | Explain prediction→signal decisions | top features, confidence drivers, lineage IDs | drill-down and compare | explainability schema policy | lineage completeness gate | explainability API, attribution store |
| Confidence Driver Breakdown | Breakdown why confidence moved | positive/negative contributors, freshness tags | scenario compare | model-feature weighting policy edits | admin approval + audit | feature attribution API |
| Orchestrator Control | Manage proposal arbitration layer | proposal flow, arbitration outcomes, queue health | safe pause/resume where allowed | arbitration policy editing | risk gateway + approval | orchestrator APIs, proposal streams |
| Risk Gateway | Final risk authority view/control | allow/block decisions, budget/cooldown state, gate outcomes | read-only policy diagnostics | risk policy changes, hard blocks | mandatory authority, dual-approval for dangerous edits | risk gateway APIs, policy ledger |
| Trader Fleet Manager | Manage trader instances and assignments | fleet roster, heartbeat, pnl, attribution completeness | add/remove/reassign (paper/default-safe) | live-mode enablement, high-risk changes | RBAC + readiness + risk gateway | fleet manager API, trader heartbeats |
| Execution Monitor | Monitor executions and failures | order lifecycle, skip reasons, latency, fill quality | filter/triage controls | execution policy overrides | live controls blocked unless gates pass | execution telemetry, trader events |
| Positions/Portfolio | Portfolio and position supervision | per-account positions, exposure, PnL, drawdown | hedge/protective requests (gated) | direct risk parameter overrides | no-loss/risk gateway/live gate | portfolio API, risk state store |
| Redis/Storage Health | Storage reliability and retention | memory ratio, keyspace pressure, stream retention | runbook links, safe diagnostics | retention policy updates | admin-only mutation controls | Redis read-only metrics, storage APIs |
| Continuous Monitor Dashboard | Always-on audit monitor | liveness matrix, evidence quality, alert history | refresh/inspect controls | alert policy edits | read-only by default | monitor snapshots, packet store |
| Audit Ledger | Immutable action and policy history | actor/action/resource/time/result | search/export | retention and legal-hold policy | tamper-evidence controls | audit event store |
| Config Admin | Controlled config lifecycle | active config sets, diffs, version graph | propose config update | approve/apply/rollback config | staged validation + approvals | config service, version store |
| Replay/Paper Trading | Test strategies safely | replay outcomes, paper PnL, scenario stats | start/stop replay, paper experiments | promote profile to candidate-live | replay pass criteria + risk checks | replay engine APIs, market archives |
| Claude/Codex/Ollama Review Center | AI-assisted review and evidence collation | review packets, unresolved findings, confidence tags | generate review packets | approve/reject AI recommendations | human-in-loop mandatory | review packet store, monitor/audit artifacts |
| Live Readiness | Explicit GO/NO-GO gate hub | checklist status, blocking findings, gate evidence | run readiness checks | final live unlock controls | all mandatory gates must pass | readiness API, governance artifacts |
| Deployment/Hosting Admin | Deployment and hosting management | environment status, release versions, security posture | stage deploy requests | production deploy/rollback, ingress policy | auth/RBAC/2FA/IP allowlist | deploy controller APIs, infra telemetry |
| Mobile/iPhone Readiness | Mobile operational usability | responsive score, mobile telemetry, key action compatibility | mobile view checks | mobile policy toggles | critical action confirmation UX | frontend telemetry, UX test APIs |

## Mandatory extensions for requirements 19 and 20

1. Passive Market Discovery page (required)
- purpose: full all-market passive discovery and adaptive universe scoring oversight
- visible data: available/observed/training/trading universe layers, symbol factor scores, data completeness, freshness, source ingestors, capacity/ranking outputs
- controls: safe filters and drill-downs, manual include/exclude proposals
- admin-only controls: force train-only, force paper-only, force disabled, override confirmations
- safety gates: dangerous override confirmation + audit + rollback value required
- underlying API/data source: discovery service, scoring engine, universe registry, audit ledger

2. Adaptive Selection Engine page (required)
- purpose: explain symbol ranking and selection decisions for training/trading universes
- visible data: ranking inputs/weights, selected/rejected candidates, capacity constraints, confidence/performance trends
- controls: what-if simulation (read-only), candidate review queue
- admin-only controls: policy weight updates, approval of high-impact selection policies
- safety gates: staged validation + approval + rollback plan
- underlying API/data source: selection engine API, performance telemetry, policy config store

3. AI Governance Console page (required)
- purpose: supervise Claude/Codex/Ollama actions and recommendations under risk-level governance
- visible data: every AI recommendation/action with `change_id`, actor, reason, evidence pointers, before/after values, risk level, validation result, rollback plan, timestamp, approval state
- controls: approve/reject queued AI actions by policy scope
- admin-only controls: risk-level policy thresholds, preapproval profiles, emergency deny-all for autonomous actions
- safety gates: risk-level authorization matrix (L0-L5), mandatory human approval for dangerous levels
- underlying API/data source: AI governance ledger, review packet store, approval workflow API

4. Claude/Codex/Ollama Review Center extension (required)
- must explicitly show:
	- what was wrong
	- why AI proposed action
	- what evidence was used
	- what was changed
	- expected effect
	- rollback option
	- validation result
- no hidden AI action path is allowed outside audit/governance surfaces

## Operator vs admin policy
- Operator controls focus on supervision, diagnostics, and safe bounded actions.
- Admin-only controls include dangerous changes, live unlocks, security policy changes, and production deployment controls.

## Pre-architecture acceptance
- All listed pages retained in V2 scope.
- Each page has concrete data source and safety gates.
- No placeholder-only page remains in release plan.
- Passive discovery, adaptive selection, and AI governance page requirements are included and bound to actual data/control APIs.
