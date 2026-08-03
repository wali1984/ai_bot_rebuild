# Trade Redesign Audit

Generated: 2026-06-13

Status: IN PROGRESS. This audit covers the Phase 8 `/trade` implementation pass. `/trade` is not marked PASS because production stream validation, durable depth/trades repositories, production account persistence, screenshot rerun, explicit partial local paper execution policy validation, production paper actions fail closed pending a verified paper execution service, and local paper submit/cancel/fill production validation remain pending.

## Current Route and Component Files

| Area | File | Status |
|---|---|---|
| Router | `frontend/src/router.tsx` | `/trade` is resolved through page registry children. |
| Registry | `frontend/src/pages/registry.ts` | `trader` page remains canonical module id. |
| Navigation override | `frontend/src/pages/productNavigation.ts` | `trader` now resolves to public `/trade` so paper/read-only terminal renders without backend auth. |
| Page entry | `frontend/src/pages/trader/index.tsx` | Refactored to render `TradeTerminal`. |
| Terminal root | `frontend/src/components/trade/TradeTerminal.tsx` | New modular terminal shell. |
| Header | `frontend/src/components/trade/SymbolHeader.tsx` | New symbol/freshness/metric header. |
| Chart | `frontend/src/components/trade/TradingChartPanel.tsx` | New `lightweight-charts` candlestick and volume panel. |
| Book/depth/tape | `frontend/src/components/trade/OrderBookPanel.tsx`, `MarketDepthPanel.tsx`, `RecentTradesTape.tsx` | New paper-safe market microstructure modules. |
| Ticket | `frontend/src/components/trade/PaperOrderTicket.tsx` | New disabled paper order ticket. |
| Bottom tabs | `frontend/src/components/trade/TradeBottomTabs.tsx` plus table panels | New positions, orders, executions, history, and signal evidence panel. |
| Data hook | `frontend/src/hooks/useTradeTerminal.ts` | Prefers safe `/api/v2` read-only/paper account data and current read-only market stream/contracts; unavailable states remain visible when scoped data is missing. Direct legacy operator terminal, paper runtime, portfolio-state, and live-gate runtime fallbacks are no longer current public/trader terminal state. |
| Copy/format | `frontend/src/lib/tradeCopy.ts`, `frontend/src/lib/tradeFormatters.ts` | New trader-facing formatting and copy mappings. |
| CSS | `frontend/src/styles/components.css` | New Phase 8 terminal styles and responsive rules. |

## Current Data Sources

