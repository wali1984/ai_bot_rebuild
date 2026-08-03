# Trader Final Defect Ledger

Generated: 2026-06-24

Statuses allowed: OPEN, IMPLEMENTED, VERIFIED, BLOCKED.

## Defects

| ID | Status | Surface | Defect | Evidence | Required verification before VERIFIED |
|---|---|---|---|---|---|
| TRADER-001 | OPEN | All trader pages | Before audit rendered zero canonical `data-field-id` values; after consistency run found 23 observations but required account, market, signal, and risk comparisons are still missing on deployed pages. | `artifacts/trader-live-before.json`, `artifacts/trader-cross-page-before.json`, `artifacts/trader-cross-page-after.json` | Source fix, unit/contract test, deployed before/after screenshots, raw API/WS value comparison, cross-page comparison pass, no console/network error |
| TRADER-002 | OPEN | Production navigation | Required menu navigation needed direct-route fallback for account settings, market detail symbols, trade, replay, technical analysis, and alerts. | `docs/trader-live-before.md` | Deployed menu crawl with zero direct fallbacks |
| TRADER-003 | OPEN | Production network | Production before audit recorded HTTP failures across trader pages. | `artifacts/trader-live-before.json` | Deployed audit with zero HTTP failures and zero console errors |
| TRADER-004 | IMPLEMENTED | Cross-page consistency | After consistency artifact now has zero missing comparisons and zero mismatches; the Playwright test still fails because production emits console/network errors. | `artifacts/trader-cross-page-after.json` | `frontend/tests/e2e/trader_cross_page_consistency.spec.ts` passes against deployed domain with zero failed requests and zero console errors |
| TRADER-005 | OPEN | Replay | Replay navigation landed on `/backtests`, not a distinct replay surface. | `docs/trader-live-before.md` | Menu-driven deployed audit reaches the intended Replay surface |
| TRADER-006 | OPEN | Technical Analysis | Technical Analysis navigation landed on `/landing`. | `docs/trader-live-before.md` | Menu-driven deployed audit reaches Technical Analysis through trader navigation |
| TRADER-007 | IMPLEMENTED | Trader account read model | Trader pages fetched and normalized account/position/signal/market fields independently. | New `/api/v2/trader/snapshot`, canonical registry, store, selectors | Deployed pages consume snapshot selectors and cross-page comparison passes |
| TRADER-008 | IMPLEMENTED | Top-right user menu | User dropdown could render behind/clipped by content, preventing logout. | `.topbar-shell` had `overflow: hidden`; menu z-index was lower than some page chrome | Deployed before/after screenshot showing visible menu and successful logout path, plus no console/network errors |
| TRADER-009 | BLOCKED | Full frontend validation | Full frontend typecheck includes admin-lane files outside Codex ownership with pre-existing errors. | Full `npm run --prefix frontend typecheck` failed before trader wiring; targeted trader TypeScript passed | Claude/admin lane resolves non-trader type errors or provides approved scope to edit |
| TRADER-010 | IMPLEMENTED | Trader paper account data | Authenticated portfolio, positions, and signals could fall back to stale seeded repository zeros/empties when Redis was unavailable, even though current paper runtime files had non-zero equity, open positions, and active signals. | `backend/tests/integration/api/v2/test_market_contract_routes.py`; local authenticated smokes with Redis disabled showed non-zero equity, non-empty positions, BTC signal present, and `LIVE_TRADING_BLOCKED` | Deploy branch, rerun deployed-domain audit, compare rendered values with `/api/v2/portfolio`, `/api/v2/account/positions`, `/api/v2/signals`, and pass cross-page comparison with no console/network errors |

## Implemented Evidence

- `backend/app/api/v2/trader_snapshot.py` adds authenticated, read-only trader snapshot and health endpoints.
- `frontend/src/data/canonicalFieldRegistry.ts` and `frontend/src/types/canonicalTraderData.ts` define 79 canonical trader fields.
- `frontend/src/stores/traderRealtimeStore.ts`, `frontend/src/hooks/useTraderSnapshot.ts`, and selectors create one realtime trader store.
- Account Settings, Dashboard, Portfolio, Trade, Signals, AI Predictions, Markets, and Market Detail now include canonical metric rendering paths.
- `frontend/src/components/layout/TopBar.tsx` now keeps the user menu above trader cards and visible outside the sticky header.
- `backend/app/api/v2/market_contracts.py` now projects authenticated paper-mode portfolio, position, and signal data from current paper runtime sources when Redis is unavailable, while still rejecting explicitly mismatched account scopes.

Live execution remains blocked. No exchange mutation, strategy, PPO, MASA, trainer, risk formula, or live-gate transition was changed.
