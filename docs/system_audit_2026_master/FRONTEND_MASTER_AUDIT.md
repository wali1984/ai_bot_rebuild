# Frontend / Website Master Audit — AI BOT V2
Generated: 2026-07-01T22:56:31Z

## Architecture

- **Framework**: React + Vite + TypeScript
- **UI**: Tailwind CSS
- **Total TS/TSX files**: 464
- **Page components**: 56 pages
- **Build**: `npm run build` → dist/
- **Serving**: FastAPI serves `dist/` as StaticFiles at root `/`
- **Mobile**: SwiftUI iOS app at `v2/mobile/` (54 Swift files, build 5 in TestFlight)

## Page Inventory

### Core Trading Pages
| Route | File | Key APIs | Runtime Payloads |
|-------|------|---------|------------------|
| /dashboard | dashboard/index.tsx | /api/v1/mission-control, /api/v2/truthful-status | Operator runtime truth |
| /markets | markets/index.tsx | /api/v2/market | Symbol universe, chart data |
| /market/:symbol | market/index.tsx | /api/v1/chart, /api/v2/market | OHLCV + TA |
| /symbols | symbols/index.tsx | /api/v1/universe | Symbol scores |
| /trader | trader/index.tsx | /api/v1/paper-trades, /api/v2/trader | Paper positions, PnL |
| /signals | signals/index.tsx | /api/v1/signals | Signal status |
| /ai-predictions | ai-predictions/index.tsx | /api/v1/predictions, /api/v2/trainer | Prediction grid |
| /positions | positions/index.tsx | /api/v1/paper-trades | Open positions |
| /executions | executions/index.tsx | /api/v1/execution-intents | Paper fills |
| /history | history/index.tsx | /api/v1/paper-trades | Closed trades |
| /paper-trading | paper-trading/index.tsx | /api/v1/paper-trades, /api/v2/trader | Paper trading status |

### Risk and Monitoring Pages
| Route | File | Key APIs |
|-------|------|---------|
| /risk-control | risk-control/index.tsx | /api/v1/risk, /api/v1/risk-decisions |
| /monitor-center | monitor-center/index.tsx | /api/v1/monitor |
| /system-health | system-health/index.tsx | /api/v1/fleet, /api/v2/monitoring-contracts |
| /ingestors | ingestors/index.tsx | /api/v1/ingestors |
| /liquidation-bridge | liquidation-bridge/index.tsx | /api/v1/ingestors (liq filter) |
| /alerts | alerts/index.tsx | /api/v2/alerts-contracts |

### Admin Pages
| Route | File | Key APIs |
|-------|------|---------|
| /config-admin | config-admin/index.tsx | /api/v1/config-admin |
| /admin-overview | admin-overview/index.tsx | /api/v2/admin |
| /admin-risk | admin-risk/index.tsx | /api/v1/risk |
| /admin-execution | admin-execution/index.tsx | /api/v1/execution-intents |
| /admin-orchestration | admin-orchestration/index.tsx | /api/v1/decisions |
| /admin-users | admin-users/index.tsx | /api/v2/admin |
| /admin-config | admin-config/index.tsx | /api/v1/config-admin |
| /admin-logs | admin-logs/index.tsx | /api/v2/monitoring-contracts |
| /admin-audit | admin-audit/index.tsx | /api/v2/audit-ledger |
| /admin-reports | admin-reports/index.tsx | /api/v2/status-contracts |
| /admin-tools | admin-tools/index.tsx | /api/v1/fleet |
| /admin-data | admin-data/index.tsx | /api/v1/ingestors |
| /admin-exchanges | admin-exchanges/index.tsx | /api/v1/exchanges |
| /admin-intelligence | admin-intelligence/index.tsx | /api/v1/discovery |
| /admin-war-room | admin-war-room/index.tsx | multiple |

### Trainer / AI Pages
| Route | File | Key APIs |
|-------|------|---------|
| /trainer-admin | trainer-admin/index.tsx | /api/v2/trainer |
| /trainer-prediction-monitor | trainer-prediction-monitor/index.tsx | /api/v1/predictions, /api/v2/trainer |
| /ai-brain | ai-brain/index.tsx | /api/v2/trainer |
| /signal-explainability | signal-explainability/index.tsx | /api/v1/signals, /api/v1/predictions |

### Analysis Pages
| Route | File | Key APIs |
|-------|------|---------|
| /technical-analysis | technical-analysis/index.tsx | /api/v1/feature-snapshots |
| /derivatives | (multiple) | /api/v1/derivatives |
| /market-intelligence | market-intelligence/index.tsx | /api/v1/discovery |
| /backtests-replay | backtests-replay/index.tsx | /api/v1/backtest |
| /strategy-backtesting | strategy-backtesting/index.tsx | /api/v1/backtest |
| /replay | replay/index.tsx | /api/v1/replay, /api/v2/replay |

### Live Gate / Readiness Pages
| Route | File | Key APIs |
|-------|------|---------|
| /live-readiness | live-readiness/index.tsx | /api/v1/live-readiness, /api/v2/live-readiness |
| /build-validation-status | build-validation-status/index.tsx | /api/v2/status-contracts |
| /coverage-system-atlas | coverage-system-atlas/index.tsx | /api/v2/status-contracts |

### Utility / Auth Pages
| Route | File | Key APIs |
|-------|------|---------|
| /login | login/index.tsx | /api/v1/auth |
| /audit-ledger | audit-ledger/index.tsx | /api/v2/audit-ledger |
| /script-registry | script-registry/index.tsx | /api/v1/fleet |
| /report-center | report-center/index.tsx | /api/v2/status-contracts |
| /claude-admin-ai | claude-admin-ai/index.tsx | /api/v1/claude-admin |
| /codex-review-center | codex-review-center/index.tsx | /api/v2/codex-reviews |
| /ollama-local-assistant | ollama-local-assistant/index.tsx | /api/v2/ollama |
| /public-status | public-status/index.tsx | /api/v2/public |

## How Frontend Consumes Runtime Truth

1. **Public payloads**: Static JSON files in `v2/frontend/public/operator_runtime/` (written by backend publishers)
2. **REST polling**: React components poll API endpoints on interval (typically 30s–120s)
3. **SSE streaming**: `/api/v2/market` stream provides real-time candle/price updates
4. **Auth**: JWT stored in browser (Auth persists via `AUTH_PROCESS_SECRET`)

## Staleness Handling
- Each page shows last-updated timestamp
- Stale data flagged with visual indicator
- Feature freshness guard checks feature_cutoff age

## Known Missing Fields / Stub Pages
- ~28 API routes are stubs (from `docs/api-gap-register.md`)
- Several admin pages may show empty data if corresponding service is down
- `v2:paper:equity` not directly in ledger scalar; equity calculation requires position MTM

## Frontend Truth Payload Sources
- `v2/frontend/public/operator_runtime/` — static JSON files updated by CLI publishers
- Contains: paper fills, predictions, signals, risk decisions, trainer status
- Updated every 30s–120s by running services

## Mobile App
- 54 Swift files in `v2/mobile/`
- Platform: iOS/iPadOS/watchOS
- Backend: `/api/v2/mobile/*` (10 endpoints)
- Build 5 uploaded to TestFlight
- Future: React Native/Expo or SwiftUI expansion