| Metric/module | Current source | Freshness displayed | Endpoint gap |
|---|---|---:|---|
| Last price | `/api/v2/market/{symbol}` with read-only market stream/contracts or designed unavailable state | yes | durable ticker repository and stream |
| Mark/index price | `/api/v2/market/{symbol}` returns designed missing state when absent | missing state | durable ticker repository |
| 24h high/low/change | `/api/v2/market/{symbol}/ticker` returns designed missing state when absent | missing state | full 24h ticker fields |
| Volume/turnover | market API data plus read-only stream/contracts where available | tooltip/source | durable ticker repository |
| Funding | typed market/derivatives contract where available; otherwise designed unavailable state | tooltip/source | durable `/api/v2/derivatives/{symbol}/funding` source |
| Open interest/OI change | typed market/derivatives contract where available; otherwise designed unavailable state | tooltip/source | durable `/api/v2/derivatives/{symbol}/open-interest` source |
| Candles | `/api/v2/market/{symbol}/candles` with chart fallback | yes | durable candle source and stream freshness |
| Order book | `/api/v2/market/{symbol}/depth` with top-of-book fallback/unavailable state | source tooltip | full ladder and realtime stream |
| Market depth | `/api/v2/market/{symbol}/depth` with top-5 summary fallback/unavailable state | source tooltip | cumulative depth and liquidity walls |
| Recent trades | `/api/v2/market/{symbol}/trades` structured unavailable state | missing state | recent trade stream/source |
| Trader credential status | `/api/auth/me` safe exchange-account metadata plus backend-only env/local vault-file credential binding | partial | durable production credential vault, permission probe, and signed read-only account adapter validation |
| Paper order preview/actions | `/api/v2/orders/preview`, `/api/v2/orders/paper`, `/api/v2/orders/paper/{order_id}/cancel`, `/api/v2/orders/paper/{order_id}/fill`, and `/api/v2/execution/audit-events` | yes | explicit partial local paper execution policy metadata, production paper actions fail closed, hash-chained local audit-event evidence, append-only local ledger rows, paper audit retention policy metadata, and durable paper audit policy artifact metadata exist; production validation, durable paper audit policy execution, persistence hardening, screenshots, and full rerun remain pending |
| Positions | `/api/v2/account/positions` with portfolio fallback/unavailable state | page fallback | auth-scoped positions repository |
| Open orders/history | `/api/v2/execution/orders` plus local paper repository submit/cancel/fill rows and audit metadata | partial | production paper order repository validation and audit hardening |
| Executions | `/api/v2/execution/executions` structured unavailable/repository state plus explicit local paper fill rows, hash-chained `/api/v2/execution/audit-events`, and append-only local ledger metadata | partial | production paper fill/execution audit validation and durable persistence |
| Signal evidence | `/api/v2/signals` with trader/paper-account scope checks; unscoped fallback signal evidence is withheld | page fallback | durable signal evidence source |

## Historical Fallback Payloads

These payloads were reviewed during the original Phase 8 implementation. They must not be treated as current live evidence. Later `/trade` hardening removed direct legacy operator terminal, paper runtime, portfolio-state, and live-gate runtime reads from the public/trader terminal state; missing scoped data should surface typed unavailable/source states instead.

| Fallback | Historical use |
|---|---|
| `/operator_runtime/v2_trade_terminal/latest/trade_terminal_payload.json` | Historical market header, top-of-book, derivatives summary, and paper balance hints; no longer accepted as current public/trader terminal truth. |
| `/operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json` | Historical open paper positions fallback; current account-sensitive rows require trader and paper-account scope or are withheld. |
| `/operator_runtime/paper_online/latest/paper_runtime_status.json` | Historical paper account/current signal/risk/runtime freshness fallback; current unscoped account/signal/risk evidence is withheld. |
| `/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json` | Historical paper/read-only safety badge copy; current live-gate runtime reads are not used as public/trader terminal truth. |
| `/operator_runtime/v2_professional_market_chart/latest/{symbol}_{timeframe}_chart.json` | Historical candlestick and volume chart fallback; current charts prefer typed closed-candle contracts and read-only stream display, with stale/static snapshots withheld from active chart rendering. |

## Pre-Implementation Screenshot Defects Reviewed

| Screenshot | Defects |
|---|---|
| `screenshots/final/1920x1080_trade.png` | Protected route renders sign-in gate instead of terminal; large blank vertical whitespace; auth/RBAC copy dominates; no chart, book, ticket, or account panel. |
| `screenshots/final/1440x900_trade.png` | Same auth-gate route defect; not a valid product QA screenshot. |
| `screenshots/final/768x1024_trade.png` | Auth gate only; no tablet terminal layout evidence. |
| `screenshots/final/390x844_trade.png` | Auth gate only; mobile shows raw preflight enum and clipped submission-hold chip. |

## Raw/Internal Copy Found Before Refactor

| Raw/internal visible copy | Status |
|---|---|
| `PRELIGHT_CREATED_APPROVAL_REQUIRED_NOT_CREATED` style preflight text | Removed from `/trade` terminal surface. |
| `NO LOCAL ROLE SWITCHING` | Removed from `/trade` terminal surface. |
| `live armed balance hold` | Mapped to friendly paper/read-only state where terminal controls display it. |
| Missing backend order preview wording | Replaced with `Paper order preview unavailable` and endpoint-specific missing state. |
| Spreadsheet/operator panel labels | Replaced with terminal modules and account tabs. |

