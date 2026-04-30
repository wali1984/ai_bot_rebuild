# 06 Enterprise GUI UX Architecture

## UX principles
- Professional enterprise UI.
- Polished animations and transitions.
- Uncluttered information hierarchy.
- No demo/sample widgets.
- Every page connected to real data/control APIs.
- Operator/Admin/Public-safe surface separation.
- Dark/light themes.
- Responsive and mobile/PWA-ready.

## Page architecture

### Mission Control
- purpose: global control/status
- data: health, alerts, readiness
- controls: safe runtime actions
- admin-only: emergency policy overrides
- safety gates: RBAC + readiness
- source: monitor + health APIs

### Market Universe Manager
- purpose: symbol CRUD and state
- data: universe members, versions, scores
- controls: add/remove/update symbols
- admin-only: force apply/rollback
- safety gates: approval + audit
- source: universe + scoring APIs

### Passive Market Discovery
- purpose: all-market passive visibility
- data: available/observed universes, ingestor coverage
- controls: filters
- admin-only: discovery policy edits
- safety gates: approval for policy changes
- source: discovery service

### Adaptive Selection Engine
- purpose: ranked selection transparency
- data: ranks, capacities, selection outcomes
- controls: read-only what-if
- admin-only: weight/policy changes
- safety gates: staged validation
- source: selection engine API

### Exchange Manager
- purpose: exchange/connector management
- data: connector health/capabilities
- controls: safe connector toggles
- admin-only: credential/live endpoint settings
- safety gates: RBAC
- source: connector APIs

### Ingestor Manager
- purpose: ingestion supervision
- data: lag/freshness/uptime
- controls: operational non-live actions
- admin-only: topology edits
- safety gates: policy + approval
- source: ingestor telemetry

### Feature Flow Map
- purpose: feature lineage graph
- data: source-to-feature pathways
- controls: tracing filters
- admin-only: pipeline policy updates
- safety gates: approval
- source: lineage APIs

### Feature Freshness Monitor
- purpose: stale/missing feature detection
- data: freshness ages and coverage
- controls: threshold display filters
- admin-only: threshold policy mutation
- safety gates: RBAC
- source: monitor + feature APIs

### Trainer Control Center
- purpose: trainer mode/health
- data: trainer status/cadence/checkpoint
- controls: bounded safe toggles
- admin-only: advanced policy changes
- safety gates: non-live + approvals
- source: trainer adapter + health

### Prediction Monitor
- purpose: prediction throughput/quality
- data: rates, confidence distributions
- controls: filters/time range
- admin-only: retention policy updates
- safety gates: RBAC
- source: prediction APIs

### Signal Explainability
- purpose: signal-level explanations
- data: drivers, freshness, lineage IDs
- controls: compare/drill-down
- admin-only: explainability policy changes
- safety gates: lineage completeness rules
- source: explainability APIs

### Confidence Driver Breakdown
- purpose: confidence movement analysis
- data: before/after + top +/- contributors
- controls: scenario compare
- admin-only: model weighting policy
- safety gates: approval + audit
- source: confidence APIs

### Orchestrator Control
- purpose: orchestration supervision
- data: proposals, arbitration outcomes
- controls: safe non-live flow controls
- admin-only: arbitration policy mutation
- safety gates: risk gateway + approval
- source: orchestrator adapter

### Risk Gateway
- purpose: final risk authority visibility
- data: allow/block decisions and reasons
- controls: diagnostics only (operator)
- admin-only: risk policy edits
- safety gates: strict approvals
- source: risk APIs

### Trader Fleet Manager
- purpose: manage trader instances
- data: heartbeats, PnL, assignment, attribution
- controls: add/remove/reassign in paper-safe mode
- admin-only: live-mode changes
- safety gates: readiness + risk policy
- source: fleet APIs

### Execution Monitor
- purpose: execution outcomes
- data: fills/latency/skip reasons
- controls: triage filters
- admin-only: execution policy overrides
- safety gates: live gates + RBAC
- source: execution APIs

### Positions/Portfolio
- purpose: account exposure view
- data: positions, exposure, drawdown
- controls: safe protective requests
- admin-only: high-risk overrides
- safety gates: no-loss + risk gateway
- source: portfolio + risk APIs

### Redis/Storage Health
- purpose: storage safety monitoring
- data: memory ratio/retention pressure
- controls: read-only diagnostics
- admin-only: retention policy updates
- safety gates: approval required
- source: monitor/storage APIs

### Continuous Monitor Dashboard
- purpose: runtime evidence dashboard
- data: hourly/daily/alert packets, liveness
- controls: inspect/refresh
- admin-only: alert policy edits
- safety gates: read-only default
- source: evidence packet store

### Audit Ledger
- purpose: immutable action history
- data: actor/action/diff/evidence
- controls: search/export
- admin-only: retention/legal-hold policy
- safety gates: tamper-evidence
- source: audit DB

### Config Admin
- purpose: config lifecycle control
- data: config versions/diffs/state
- controls: propose config changes
- admin-only: approve/apply/rollback
- safety gates: staged validation
- source: config APIs

### Replay/Paper Trading
- purpose: safe validation environment
- data: replay runs, paper PnL
- controls: start/stop replay and paper tests
- admin-only: candidate-live promotion requests
- safety gates: replay pass criteria
- source: replay/paper services

### Claude/Codex/Ollama Review Center
- purpose: AI-assisted analysis
- data: review packets and recommendations
- controls: generate/triage packets
- admin-only: recommendation acceptance workflow
- safety gates: human-in-loop
- source: review center APIs

### AI Governance Console
- purpose: controlled AI change governance
- data: change ledger with risk levels and approvals
- controls: approve/reject pending actions
- admin-only: risk policy profiles
- safety gates: L0-L5 governance matrix
- source: AI governance ledger API

### Live Readiness
- purpose: explicit GO/NO-GO
- data: gate checklist and blockers
- controls: run readiness validations
- admin-only: final unlock approvals
- safety gates: all mandatory gates
- source: readiness API

### Deployment/Hosting Admin
- purpose: deployment operations
- data: environments, releases, security posture
- controls: stage deployment requests
- admin-only: production deploy/rollback
- safety gates: RBAC + 2FA-ready controls
- source: deployment APIs

### Mobile/iPhone Readiness
- purpose: mobile operations quality
- data: responsive metrics and action safety coverage
- controls: mobile diagnostics
- admin-only: mobile policy toggles
- safety gates: mobile-safe approvals
- source: frontend telemetry APIs
