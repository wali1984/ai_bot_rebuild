# Admin Route Consolidation Map

Generated: 2026-06-23  
Branch: claude/website-admin-final

This is the authoritative mapping from every legacy or redundant route to its canonical destination.  
All legacy routes emit a 301 redirect. Tab query parameter preserves deep-link context.

---

## Canonical Admin IA (Final)

### Primary Navigation (10 entries)

| # | Label | Canonical Route | Role Min | Source Pages Absorbed |
|---|---|---|---|---|
| 1 | Overview | `/admin` | admin | admin-war-room, system-health (summary), monitor-center (summary) |
| 2 | Data | `/admin/data` | reviewer | ingestors, monitor-center (detail), coverage (summary) |
| 3 | Intelligence | `/admin/intelligence` | reviewer | trainer-admin, trainer-prediction-monitor, ai-brain/model-state, signal-explainability |
| 4 | Orchestration | `/admin/orchestration` | admin | orchestrator-admin, strategy-admin/traders |
| 5 | Risk & Readiness | `/admin/risk` | admin | risk-control, live-readiness, mobile-iphone-readiness, external-manual-position-quarantine |
| 6 | Execution | `/admin/execution` | admin | execution-admin |
| 7 | Exchanges | `/admin/exchanges` | reviewer | exchange-manager |
| 8 | Configuration | `/admin/config` | admin | config-admin, config (alias) |
| 9 | Users | `/admin/users` | admin | user-status (admin surface), session management |
| 10 | Reports | `/admin/reports` | reviewer | report-center, executive-status, operator-proof-dashboard/evidence |

### Secondary Navigation (always visible, collapsed by default for Tools)

| Label | Canonical Route | Role Min | Source Pages Absorbed |
|---|---|---|---|
| Logs | `/admin/logs` | reviewer | logs-errors |
| Audit | `/admin/audit` | superadmin | audit-ledger |
| Developer Tools | `/admin/tools` | superadmin | script-registry, build-validation-status, coverage-system-atlas, permanent-migration, claude-admin-ai, ollama-local-assistant, codex-review-center |

---

## Full Redirect Table