## Current Control Safety

| Control | State | Safety result |
|---|---|---|
| Buy/Sell side tabs | UI-only | Paper ticket state only. |
| Market/Limit/Stop/TP-SL selector | UI-only | Does not submit. |
| Quantity/price fields | Local form state | No exchange path. |
| Percent sizing buttons | Disabled | Requires paper preview endpoint. |
| Submit button | Enabled only for authenticated local paper repository staging after preview approval | Labeled `Place Paper Buy/Sell`; no live action and no automatic fill. |
| Reduce-only | Not shown as enabled | Requires backend support before display. |
| Cancel order action | Available only for authenticated local open paper repository orders | No exchange cancel path; filled paper orders are not cancelable. |
| Fill order action | Available only for authenticated local open paper repository orders | Manual local paper fill only with local audit event; no exchange fill path, no transport submission, and no automatic fill policy. |
| Live trading controls | Absent | No live submission, cancellation, margin, leverage, or live-gate mutation exists on `/trade`. |

## Responsive Defects Addressed

| Viewport | Change |
|---|---|
| Desktop | Chart-first grid with right trading column and bottom tabs. |
| 1440/tablet | Single-column chart with two-column trading modules where space allows. |
| 768px | Tables convert toward compact cards and no page-width table is required. |
| 390px | Segmented Chart / Book / Ticket / Positions / Evidence modules prevent wide terminal overflow. |

## Historical Post-Implementation Screenshots

These screenshots are retained as historical Phase 8/13A evidence only. Later stream, account-scope, ProChart, symbol-data fallback-removal, open-order guard, and docs changes require a current screenshot rerun and visual review before these can be used as current completion evidence.

| Screenshot | Visual review |
|---|---|
| `screenshots/final/trade-1920x1080.png` | Historical review. Terminal rendered chart-first layout, right trading column, disabled paper ticket, and account tabs without body overflow at that point. Current rerun pending. |
| `screenshots/final/trade-1440x900.png` | Historical Playwright capture. Layout remained terminal-oriented with chart and trading column at that point. Current rerun pending. |
| `screenshots/final/trade-768x1024.png` | Historical Playwright capture. Tablet layout stacked modules without body overflow at that point. Current rerun pending. |
| `screenshots/final/trade-390x844.png` | Historical review. Mobile segmented module layout rendered chart-first without body overflow at that point. Current rerun pending. |

## Tests Run

| Command | Result |
|---|---|
| `npm run typecheck` | HISTORICAL PASS; current rerun pending after later stream/account/ProChart/symbol-data/open-order/docs changes |
| `npm run build` | HISTORICAL PASS with existing Vite chunk-size warning; current rerun pending after later stream/account/ProChart/symbol-data/open-order/docs changes |
| `npx playwright test tests/e2e/trade_terminal_redesign.spec.ts --project=chromium` | HISTORICAL PASS, 10 tests; pending rerun after stream/account/credential-status/exchange-account normalization/frontend scoped paper-account display/trade typed activity tabs/shared symbol-data fallback removal/open-order explicit local repository action guard/ProChart realtime timestamp normalization/ProChart derivative overlay null-clear/docs guard changes |
| `npx playwright test tests/e2e/redesign_screenshot_overflow.spec.ts --project=chromium` | HISTORICAL PASS, 4 viewport route-crawl tests; current rerun pending after later stream/account/ProChart/symbol-data/open-order/docs changes |

## Current Status

`/trade`: IN PROGRESS.

Remaining blockers: missing native exchange realtime streams, incomplete durable trader-scoped data sources, durable production credential vault/signed read-only account adapter validation, local paper submit/cancel/fill production validation beyond explicit partial local policy metadata and production paper actions fail closed behavior, current validation rerun, screenshot visual adjudication after this pass, and full product triple-check across all routes.

