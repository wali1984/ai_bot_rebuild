# Backend API Master Audit — AI BOT V2

> **Historical snapshot — superseded by the 2026-07-16 reconstruction.** Do not use this file alone for current behavior, operations, safety, or change-impact decisions. Start with [REVERSE_ENGINEERING_INDEX.md](REVERSE_ENGINEERING_INDEX.md).
Generated: 2026-07-01T22:56:31Z

## Architecture

- **Framework**: FastAPI (Python)
- **Server**: uvicorn (ai-bot-v2-public-website-backend.service)
- **API Namespaces**: /api/v1 (legacy feature-complete), /api/v2 (new contract-based)
- **Auth**: RBAC (auth_rbac.py) + JWT
- **Total API files**: 82

## Middleware Stack (MIDDLEWARE_ORDER)

Applied outermost → innermost:
1. `request_id` — assigns unique X-Request-ID
2. `rbac` — role-based access control
3. `rate_limit` — per-route rate limiting
4. `ip_allowlist` — IP whitelist enforcement
5. `live_block_guard` — blocks all mutation if live trading disabled
6. `lineage_validator` — validates lineage IDs on mutation requests
7. `idempotency` — idempotency key handling
8. `step_up_mfa` — step-up MFA for dangerous operations
9. `approval` — human approval gate for dangerous mutations
10. `db_error_translator` — converts DB errors to API envelopes

## V1 API Routers

| Router | Prefix | Description |
|--------|--------|-------------|
| auth | /auth | JWT login, refresh, logout |
| accounts | /accounts | Exchange account read-only status |
| audit | /audit | Audit events and chain |
| chart | /chart | Market chart data |
| claude_admin | /claude-admin | Claude AI admin interface |
| codex_review | /codex | Codex review results |
| config_admin | /config-admin | Config management (versioned) |
| decisions | /decisions | Orchestrator decisions |
| derivatives | /derivatives | Funding/OI/long-short data |
| discovery | /discovery | Symbol discovery status |
| evidence | /evidence | Audit evidence |
| exchanges | /exchanges | Exchange status |
| features | /feature-snapshots | Feature snapshot data |
| fleet | /fleet | Multi-service fleet status |
| governance | /governance | Governance and approval records |
| health | /_meta/health | System health check |
| ingestors | /ingestors | Ingestor status |
| intents | /execution-intents | Paper execution intents |
| live_gate | /live-gate | Live gate status (read-only) |
| live_mode | /live | Live mode status |
| live_readiness | /live-readiness | Live readiness checklist |
| mission_control | /mission-control | Mission control summary |
| monitor | /monitor | Monitor center status |
| ollama_assistant | /ollama | Ollama local assistant |
| paper | /paper-trades | Paper trades, positions, PnL |
| predictions | /predictions | Trainer predictions |
| replay | /replay | Replay runner |
| risk | /risk | Risk gateway status |
| risk_decisions | /risk-decisions | Risk decision history |
| selection | /selection | Symbol/strategy selection |
| signals | /signals | Signal status |
| universe | /universe | Symbol universe |

## V2 API Routers

| Router | Prefix | Description |
|--------|--------|-------------|
| admin | /admin | Admin controls + approval gate |
| alerts_contracts | /alerts | Alert contracts |
| audit_ledger | /audit-ledger | Structured audit ledger events |
| brand | /brand | Brand/UI config |
| codex_reviews | /codex | Codex review center |
| hourly_monitor | /monitor/hourly | Hourly monitoring snapshot |
| live_gate_status | /live-gate-status | Live gate status (V2 format) |
| live_readiness | /live-readiness | Live readiness (V2 format) |
| market_contracts | /market | Market data contracts + SSE stream |
| mobile | /mobile | Mobile app API endpoints |
| monitoring_contracts | /monitoring | Monitoring contract data |
| ollama | /ollama | Ollama V2 assistant |
| pipeline | /pipeline | Pipeline control status |
| public_status | /public | Public status page |
| replay | /replay | Replay V2 |
| status_contracts | /status | Status contract data |
| trader_snapshot | /trader | Trader snapshot |
| trainer | /trainer | Trainer status + metrics |
| truthful_status | /truthful-status | Truthful runtime status |

## Key Route Details

### Mutation Endpoints (Dangerous — require approval + MFA)
- `POST /config-admin/update` — config version update
- `POST /live-gate` — live gate state update (BLOCKED by live_block_guard unless live enabled)
- `POST /admin/controls/{id}` — admin control approval
- `POST /governance/approve` — governance approval
- `POST /paper-fill-gate/open` / `close` — paper fill gate control

### Read-Only Endpoints (Safe)
- `GET /health` / `GET /_meta/health` — system health
- `GET /predictions` — current predictions
- `GET /signals` — current signals
- `GET /paper-trades` — paper position/PnL
- `GET /risk` — risk gateway status
- `GET /trainer` — trainer status
- `GET /ingestors` — ingestor status
- `GET /market` — market chart data (+ SSE stream)
- `GET /mobile/*` — 10 mobile API endpoints

## Safety Classification Summary

| Classification | Count |
|---------------|-------|
| Read-only endpoints | ~80% |
| Mutation endpoints (approval required) | ~20% |
| Exchange mutation endpoints | 0 (all blocked) |
| Live trade submission endpoints | 0 (blocked by live_block_guard) |

## Known Stub Routes (from prior API gap audit)
Approximately 28 stub routes exist where the handler returns empty/placeholder data rather than live data. These are documented in `docs/api-gap-register.md`.

## Mobile API
- 10 endpoints at `/api/v2/mobile/*`
- Serves SwiftUI iOS app (build 5 in TestFlight)
- All endpoints: read-only status/dashboard data
