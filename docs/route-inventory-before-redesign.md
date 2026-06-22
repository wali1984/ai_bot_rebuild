# Route Inventory (Pre-redesign)
Generated: 2026-06-12T22:05:22.111Z

## Canonical route map from `router.tsx`, `registry.ts`, and `productNavigation.ts`

| id | raw path | resolved path | surface | minRole | nav category | class | notes |
|---|---|---|---|---|---|---|---|
| admin-war-room | /admin/war-room | /system/control-center | admin | admin | admin | ADMIN | legacy-source→/system/control-center; canonical still same as legacy target |
| ai-brain | /ai-brain | /ai-predictions/model-state | admin | viewer | trainer | ADMIN | active |
| alerts | /alerts | /alerts | app | viewer | alerts | TRADER | active |
| audit-ledger | /admin/audit-ledger | /system/audit-ledger | admin | reviewer | audit | ADMIN | legacy-source→/system/audit-ledger; canonical still same as legacy target |
| build-validation-status | /admin/build-validation-status | /system/build-validation | admin | viewer | audit | ADMIN | legacy-source→/system/build-validation; canonical still same as legacy target |
| claude-admin-ai | /admin/claude-admin-ai | /system/ai-tools | admin | reviewer | internal | ADMIN | legacy-source→/system/ai-tools; canonical still same as legacy target |
| codex-review-center | /admin/codex-review-center | /system/build-code-review | admin | reviewer | admin | ADMIN | legacy-source→/system/build-code-review; canonical still same as legacy target |
| config-admin | /admin/config-admin | /system/config | admin | reviewer | admin | ADMIN | legacy-source→/system/config; canonical still same as legacy target |
| config-admin-alias | /admin/config | /admin/config | admin | reviewer | internal | ADMIN | legacy-source→/system/config; duplicate alias route |
| coverage-system-atlas | /admin/coverage-system-atlas | /system/coverage | admin | reviewer | observability | ADMIN | legacy-source→/system/coverage; canonical still same as legacy target |
| exchange-manager | /admin/exchange-manager | /system/exchanges | admin | reviewer | market | ADMIN | legacy-source→/system/exchanges; canonical still same as legacy target |
| execution-admin | /admin/execution-admin | /system/execution | admin | reviewer | execution | ADMIN | legacy-source→/system/execution; canonical still same as legacy target |
| executions | /admin/executions | /portfolio/executions | admin | viewer | execution | ADMIN | legacy-source→/portfolio/executions; canonical still same as legacy target |
| executive-status | /admin/executive-status | /system/executive-summary | admin | viewer | audit | ADMIN | legacy-source→/system/executive-summary; canonical still same as legacy target |
| external-manual-position-quarantine | /admin/external-manual-position-quarantine | /system/position-quarantine | admin | viewer | risk | ADMIN | legacy-source→/system/position-quarantine; canonical still same as legacy target |
| history | /history | /portfolio/history | admin | viewer | audit | ADMIN | legacy-source→/portfolio/history; canonical still same as legacy target |
| ingestors | /admin/ingestors | /system/ingestors | admin | viewer | data | ADMIN | legacy-source→/system/ingestors; canonical still same as legacy target |
| liquidation-bridge | /admin/liquidation-bridge | /derivatives | admin | viewer | data | ADMIN | legacy-source→/derivatives; canonical still same as legacy target |
| live-readiness | /admin/live-readiness | /system/readiness | admin | reviewer | risk | ADMIN | legacy-source→/system/readiness; canonical still same as legacy target |
| login | /login | /login | public | public | public | PUBLIC | active |
| logs-errors | /admin/logs-errors | /system/logs | admin | viewer | observability | ADMIN | legacy-source→/system/logs; canonical still same as legacy target |
| market | /market | /market/:symbol? | public | public | public | PUBLIC | active |
| market-intelligence | /admin/market-intelligence | /research | admin | viewer | market | ADMIN | legacy-source→/research; canonical still same as legacy target |
| markets | /markets | /markets | public | public | public | PUBLIC | active |
| mission-control | /admin/mission-control | /dashboard | admin | viewer | overview | ADMIN | legacy-source→/dashboard; canonical still same as legacy target |
| mobile-iphone-readiness | /admin/mobile-iphone-readiness | /system/readiness/mobile | admin | reviewer | internal | ADMIN | legacy-source→/system/readiness/mobile; canonical still same as legacy target |
| monitor-center | /admin/monitor-center | /system/health | admin | viewer | observability | ADMIN | legacy-source→/system/health; canonical still same as legacy target |
| ollama-local-assistant | /admin/ollama-local-assistant | /admin/ollama-local-assistant | admin | reviewer | internal | ADMIN | legacy-source→/system/ai-tools; legacy path no longer canonical |
| operator-proof-dashboard | /admin/operator-proof-dashboard | /system/evidence | admin | viewer | admin | ADMIN | legacy-source→/system/evidence; canonical still same as legacy target |
| orchestrator-admin | /admin/orchestrator-admin | /system/orchestrator | admin | reviewer | trainer | ADMIN | legacy-source→/system/orchestrator; canonical still same as legacy target |
| paper-trading | /admin/paper-trading | /trade/paper | admin | viewer | execution | ADMIN | legacy-source→/trade/paper; canonical still same as legacy target |
| permanent-migration | /admin/permanent-migration | /system/migrations | admin | viewer | internal | ADMIN | legacy-source→/system/migrations; canonical still same as legacy target |
| positions | /admin/positions | /portfolio | admin | viewer | execution | ADMIN | legacy-source→/portfolio; canonical still same as legacy target |
| public-landing | /landing-legacy | /landing-legacy | public | public | public | PUBLIC | legacy-source→/landing; legacy path no longer canonical |
| public-landing-v2 | /landing | /landing | public | public | internal | PUBLIC | active |
| public-status | /status | /status | public | public | public | PUBLIC | active |
| replay | /admin/replay | /backtests/replay | admin | viewer | execution | ADMIN | legacy-source→/backtests/replay; canonical still same as legacy target |
| report-center | /admin/report-center | /system/reports | admin | viewer | audit | ADMIN | legacy-source→/system/reports; canonical still same as legacy target |
| risk-control | /admin/risk-control | /system/risk-controllers | admin | reviewer | risk | ADMIN | legacy-source→/system/risk-controllers; canonical still same as legacy target |
| script-registry | /admin/script-registry | /system/scripts | admin | reviewer | observability | ADMIN | legacy-source→/system/scripts; canonical still same as legacy target |
| signal-explainability | /admin/signal-explainability | /admin/signal-explainability | admin | viewer | trainer | ADMIN | legacy-source→/signals; legacy path no longer canonical |
| signals | /admin/signals | /signals | admin | viewer | execution | ADMIN | legacy-source→/signals; canonical still same as legacy target |
| strategy-admin | /admin/strategy-admin | /system/strategy-controls | admin | reviewer | trainer | ADMIN | legacy-source→/system/strategy-controls; canonical still same as legacy target |
| strategy-backtesting | /admin/strategy-backtesting | /backtests | admin | reviewer | execution | ADMIN | legacy-source→/backtests; canonical still same as legacy target |
| symbols | /admin/symbols | /markets/symbols | admin | viewer | market | ADMIN | legacy-source→/markets/symbols; canonical still same as legacy target |
| system-health | /admin/system-health | /system | admin | viewer | observability | ADMIN | legacy-source→/system; canonical still same as legacy target |
| technical-analysis | /admin/technical-analysis | /research/technical-analysis | admin | viewer | data | ADMIN | legacy-source→/research/technical-analysis; canonical still same as legacy target |
| trader | /trader | /trade | admin | viewer | execution | ADMIN | legacy-source→/trade; canonical still same as legacy target |
| trainer-admin | /admin/trainer-admin | /system/trainer | admin | reviewer | trainer | ADMIN | legacy-source→/system/trainer; canonical still same as legacy target |
| trainer-prediction-monitor | /admin/trainer-prediction-monitor | /ai-predictions | admin | viewer | trainer | ADMIN | legacy-source→/ai-predictions; canonical still same as legacy target |
| user-status | /status-simple | /system/users | public | viewer | internal | PUBLIC | legacy-source→/system/users; canonical still same as legacy target |

