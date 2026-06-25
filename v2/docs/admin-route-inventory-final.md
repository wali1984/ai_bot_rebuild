# Admin Route Inventory — Final

Generated: 2026-06-23  
Branch: claude/website-admin-final  
Mission: NERVYX ONE Admin Portal Rebuild

---

## Current Admin Routes (pre-consolidation)

| Current Route | Page ID | Title | Surface | Role | Nav Category | Unique Job | Target Route | Disposition |
|---|---|---|---|---|---|---|---|---|
| `/admin` | admin-war-room | Ops Center | system | admin | control-center | War-room daemon cycles, gap/blocker matrix, safety scan | `/admin` | KEEP → becomes Overview |
| `/admin/system` | system-health | System Overview | system | reviewer | overview | System-wide service health summary | `/admin` | REDIRECT → Overview tab |
| `/admin/monitor-center` | monitor-center | Monitor Center | admin | reviewer | observability | Every monitor script status, owner, evidence | `/admin/data` | REDIRECT → Data tab:monitors |
| `/admin/ingestors` | ingestors | Ingestors | admin | reviewer | data | Live ingestor status, heartbeat, symbols, Redis | `/admin/data` | REDIRECT → Data |
| `/admin/trainer` | trainer-admin | Trainer | system | admin | trainer | Trainer config, checkpoint state, training job | `/admin/intelligence` | REDIRECT → Intelligence |
| `/admin/trainer-prediction-monitor` | trainer-prediction-monitor | Trainer Prediction Monitor | admin | reviewer | trainer | Evidence packets, prediction matrix, realized-vs-predicted | `/admin/intelligence` | REDIRECT → Intelligence tab:predictions |
| `/admin/model-state` | ai-brain | Model State | system | reviewer | predictions | Model health, forecast quality, uncertainty | `/admin/intelligence` | REDIRECT → Intelligence tab:model |
| `/admin/signal-explainability` | signal-explainability | Signal Explainability | admin | reviewer | signals | Per-signal input, features, raw model output | `/admin/intelligence` | REDIRECT → Intelligence tab:signals |
| `/admin/orchestrator` | orchestrator-admin | Orchestrator | system | admin | orchestrator | Orchestrator runtime, queues, dependency state | `/admin/orchestration` | REDIRECT → Orchestration |
| `/admin/traders` | strategy-admin | Traders | admin | admin | traders | Bot/trader operational view, strategy routing | `/admin/orchestration` | REDIRECT → Orchestration tab:traders |
| `/admin/risk` | risk-control | Risk Controllers | admin | admin | risk-controllers | Risk rules, thresholds, block counts, kill switch | `/admin/risk` | KEEP → Risk & Readiness |
| `/admin/readiness` | live-readiness | Readiness | admin | admin | readiness | GO/NO-GO criteria, L4/L5 controls | `/admin/risk` | REDIRECT → Risk tab:readiness |
| `/admin/readiness/mobile` | mobile-iphone-readiness | Mobile Readiness | system | admin | readiness | PWA + RN/SwiftUI bridge readiness | `/admin/risk` | REDIRECT → Risk tab:mobile |
| `/admin/external-manual-position-quarantine` | external-manual-position-quarantine | Position Quarantine | admin | admin | quarantine | Manual/external position ownership classification | `/admin/risk` | REDIRECT → Risk tab:quarantine |
| `/admin/execution` | execution-admin | Execution Control | admin | admin | execution | Execution router, fills, rejects, latency, reconciliation | `/admin/execution` | KEEP |
| `/admin/exchanges` | exchange-manager | Exchanges | admin | reviewer | exchanges | Exchange connectivity, REST/WS status, credentials | `/admin/exchanges` | KEEP |
| `/admin/config` | config-admin | Config | admin | admin | config | Versioned config, diff, rollback, validation | `/admin/config` | KEEP |
| `/admin/logs` | logs-errors | Logs | system | reviewer | logs | Structured event logs, error counts, incident history | `/admin/logs` | KEEP |
| `/admin/audit` | audit-ledger | Audit Ledger | system | superadmin | audit-ledger | Append-only governance event chain | `/admin/audit` | KEEP |
| `/admin/reports` | report-center | Reports | system | reviewer | reports | Report index, lane status, export history | `/admin/reports` | KEEP |
| `/system/executive-summary` | executive-status | Executive Summary | system | reviewer | executive-summary | Plain-English truth: migrated? live-ready? blockers? | `/admin/reports` | REDIRECT → Reports tab:executive |
| `/admin/evidence` | operator-proof-dashboard | Evidence | admin | reviewer | evidence | Operator proof dashboard, historical evidence | `/admin/reports` | REDIRECT → Reports tab:evidence |
| `/admin/scripts` | script-registry | Scripts | system | superadmin | scripts | Script registry, usage evidence | `/admin/tools` | REDIRECT → Tools |
| `/admin/build-validation` | build-validation-status | Build Validation | admin | superadmin | build-validation | Build artifact states, READY/BLOCKED | `/admin/tools` | REDIRECT → Tools |
| `/admin/coverage` | coverage-system-atlas | Coverage | system | superadmin | coverage | File inventory, classification, system atlas | `/admin/tools` | REDIRECT → Tools |
| `/admin/migrations` | permanent-migration | Migrations | system | superadmin | migrations | Schema/data migration history | `/admin/tools` | REDIRECT → Tools |
| `/admin/ai-tools` | claude-admin-ai | AI Tools | system | superadmin | ai-tools | Claude supervision, Ollama local assistant | `/admin/tools` | REDIRECT → Tools |
| `/system/build-code-review` | codex-review-center | Build / Code Review | system | superadmin | build-code-review | Codex review status across milestones | `/admin/tools` | REDIRECT → Tools |
| `/admin/users` | (new) | Users | admin | admin | users | User list, roles, sessions, account state | `/admin/users` | NEW |
| `/admin/tools` | (new) | Developer Tools | system | superadmin | tools | Scripts, build, coverage, migrations, AI tools, Codex | `/admin/tools` | NEW (consolidation) |
| `/admin/data` | (new) | Data | admin | reviewer | data | Ingestors + monitors + pipeline health + source freshness | `/admin/data` | NEW (consolidation) |
| `/admin/intelligence` | (new) | Intelligence | admin | reviewer | intelligence | Trainer + predictions + model state + signal explainability | `/admin/intelligence` | NEW (consolidation) |
| `/admin/orchestration` | (new) | Orchestration | admin | admin | orchestration | Orchestrator + traders + strategy routing + queues | `/admin/orchestration` | NEW (consolidation) |

