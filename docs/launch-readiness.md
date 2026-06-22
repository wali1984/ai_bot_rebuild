# Launch Readiness Register
Generated: 2026-06-12T22:22:41.000Z

## Codex 5.5 launch stance (current)
- Public/trader platform target: **PAPER / READ-ONLY** by design until explicit live-gate completion.
- Real live order submission must remain blocked by middleware + explicit gate state.

## Launch-control matrix
| control | status | evidence | required fix |
|---|---|---|---|
| PAPER/READ-ONLY LIVE | PASS | `/api/v1/live` is guarded by `live_block_guard`; no enabled `/live/orders` workflow in public routes | Preserve by default; do not open live execution without explicit approval |
| Real LIVE trading | BLOCKED | No production-ready live auth/execution controls in trader-facing surfaces; many routes are placeholders | Require full auth + RBAC + audit + live gate before any live controls |
| Trader/Public vs Admin separation | BLOCKED | Multiple admin/developer routes remain in route registry/nav flow via current mapping | Create explicit `/admin/*` surface and hide operator routes from trader shell |
| Auth integrity | BLOCKED | Fake role override via URL/session storage still present in runtime auth path | Replace with backend-enforced JWT/session auth before launch |
| Brand normalization | BLOCKED | `AI BOT V2`/`Control Plane` still visible in public shells/components | Standardize AlphaForge defaults and evidence-only admin labels |
| Paper mode visibility | BLOCKED | Paper/read-only state is not consistently surfaced across all trading pages | Add required `Paper Mode Active / Live Trading Disabled` indicator |
| Missing market data APIs | BLOCKED | `/api/v2/market`, `/api/v2/positions`, `/api/v2/signals`, `/api/v2/portfolio` unresolved | Implement APIs or explicit stale/missing-data state in every affected page |
| WebSocket/event stream | BLOCKED | No verified `/ws/market-data` or `/events` usage | Implement stream + stale handling when unavailable |
| Static polling fallback discipline | NOT STARTED | Polling exists but stale/missing labeling is inconsistent | Add explicit stale/missing state primitives before any rollout |
| Test evidence | NOT STARTED | Phase-0 acceptance not yet enforced by automated checks | Add route, branding, auth, and overflow test coverage before Phase 1 |

## Status decision
- `PAPER/READ-ONLY LIVE: PASS`
- `REAL LIVE TRADING: BLOCKED`

## Immediate launch blockers (must clear before claiming clean paper launch)
1. Complete auth integrity fix (`/api/auth/*`, no URL/session role escalation).
2. Finish route/surface separation into trader/admin with superadmin routes isolated.
3. Introduce mandatory paper-mode banner + freshness labels on all trading/product pages.
4. Replace core fake data dependencies on `/markets`, `/trade`, `/signals`, `/portfolio`, and `/market/:symbol` with real endpoints or strict missing-data states.
5. Implement or explicitly gate stream architecture and stale handling for trade-critical cards and charts.
6. Capture required baseline and final screenshots for all critical routes at approved resolutions.

## Evidence requirements before deployment
- `docs/route-inventory-before-redesign.md`, `docs/data-source-inventory.md`, `docs/ui-defect-log-before.md`, `docs/redesign-acceptance-matrix.md`, `docs/api-gap-register.md` committed and updated.
- No localStorage/sessionStorage role switching or query role injection.
- Superadmin controls restricted by backend role checks and logged with audit IDs.