## Legacy redirects (explicit in `MERGED_LEGACY_PATHS`)

| legacy path | mapped path | status |
|---|---|---|
| /admin | /dashboard | mapped |
| /admin/mission-control | /dashboard | mapped |
| /admin/war-room | /system/control-center | mapped |
| /admin/permanent-migration | /system/migrations | mapped |
| /admin/monitor-center | /system/health | mapped |
| /admin/coverage-system-atlas | /system/coverage | mapped |
| /admin/script-registry | /system/scripts | mapped |
| /admin/trainer-prediction-monitor | /ai-predictions | mapped |
| /admin/signal-explainability | /signals | mapped |
| /admin/symbols | /markets/symbols | mapped |
| /admin/market-intelligence | /research | mapped |
| /admin/ai-brain | /ai-predictions/model-state | mapped |
| /admin/signals | /signals | mapped |
| /admin/executions | /portfolio/executions | mapped |
| /admin/positions | /portfolio | mapped |
| /admin/risk-control | /system/risk-controllers | mapped |
| /admin/exchange-manager | /system/exchanges | mapped |
| /admin/external-manual-position-quarantine | /system/position-quarantine | mapped |
| /admin/config-admin | /system/config | mapped |
| /admin/config | /system/config | mapped |
| /admin/strategy-admin | /system/strategy-controls | mapped |
| /admin/ingestors | /system/ingestors | mapped |
| /admin/technical-analysis | /research/technical-analysis | mapped |
| /admin/liquidation-bridge | /derivatives | mapped |
| /admin/strategy-backtesting | /backtests | mapped |
| /admin/logs-errors | /system/logs | mapped |
| /admin/trainer-admin | /system/trainer | mapped |
| /admin/orchestrator-admin | /system/orchestrator | mapped |
| /admin/execution-admin | /system/execution | mapped |
| /admin/paper-trading | /trade/paper | mapped |
| /admin/replay | /backtests/replay | mapped |
| /admin/audit-ledger | /system/audit-ledger | mapped |
| /admin/system-health | /system | mapped |
| /admin/live-readiness | /system/readiness | mapped |
| /admin/claude-admin-ai | /system/ai-tools | mapped |
| /admin/ollama-local-assistant | /system/ai-tools | mapped |
| /admin/codex-review-center | /system/build-code-review | mapped |
| /admin/report-center | /system/reports | mapped |
| /admin/executive-status | /system/executive-summary | mapped |
| /admin/build-validation-status | /system/build-validation | mapped |
| /admin/operator-proof-dashboard | /system/evidence | mapped |
| /admin/mobile-iphone-readiness | /system/readiness/mobile | mapped |
| /trader | /trade | mapped |
| /history | /portfolio/history | mapped |
| /status-simple | /system/users | mapped |
| /landing-legacy | /landing | mapped |
