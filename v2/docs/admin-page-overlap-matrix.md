# Admin Page Overlap Matrix

Generated: 2026-06-23  
Branch: claude/website-admin-final

A page pair scores >60% overlap when displayed metrics, data sources, or operational controls belong to the same workflow.  
Pairs above 60% are merged into a single canonical page.

---

## Overlap Scores

| Page A | Page B | Overlap % | Reason | Decision |
|---|---|---|---|---|
| `/admin` (Ops Center) | `/admin/system` (System Overview) | 85% | Both show global service health, live-gate status, mode, incident counts | MERGE → `/admin` Overview |
| `/admin` (Ops Center) | `/admin/monitor-center` (Monitor Center) | 70% | Both summarize script/service health and alerts | MERGE summary → `/admin`, detail → `/admin/data` |
| `/admin/ingestors` | `/admin/monitor-center` | 75% | Monitor Center includes ingestor status rows; Ingestors page duplicates freshness/heartbeat columns | MERGE → `/admin/data` |
| `/admin/trainer` | `/admin/trainer-prediction-monitor` | 80% | Trainer config + prediction stream belong to the same trainer operational workflow | MERGE → `/admin/intelligence` |
| `/admin/trainer` | `/admin/model-state` | 90% | Model State is a subset of Trainer Admin's model health section | MERGE → `/admin/intelligence` tab:model |
| `/admin/trainer-prediction-monitor` | `/admin/signal-explainability` | 65% | Both show signal causality, feature freshness, model output; differ only in entry point | MERGE → `/admin/intelligence` tab:signals |
| `/admin/orchestrator` | `/admin/traders` | 80% | Strategy routing and trader bot status are orchestration sub-components | MERGE → `/admin/orchestration` |
| `/admin/readiness` | `/admin/risk` | 75% | Live-readiness GO/NO-GO depends on risk gate status; controls share kill-switch and approval flow | MERGE → `/admin/risk` tab:readiness |
| `/admin/readiness/mobile` | `/admin/readiness` | 82% | Mobile readiness is a sub-section of the readiness wizard | MERGE → `/admin/risk` tab:mobile |
| `/admin/external-manual-position-quarantine` | `/admin/risk` | 70% | Quarantine state feeds into risk controller decisions | MERGE → `/admin/risk` tab:quarantine |
| `/system/executive-summary` | `/admin/reports` | 80% | Executive summary is a report type; shares export, lane status, GO/NO-GO fields | MERGE → `/admin/reports` tab:executive |
| `/admin/evidence` | `/admin/reports` | 72% | Evidence dashboard is report evidence, shares operator payload fields | MERGE → `/admin/reports` tab:evidence |
| `/admin/scripts` | `/admin/build-validation` | 65% | Both are developer/superadmin tools about build artifacts and script health | MERGE → `/admin/tools` |
| `/admin/coverage` | `/admin/build-validation` | 68% | Coverage atlas and build validation share file inventory and classifier state | MERGE → `/admin/tools` |
| `/admin/ai-tools` | `/admin/scripts` | 70% | Claude/Ollama AI tools and script registry are both developer-only utilities | MERGE → `/admin/tools` |
| `/admin/migrations` | `/admin/build-validation` | 60% | Both track artifact progression state (schema migrations vs build states) | MERGE → `/admin/tools` |
| `/system/build-code-review` | `/admin/build-validation` | 75% | Codex review IS the build code review; overlaps build-validation artifact list | MERGE → `/admin/tools` |

---

## Pages with Unique Content (< 60% overlap with any other page)

| Page | Unique Content | Decision |
|---|---|---|
| `/admin/execution` | Fill routing, reject analysis, latency histogram, slippage, reconciliation | KEEP canonical |
| `/admin/exchanges` | Exchange REST/WS status, rate limits, credential state, permissions | KEEP canonical |
| `/admin/config` | Versioned config diff, rollback, dangerous-control toggle gating | KEEP canonical |
| `/admin/logs` | Structured event log stream, incident history, error aggregation | KEEP canonical |
| `/admin/audit` | Append-only governance chain (superadmin only, immutable) | KEEP canonical |

---

## Pages That Cannot Survive Merely Because They Exist

The following pages exist for historical or developer reasons and have no unique operational job that cannot be served by a tab in a canonical page:

- `/admin/system` — system-health: Every metric is a subset of Overview
- `/admin/monitor-center` — monitor-center: Data pipeline summary belongs in Data
- `/admin/trainer-prediction-monitor` — trainer-prediction-monitor: Trainer workflow belongs in Intelligence
- `/admin/model-state` — ai-brain: Trainer model state belongs in Intelligence
- `/admin/traders` — strategy-admin: Strategy routing is orchestration
- `/admin/readiness` — live-readiness: Risk gate controls belong in Risk & Readiness
- `/admin/readiness/mobile` — mobile-iphone-readiness: Sub-section of Readiness
- `/admin/external-manual-position-quarantine` — position quarantine: Risk sub-section
- `/system/executive-summary` — executive-status: Report sub-section
- `/admin/evidence` — operator-proof-dashboard: Report evidence sub-section
- `/admin/scripts` — script-registry: Developer tool
- `/admin/build-validation` — build-validation-status: Developer tool
- `/admin/coverage` — coverage-system-atlas: Developer tool detail
- `/admin/migrations` — permanent-migration: Developer tool
- `/admin/ai-tools` — claude-admin-ai: Developer tool
- `/system/build-code-review` — codex-review-center: Developer tool