## Phase 4A / 7A Addendum

- Phase 8 documentation structure was rechecked during the Phase 4A/7A pass: the `/trade` gap table is valid Markdown, all Phase 8 rows remain under the correct section, and no unrelated document heading is embedded inside the table.
- `/trade` remains `IN PROGRESS`, not `PASS`.
- `/trade` now prefers safe `/api/v2/market/{symbol}` data when available and shows typed unavailable/source states when scoped data is missing. Direct legacy operator terminal, paper runtime, portfolio-state, live-gate runtime, and shared symbol-data legacy terminal fallback reads are no longer current public/trader terminal truth.
- `/trade` paper ticket now calls `/api/v2/orders/preview` for valid inputs and can stage authenticated local paper repository orders when preview checks pass; open-order rows expose manual local paper fill/cancel actions only; staged orders do not auto-fill.
- New safe read-only/paper API surfaces were added for `/api/v2/market/*`, `/api/v2/portfolio`, `/api/v2/account/positions`, `/api/v2/execution/orders`, `/api/v2/execution/executions`, `/api/v2/signals`, and `/api/v2/orders/preview`.
- Historical re-verification after API integration: `npm run typecheck`, `npm run build`, `npx playwright test tests/e2e/trade_terminal_redesign.spec.ts --project=chromium`, and `npx playwright test tests/e2e/redesign_screenshot_overflow.spec.ts --project=chromium`. Current stream/account/credential-status/exchange-account normalization/frontend scoped paper-account display/trade activity tabs/symbol-data fallback removal/open-order explicit local repository guard/ProChart realtime timestamp normalization/ProChart derivative overlay null-clear/docs guard changes are pending rerun.

## Phase 3A / 5B Addendum

- `/trade` remains `IN PROGRESS`, not `PASS`.
- Auth/RBAC changes did not enable live submission, cancellation, leverage, margin, or live-gate mutation.
- Historical Phase 3A/5B verification: backend pytest passed for auth/status and market contract tests, frontend `npm run typecheck`, `npm run build`, `npm run lint --if-present`, and the combined requested Playwright suite passed 49/49. Current validation remains pending after later stream/account/ProChart/symbol-data/open-order/docs changes.
- Remaining `/trade` blockers are native exchange market streams, durable trader-scoped repositories/writers, production paper submit/cancel/fill validation decision beyond production paper actions fail closed behavior, durable production credential vault/signed read-only account adapter validation, production auth hardening, current validation rerun, and human visual review.

## 2026-06-14 Paper Ticket Verified Staging Policy Guard

- Event: `paper_order_ticket_requires_verified_paper_staging_policy`.
- `/trade` paper submit remains fail-closed unless trader scope, local paper staging policy, and exchange-route safety policy all pass.
- Evidence key `production_paper_actions_fail_closed_after_latest_changes` remains `PENDING`; current validation was not run.
- `/trade`, `/market/:symbol`, Phase 15, paper/read-only launch, full product launch, admin security, and real live trading remain not complete.

## 2026-06-14 Trade Header Next Funding Display

- Event: `trade_symbol_header_next_funding_uses_typed_value`.
- `/trade` next funding now uses market API data when available.
- Evidence key `trade_typed_activity_tabs_after_latest_changes` remains `PENDING`; current validation was not run.
- `/trade`, `/market/:symbol`, Phase 15, paper/read-only launch, full product launch, admin security, and real live trading remain not complete.

## 2026-06-14 update - scoped local paper staging guard

- Paper order preview still performs a read-only estimate and now exposes whether the request trader/paper account scope matched the backend session.
- Local paper staging is blocked unless explicit `trader_id` and `paper_account_id` request fields match the authenticated session and repository account.
- `/trade` remains IN PROGRESS because realtime streams, production paper submit/cancel/fill validation, and current visual/test evidence remain pending.