| From (Legacy Route) | To (Canonical) | Tab Hint | Reason |
|---|---|---|---|
| `/admin/system` | `/admin` | — | system-health merged into Overview |
| `/admin/monitor-center` | `/admin/data` | `?tab=monitors` | Monitor Center merged into Data |
| `/admin/ingestors` | `/admin/data` | — | Ingestors merged into Data |
| `/admin/trainer` | `/admin/intelligence` | — | Trainer merged into Intelligence |
| `/admin/trainer-prediction-monitor` | `/admin/intelligence` | `?tab=predictions` | Prediction monitor merged into Intelligence |
| `/admin/model-state` | `/admin/intelligence` | `?tab=model` | Model state merged into Intelligence |
| `/admin/signal-explainability` | `/admin/intelligence` | `?tab=signals` | Signal explainability merged into Intelligence |
| `/admin/orchestrator` | `/admin/orchestration` | — | Canonical rename |
| `/admin/traders` | `/admin/orchestration` | `?tab=traders` | Traders is an orchestration sub-section |
| `/admin/readiness` | `/admin/risk` | `?tab=readiness` | Readiness merged into Risk |
| `/admin/readiness/mobile` | `/admin/risk` | `?tab=mobile` | Mobile readiness is sub-section |
| `/admin/external-manual-position-quarantine` | `/admin/risk` | `?tab=quarantine` | Quarantine merged into Risk |
| `/system/executive-summary` | `/admin/reports` | `?tab=executive` | Executive summary is a report |
| `/admin/evidence` | `/admin/reports` | `?tab=evidence` | Evidence dashboard merged into Reports |
| `/admin/scripts` | `/admin/tools` | — | Developer tool |
| `/admin/build-validation` | `/admin/tools` | — | Developer tool |
| `/admin/coverage` | `/admin/tools` | — | Developer tool |
| `/admin/migrations` | `/admin/tools` | — | Developer tool |
| `/admin/ai-tools` | `/admin/tools` | — | Developer tool |
| `/system/build-code-review` | `/admin/tools` | — | Developer tool |
| `/admin/war-room` | `/admin` | — | Canonical rename |
| `/admin/risk-control` | `/admin/risk` | — | Canonical rename |
| `/admin/orchestrator-admin` | `/admin/orchestration` | — | Canonical rename |
| `/admin/config-admin` | `/admin/config` | — | Canonical rename |
| `/admin/exchange-manager` | `/admin/exchanges` | — | Canonical rename |
| `/admin/strategy-admin` | `/admin/orchestration` | `?tab=traders` | Moved to orchestration |
| `/admin/execution-admin` | `/admin/execution` | — | Canonical rename |
| `/admin/logs-errors` | `/admin/logs` | — | Canonical rename |
| `/admin/audit-ledger` | `/admin/audit` | — | Canonical rename |
| `/admin/report-center` | `/admin/reports` | — | Canonical rename |
| `/admin/claude-admin-ai` | `/admin/tools` | — | Merged into tools |
| `/admin/ollama-local-assistant` | `/admin/tools` | — | Merged into tools |
| `/admin/codex-review-center` | `/admin/tools` | — | Merged into tools |
| `/admin/build-validation-status` | `/admin/tools` | — | Merged into tools |
| `/admin/script-registry` | `/admin/tools` | — | Merged into tools |
| `/admin/coverage-system-atlas` | `/admin/tools` | — | Merged into tools |
| `/admin/permanent-migration` | `/admin/tools` | — | Merged into tools |
| `/admin/live-readiness` | `/admin/risk` | `?tab=readiness` | Merged into Risk |
| `/admin/mobile-iphone-readiness` | `/admin/risk` | `?tab=mobile` | Merged into Risk |
| `/admin/executive-status` | `/admin/reports` | `?tab=executive` | Merged into Reports |
| `/system/control-center` | `/admin` | — | Legacy alias |
| `/system/health` | `/admin` | — | Legacy alias |
| `/system/risk-controllers` | `/admin/risk` | — | Legacy alias |
| `/system/exchanges` | `/admin/exchanges` | — | Legacy alias |
| `/system/position-quarantine` | `/admin/risk` | `?tab=quarantine` | Legacy alias |
| `/system/config` | `/admin/config` | — | Legacy alias |
| `/system/logs` | `/admin/logs` | — | Legacy alias |
| `/system/trainer` | `/admin/intelligence` | — | Legacy alias |
| `/system/orchestrator` | `/admin/orchestration` | — | Legacy alias |
| `/system/execution` | `/admin/execution` | — | Legacy alias |
| `/system/audit-ledger` | `/admin/audit` | — | Legacy alias |
| `/system/readiness` | `/admin/risk` | `?tab=readiness` | Legacy alias |
| `/system/ai-tools` | `/admin/tools` | — | Legacy alias |
| `/system/reports` | `/admin/reports` | — | Legacy alias |
| `/system/build-validation` | `/admin/tools` | — | Legacy alias |
| `/system/evidence` | `/admin/reports` | `?tab=evidence` | Legacy alias |
| `/system/readiness/mobile` | `/admin/risk` | `?tab=mobile` | Legacy alias |
| `/system` | `/admin` | — | Legacy alias |
| `/system/strategy-controls` | `/admin/orchestration` | `?tab=traders` | Legacy alias |
| `/system/ingestors` | `/admin/data` | — | Legacy alias |

---

## Pages Removed

Pages whose routes are fully redirected and whose components serve no unique function once tabs exist in the canonical page. Components are preserved in the filesystem as redirect stubs until all imports are removed.

- `pages/system-health` — redirected to `/admin`
- `pages/monitor-center` — redirected to `/admin/data`
- `pages/trainer-prediction-monitor` — redirected to `/admin/intelligence`
- `pages/ai-brain` — redirected to `/admin/intelligence`
- `pages/strategy-admin` — redirected to `/admin/orchestration`
- `pages/live-readiness` — redirected to `/admin/risk`
- `pages/mobile-iphone-readiness` — redirected to `/admin/risk`
- `pages/external-manual-position-quarantine` — redirected to `/admin/risk`
- `pages/executive-status` — redirected to `/admin/reports`
- `pages/operator-proof-dashboard` — redirected to `/admin/reports`
- `pages/script-registry` — redirected to `/admin/tools`
- `pages/build-validation-status` — redirected to `/admin/tools`
- `pages/coverage-system-atlas` — redirected to `/admin/tools`
- `pages/permanent-migration` — redirected to `/admin/tools`
- `pages/claude-admin-ai` — redirected to `/admin/tools`
- `pages/ollama-local-assistant` — redirected to `/admin/tools`
- `pages/codex-review-center` — redirected to `/admin/tools`