---

## Non-Admin Pages (excluded from admin IA)

| Route | Page | Surface | Note |
|---|---|---|---|
| `/dashboard` | mission-control | app | Trader dashboard — not admin |
| `/trade` | trader | app | Trade terminal — not admin |
| `/portfolio` | positions | app | Portfolio — not admin |
| `/portfolio/executions` | executions | app | Trader executions — not admin |
| `/portfolio/history` | history | app | Trade history — not admin |
| `/signals` | signals | app | Trader signals — not admin |
| `/ai-predictions` | ai-predictions | app | Trader predictions — not admin |
| `/research` | market-intelligence | app | Research — not admin |
| `/backtests` | strategy-backtesting | app | Backtests — not admin |
| `/replay` | replay | app | Replay — not admin |
| `/alerts` | alerts | app | Alerts — not admin |
| `/derivatives` | liquidation-bridge | app | Derivatives — not admin |
| `/markets` | markets | public | Markets screener — public |
| `/market/:symbol?` | market | app | Market detail — app |
| `/landing` | public-landing-v2 | public | Landing — public |
| `/status` | public-status | public | Public status — public |
| `/login` | login | public | Login — public |
| `/account-settings` | account-settings | app | Account settings — app |
| `/status-simple` | user-status | public | Simple status — public |

---

## Summary

- Total admin routes (current): 28
- Routes to KEEP with same canonical path: 7 (`/admin`, `/admin/execution`, `/admin/exchanges`, `/admin/config`, `/admin/logs`, `/admin/audit`, `/admin/reports`)
- Routes to REDIRECT (consolidate into canonical pages): 15
- Routes to CREATE NEW: 6 (`/admin/data`, `/admin/intelligence`, `/admin/orchestration`, `/admin/risk` expansion, `/admin/users`, `/admin/tools`)
- Final canonical admin entry count: 13 (10 primary + Logs + Audit + Tools)
