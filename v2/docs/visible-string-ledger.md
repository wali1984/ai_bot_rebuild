# Visible String Ledger

Generated: 2026-06-13

Purpose: track trader-visible terminology that must be removed, translated, or confined to system/superadmin pages.

## Forbidden On Public/Trader Routes

| String/pattern | Allowed only in | Current status | Action |
|---|---|---|---|
| `AI BOT V2` | none for public/trader | IN PROGRESS | Replace with AlphaForge or route-specific professional copy. |
| `Control Plane` | protected system pages only | IN PROGRESS | Use `System` or admin-specific labels outside trader routes. |
| `Mission Control` | protected system pages only | IN PROGRESS | Dashboard route now uses trader copy; remaining references must be checked. |
| `War Room` | superadmin/developer pages only | IN PROGRESS | Keep hidden from trader nav and copy. |
| `Operator Proof` | superadmin/evidence pages only | IN PROGRESS | Rename trader-facing evidence to plain language. |
| `Codex`, `Claude`, `Ollama` | superadmin/developer pages only | IN PROGRESS | Remove from public/trader visible strings. |
| `payload explorer` | superadmin/developer pages only | IN PROGRESS | Replace with evidence/source drawers where trader-facing. |
| `gap matrix` | superadmin/developer pages only | IN PROGRESS | Replace with source coverage or missing-data copy. |
| `operator truth` | system/superadmin pages only | IN PROGRESS | Translate to data/source status in trader routes. |
| raw snake_case enums | collapsed admin/debug sections only | IN PROGRESS | Convert to sentence-case labels in trader UI. |

## Translations

| Raw/internal value | Trader-facing label |
|---|---|
| `LIVE_ARMED_BALANCE_HOLD` | Balance hold |
| `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER` | Insufficient paper balance |
| `paper_fill_allowed:false` | Paper fill blocked |
| `churn_blocked` | Churn protection active |
| `fee_gate_allowed` | Fee gate passed |
| `gate_always_blocked_invariant` | Live trading guard active |
| `PRESENT_CURRENT` | Current |
| `MISSING_SOURCE` | Data source unavailable |
| `MISSING_EVIDENCE` | Evidence unavailable |
| `Data source unavailable` | Data source unavailable |
| `payload fallback` | Fallback data |
| `runtime payload` | Fallback runtime snapshot |
| `V2_BINANCE_KLINE_WSS_WITH_V2_TA_AND_SIGNAL_OVERLAYS` | Market chart source connected |

## Phase 8 `/trade` Visible String Ledger

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---|---|
| `/trade` | `TradeTerminal.tsx` | `Professional paper trading terminal` | `Professional paper trading terminal` | no | CHECKED |
| `/trade` | `TradeShared.tsx` | `Paper / Read-only` | `Paper / Read-only` | no | CHECKED |
| `/trade` | `SymbolHeader.tsx` | `Last`, `Mark`, `Index`, `24h`, `High`, `Low`, `Volume`, `Turnover`, `Funding`, `Next funding`, `Open interest`, `OI change`, `Spread`, `AI direction`, `Confidence`, `Risk` | same | no | CHECKED |
| `/trade` | `TradingChartPanel.tsx` | `Candlestick Chart`, `Loading chart data`, `Candles unavailable` | same | no | CHECKED |
| `/trade` | `OrderBookPanel.tsx` | `Order Book`, `Full ladder unavailable` | same | no | CHECKED |
| `/trade` | `MarketDepthPanel.tsx` | `Market Depth`, `Depth chart source incomplete` | same | no | CHECKED |
| `/trade` | `RecentTradesTape.tsx` | `Recent Trades`, `Recent trades unavailable` | same | no | CHECKED |
| `/trade` | `PaperOrderTicket.tsx` | `Paper Order Ticket`, `Place Paper Buy`, `Place Paper Sell`, `Paper order unavailable`, `Paper order can be staged`, `Staging Paper Order`, `Paper policy`, `Local paper only; production validation pending`, `Production paper actions disabled`, `Exchange route`, `Live trading disabled`, `Paper execution policy pending` | same | no | CHECKED PENDING RERUN |
| `/trade` | `TradeBottomTabs.tsx` | `Positions`, `Open Orders`, `Executions`, `Order History`, `Signal Evidence` | same | no | CHECKED |
| `/trade` | `tradeCopy.ts` | raw enum mappings | friendly labels | allowed in code only | CHECKED |
| `/trade` | `PositionsTable.tsx` | `No trader-scoped paper position rows are available from the positions source. Unscoped fallback positions are not shown.` | same | no | CHECKED |
| `/trade` | `RecentTradesTape.tsx` | `Buy`, `Sell`, `Recent trades unavailable`, `recent-trades source` | same | no | CHECKED |
| `/trade` | `TradeTerminal.tsx`, `PaperOrderTicket.tsx` | account balance/PnL unavailable when typed account contract is unscoped | trader-specific account data only | no | CHECKED |
| `/dashboard` | `mission-control/index.tsx` | `Trader-scoped position rows unavailable`, `Position rows require a trader-specific repository source.` | trader-specific account source state | no | CHECKED PENDING RERUN |
| `/trade` | `TradeTerminal.tsx`, `useTraderContext.ts` | `Account access`, `Account access source unavailable`, `Exchange account unavailable`, `Read-only account access configured` | safe account-link status only; no raw private values | no | CHECKED PENDING RERUN |
| `/trade`, `/market/:symbol` | `useMarketDataStream.ts`, `useTradeTerminal.ts` | `Market stream unavailable`, `Read-only market stream connected`, `Read-only market stream unavailable; using API polling fallback` | same | no | CHECKED |
| `/trade`, `/market/:symbol`, `/chart/:symbol` | `useMarketDataStream.ts`, `TradingChartPanel.tsx`, `ProChart.tsx`, `market_contracts.py` | `Native public stream + candle source`, `Realtime`, `Candle update`, `Stream forming candle`, `Stream closed candle`, `Waiting for stream frame` | public-safe read-only stream and partial-candle copy; unfinished candles are not final evidence | no | CHECKED PENDING RERUN |

## Phase 7A `/market/:symbol` Visible String Ledger

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `pages/market/index.tsx` | `Read-only market view`, `Read-only`, `Source transparency` | same | no | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | `Last price`, `Mark price`, `Index price`, `1h change`, `4h change`, `24h change`, `24h high`, `24h low`, `24h volume`, `24h turnover` | same | no | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | `Funding`, `Next funding`, `Open interest`, `OI change`, `Spread`, `Risk status` | same | no | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | `AI direction`, `Confidence`, `Prediction unavailable`, `Model version unavailable` | same | no | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | `Order Book Summary`, `Depth data not connected`, `Depth chart unavailable`, `Recent Trades`, `Recent trades unavailable` | same | no | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | `Funding, OI, Liquidations`, `Liquidations unavailable`, `Long/short data unavailable`, `Basis data unavailable` | same | no | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | `Active Signal Summary`, `Signal evidence unavailable`, `Evidence`, `Data Sources and Freshness`, `Technical evidence` | same | no | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | backend warnings | public-safe warning text with `payload`, `operator`, and `debug` removed | yes if unsanitized | CHECKED |

## Current Hotspots

| Route/file area | Risk | Status |
|---|---|---|
| `/trade` | Terminal route has copy mapping, paper preview integration, local paper repository staging/cancel, explicit partial local paper execution policy copy, explicit no-auto-fill policy, and safe credential-status copy; production stream validation, production paper validation/fill writer, and current rerun remain missing. | IN PROGRESS |
| `/market/:symbol` | Public read-only market page removed the raw alt-data candidate publisher and no longer exposes debug/operator panels in main UI; depth/trades/derivatives remain unavailable until durable sources are wired. | IN PROGRESS |
| `/login` | New login page has no role selector, fake admin shortcut, local role copy, or frontend role escalation wording. | CHECKED |
| `/status` | Public status page uses platform/API/data/paper/live-disabled copy and avoids logs, stack traces, build internals, paths, and raw JSON. | CHECKED |
| `/` | Public landing raw live-gate/runtime labels and payload wording were translated to public-safe labels. | CHECKED |
| `/signals` and `/ai-predictions` | Signal/evidence pages now use trader-safe signal source and model/routing copy by default; technical source inventory, deployment truth, and lineage IDs are admin-only or behind an explicit technical trace drawer. | CHECKED PENDING RERUN |
| `/system/*` | Internal terms are allowed only when access and context are clearly admin/superadmin. | MONITOR |

## Phase 3A + 5B Visible String Ledger

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---|---|
| `/login` | `pages/login/index.tsx` | `Sign in to AlphaForge`, `Email`, `Password`, `Remember this device`, `Sign In`, `View read-only markets` | same | no | CHECKED |
| `/login` | `pages/login/index.tsx` | role selector / fake admin shortcut | removed | yes if visible | CHECKED |
| `/status` | `pages/public-status/index.tsx` | `Platform status`, `API availability`, `Data freshness`, `Paper mode`, `Live trading disabled`, `No active incidents` | same | no | CHECKED |
| `/status` | `pages/public-status/index.tsx`, `status_contracts.py` | `Market stream`, `Read-only public market stream`, `Read-only market polling fallback`, `Waiting for first public market frame` | public-safe stream freshness labels; no file paths or raw source enum exposed | no | CHECKED PENDING RERUN |
| `/status` | `pages/public-status/index.tsx` | stack traces, logs, env vars, raw JSON, build/migration/script copy | removed/not rendered | yes if visible | CHECKED |
| `/` | `pages/public-landing-v2/index.tsx` | raw live-gate/runtime state and `payload` wording | `Restricted to paper mode`, `Paper mode active`, `market data` | yes if raw | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | raw alt-data candidate publisher table | removed from public market detail | yes if visible | CHECKED |
| public/trader nav | `components/layout/Nav.tsx`, `auth/rbac.ts`, `hooks/useAuth.tsx` | browser-storage or query-derived role labels | backend-confirmed role state only | yes if visible | CHECKED |

## Phase 13A Visible String Ledger

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---|---|
| `/` | `pages/public-landing-v2/index.tsx` | `Data source unavailable` fallbacks | `Data unavailable` / `Data source unavailable` | yes if raw | CHECKED |
| `/` | `pages/public-landing-v2/index.tsx` | `Paper Mode`, `Read-only preview`, `Trader Account`, `Sign in for account-specific paper data`, `Account data: sign in required` | public-safe non-account posture copy | no | CHECKED PENDING RERUN |
| `/` | `components/banners/LiveBlockBanner.tsx` | live/armed runtime banner wording | `Paper / read-only mode active`, `Live trading disabled` | yes if raw | CHECKED |
| public shell | `components/layout/PublicShell.tsx` | public `Equity` / public `Paper PnL` account-like values | `Account scope: Sign in required`, `Paper PnL: Trader-specific source required` | no | CHECKED |
| trader generic shell | `components/layout/PageShell.tsx` | global paper equity/PnL payload values | `Trader-specific account source required` | no | CHECKED |
| `/login` | `pages/login/index.tsx` | email/password/auth copy | approved professional auth copy | no | CHECKED |
| `/status` | `pages/public-status/index.tsx` | `Source Pending` | `Data source unavailable` | yes if raw | CHECKED |
| `/dashboard` | `components/charts/V2ProfessionalMarketChart.tsx` | `payload`, source Redis keys, backend chart source enum | `Chart data current`, `Market chart source connected`, `Technical evidence` | yes if raw | CHECKED |
| `/dashboard` | `components/layout/AdminShell.tsx` | `LIVE_ARMED_BALANCE_HOLD`, `Live Gate` | `paper balance hold`, `Live trading disabled` | yes if raw | CHECKED |
| `/markets` | `pages/markets/index.tsx` | numeric formatter `Data source unavailable` output | `Data source unavailable` | yes if raw | CHECKED |
| `/market/:symbol` | `pages/market/index.tsx` | candidate publisher/debug panel | removed from public market detail | yes if visible | CHECKED |
| `/trade` | `components/trade/*` | live submit wording | no live submit button; paper/read-only copy only | yes if visible | CHECKED |

## Phase 14A Visible String/Test Contract Updates

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---|---|
| `/alerts` | `pages/alerts/index.tsx` | `enabled_operator_approved` live-gate value | `gate approved` / blocked-mode banner still visible | yes if raw | CHECKED FOR PHASE14A |
| `/derivatives` | `pages/liquidation-bridge/index.tsx` | raw live-gate value | friendly live-gate label via formatter | yes if raw | CHECKED FOR PHASE14A |
| `/portfolio` | `pages/positions/index.tsx` | raw live-gate value in live positions panel | friendly live-gate label via formatter | yes if raw | CHECKED FOR PHASE14A |
| `/backtests` | `pages/strategy-backtesting/index.tsx` | `LIVE_GATE` / raw live-gate value | `Live gate` with friendly label | yes if raw | CHECKED FOR PHASE14A |
| `/research` | `pages/market-intelligence/index.tsx`, `pages/edgeRecoveryQualityPanel.tsx` | raw live-gate value | friendly/sanitized live-gate label | yes if raw | CHECKED FOR PHASE14A |
| `/ai-predictions/model-state` | `components/layout/AdminShell.tsx`, `styles/admin.css` | mobile header overflow around backend role/user controls | wrapped backend-confirmed role controls | no | CHECKED FOR PHASE14A |
| full public/trader nav | `tests/e2e/helpers/forbiddenStrings.ts`, `tests/e2e/trader_first_redesign.spec.ts` | duplicated legacy forbidden word lists | shared route/copy contract helpers | no | CHECKED FOR PHASE14A |

## Market derivatives contract strings

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Derivatives analytics | Derivatives analytics | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Funding, OI, Liquidations | Funding, OI, Liquidations | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Next funding | Next funding | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Liquidations 1h | Liquidations 1h | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Liquidations 24h | Liquidations 24h | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Long/short ratio | Long/short ratio | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Basis | Basis | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Funding chart unavailable | Funding chart unavailable | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Open interest chart unavailable | Open interest chart unavailable | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Liquidation feed unavailable | Liquidation feed unavailable | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | Exchange comparison unavailable | Exchange comparison unavailable | no | CHECKED PENDING RERUN |

## Trade account-specific exchange strings

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/components/trade/TradeTerminal.tsx` | Exchange read | Exchange read | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/TradeTerminal.tsx` | Futures balance | Futures balance | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | Read-only account verified | Read-only account verified | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | Exchange read unavailable | Exchange read unavailable | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | Read-only account pending | Read-only account pending | no | CHECKED PENDING RERUN |

## ProChart realtime status strings

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Native public stream + candle source | Native public stream + candle source | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Typed candle contract | Typed candle contract | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Fallback candles | Fallback candles | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Runtime fallback snapshot | Runtime fallback snapshot | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Candle source unavailable | Candle source unavailable | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Forming display-only | Forming display-only | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Closed stream update | Closed stream update | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Waiting for stream | Waiting for stream | no | CHECKED PENDING RERUN |

## Paper submit and cancel strings

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/components/trade/PaperOrderTicket.tsx` | Paper order can be staged. | Paper order can be staged. | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/PaperOrderTicket.tsx` | Staging Paper Order | Staging Paper Order | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/PaperOrderTicket.tsx` | Paper order unavailable | Paper order unavailable | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | Cancel paper | Cancel paper | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | Canceling | Canceling | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | Fill paper | Fill paper | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | Filling paper | Filling paper | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | Manual local paper fill only; no exchange order is placed | Manual local paper fill only; no exchange order is placed | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | Local paper cancel only; no exchange cancel is sent | Local paper cancel only; no exchange cancel is sent | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | No action | No action | no | CHECKED PENDING RERUN |

## Paper audit event strings

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Paper audit events | Paper audit events | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Tamper-evident local audit chain | Tamper-evident local audit chain | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Local file-backed evidence | Local file-backed evidence | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Append-only local ledger | Append-only local ledger | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Paper order staged | Paper order staged | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Paper order canceled | Paper order canceled | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Paper order filled | Paper order filled | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Local paper repository audit | Local paper repository audit | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Paper audit events unavailable | Paper audit events unavailable | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | Trader-scoped paper audit events are not available from the typed execution audit endpoint. | Trader-scoped paper audit events are not available from the typed execution audit endpoint. | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SignalEvidencePanel.tsx` | `paper_order_staged_local`, `paper_order_canceled_local`, `paper_order_filled_local` | translated to trader-facing labels; raw values remain backend/test evidence only | yes if visible | CHECKED PENDING RERUN |

## Phase 15 partial stream alert-history copy

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---|---|
| `/status` | `frontend/src/pages/public-status/index.tsx` | Alert history | Alert history | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Production alerting pending. | Production alerting pending. | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Waiting for local stream events. | Waiting for local stream events. | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | local events | local events | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | active alerts | active alerts | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | active alert | active alert | no | APPROVED |

## Phase 15 partial stream alert-delivery copy

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---|---|
| `/status` | `frontend/src/pages/public-status/index.tsx` | Alert delivery | Alert delivery | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Outbound alert delivery is not configured. | Outbound alert delivery is not configured. | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Outbound alert delivery is configured but disabled. | Outbound alert delivery is configured but disabled. | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Waiting for the first delivery attempt. | Waiting for the first delivery attempt. | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Not configured | Not configured | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Disabled | Disabled | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Ready | Ready | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Pending | Pending | no | APPROVED |
| `/status` | `frontend/src/pages/public-status/index.tsx` | Alert delivery status is unavailable. | Alert delivery status is unavailable. | no | APPROVED |

## 2026-06-14 route cleanup additions

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---:|---|
| `/portfolio/executions` | `frontend/src/pages/executions/index.tsx` | Trader-Scoped Execution Account | Paper Execution Account | no | CHECKED PENDING RERUN |
| `/portfolio/executions` | `frontend/src/pages/executions/index.tsx` | Paper / read-only | Paper / read-only | no | pending rerun |
| `/portfolio/history` | `frontend/src/pages/history/index.tsx` | Trader-Scoped History Account | Paper History Account | no | CHECKED PENDING RERUN |
| `/signals` | `frontend/src/pages/signals/index.tsx` | Active Signal Summary | Active Signal Summary | no | pending rerun |
| `/signals` | `frontend/src/pages/signals/index.tsx` | Signal Evidence | Signal Evidence | no | pending rerun |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/index.tsx` | Current Prediction | Current Prediction | no | pending rerun |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/index.tsx` | Prediction Evidence | Prediction Evidence | no | pending rerun |
| `/ai-predictions/model-state` | `frontend/src/pages/productNavigation.ts` | redirects to `/ai-predictions` | redirects to `/ai-predictions` | no | pending rerun |
| `/trade/paper` | `frontend/src/pages/productNavigation.ts` | redirects to `/trade` | redirects to `/trade` | no | pending rerun |
| `/derivatives` | `frontend/src/pages/liquidation-bridge/index.tsx` | Derivatives Snapshot | Derivatives Snapshot | no | pending rerun |
| `/derivatives` | `frontend/src/pages/liquidation-bridge/index.tsx` | Derivative Data Gaps | Derivative Data Gaps | no | pending rerun |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | Current candle data unavailable | Current candle data unavailable | no | pending rerun |

## 2026-06-14 duplicate trader route cleanup

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/markets/symbols` | `frontend/src/pages/productNavigation.ts` | duplicate Symbols route | Redirect to Markets | no | IN PROGRESS, pending rerun |
| `/backtests/replay` | `frontend/src/pages/productNavigation.ts` | replay runtime surface | Redirect to Backtests | no | IN PROGRESS, pending rerun |
| `/research/technical-analysis` | `frontend/src/pages/productNavigation.ts` | technical-analysis runtime surface | Redirect to Research | no | IN PROGRESS, pending rerun |
| `/backtests` | `frontend/src/pages/strategy-backtesting/index.tsx` | Backtest engine unavailable | Backtest engine unavailable | no | IN PROGRESS, pending rerun |
| `/research` | `frontend/src/pages/market-intelligence/index.tsx` | Research workbench incomplete | Research workbench incomplete | no | IN PROGRESS, pending rerun |
| `/portfolio` | `frontend/src/pages/positions/index.tsx` | Trader-scoped paper portfolio view | Trader-scoped paper portfolio view | no | IN PROGRESS, pending rerun |
| `/portfolio` | `frontend/src/pages/positions/index.tsx` | No scoped paper positions | No scoped paper positions | no | IN PROGRESS, pending rerun |
| `/alerts` | `frontend/src/pages/alerts/index.tsx` | Alert source present; actions unavailable | Alert source present; actions unavailable | no | IN PROGRESS, pending rerun |
| `/alerts` | `backend/app/api/v2/alerts_contracts.py` | Alert actions are unavailable | Alert actions are unavailable | no | IN PROGRESS, pending rerun |
| `/markets` | `frontend/src/pages/markets/index.tsx` | Fallback source pending | Fallback data unavailable | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| shared public/trader charts | `frontend/src/components/charts/V2RealtimeMarketChart.tsx` | data source pending / raw chart source status | Data source unavailable / current market chart source | yes before cleanup | CHECKED PENDING RERUN |
| shared public/trader charts | `frontend/src/components/charts/V2ProfessionalMarketChart.tsx` | AI signal | AI signal | no | IN PROGRESS, pending rerun |
| `/trade` | `frontend/src/components/trade/PaperOrderTicket.tsx` | Paper staging is disabled until a verified paper-only execution policy is available. | Paper staging is disabled until a verified paper-only execution policy is available. | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/PaperOrderTicket.tsx` | Paper staging is disabled because exchange-route safety evidence is unavailable. | Paper staging is disabled because exchange-route safety evidence is unavailable. | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/SymbolHeader.tsx`, `frontend/src/components/trade/TradeTerminal.tsx` | Trader account linked / Account binding incomplete / Sign in for trader account binding | Trader account linked / Account scope incomplete / Sign in for trader account scope | no | CHECKED PENDING RERUN |
| `/market/:symbol` | `frontend/src/hooks/useMarketDetail.ts` | Active signal was withheld because symbol evidence is unavailable. / Active signal was withheld because it belongs to another symbol. | Signal evidence unavailable for this market | no | CHECKED PENDING RERUN |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Data status` / training-row count | `Data freshness` / `Freshness checked` | no | Updated in `dashboard_internal_status_copy_hardened`; pending visual rerun. |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Trainer` / `System` active unit labels | `Signals` / `Platform` trader-safe labels | no | Updated in `dashboard_internal_status_copy_hardened`; pending visual rerun. |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Active signals` / `Current AI Signal` | `Market signals` / `Current Market Signal` | no | Updated in `dashboard_market_signal_copy_hardened`; pending visual rerun. |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | `Hold` for missing signal evidence | `Signal unavailable` | no | Updated in `trade_terminal_missing_signal_copy_hardened`; pending visual rerun. |
| `/trade` | `frontend/src/components/trade/SymbolHeader.tsx` | hardcoded `Signal fallback data` tooltip source | actual signal source state | no | Updated in `trade_symbol_header_signal_source_copy_hardened`; pending visual rerun. |

## 2026-06-14 Paper Order Validation Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `backend/app/api/v2/market_contracts.py` via paper order preview/submit friendly reason | `Enter a valid market symbol` | `Enter a valid market symbol` | no | APPROVED: malformed paper order symbols are blocked with trader-safe copy, not raw enum text. |

## 2026-06-14 Paper Order Fallback Metadata Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/api/v2Orders.ts` unavailable order envelopes | malformed symbol metadata omitted | malformed symbol metadata omitted | no | APPROVED: unavailable envelopes do not reflect unsafe order-symbol input. |

## 2026-06-14 Market Contract Validation Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `backend/app/api/v2/market_contracts.py` structured unavailable response | `Enter a valid market symbol` | `Enter a valid market symbol` | no | APPROVED: malformed public market symbols fail closed with trader-safe copy. |
| `/market/:symbol` | `backend/app/api/v2/market_contracts.py` structured unavailable response | `Select a supported chart timeframe` | `Select a supported chart timeframe` | no | APPROVED: unsupported chart timeframes fail closed with trader-safe copy. |
| `/trade` | `backend/app/api/v2/market_contracts.py` market stream unavailable response | `Enter a valid market symbol` | `Enter a valid market symbol` | no | APPROVED: malformed market-stream symbols fail closed with trader-safe copy. |
| `/trade` | `backend/app/api/v2/market_contracts.py` market stream unavailable response | `Select a supported chart timeframe` | `Select a supported chart timeframe` | no | APPROVED: unsupported market-stream timeframes fail closed with trader-safe copy. |

## 2026-06-14 Frontend Market API Validation Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/api/v2Market.ts` local unavailable envelope | `Enter a valid market symbol.` | `Enter a valid market symbol.` | no | APPROVED: malformed frontend market symbols fail closed with trader-safe copy. |
| `/market/:symbol` | `frontend/src/api/v2Market.ts` local unavailable envelope | `Select a supported chart timeframe.` | `Select a supported chart timeframe.` | no | APPROVED: unsupported frontend chart timeframes fail closed with trader-safe copy. |

## 2026-06-14 Signal Symbol Filter Validation Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `backend/app/api/v2/market_contracts.py` and `frontend/src/api/v2Signals.ts` signal unavailable envelope | `Enter a valid market symbol` | `Enter a valid market symbol` | no | APPROVED: malformed signal filters fail closed with trader-safe copy. |
| `/market/:symbol` | `backend/app/api/v2/market_contracts.py` and `frontend/src/api/v2Signals.ts` signal unavailable envelope | `Enter a valid market symbol.` | `Enter a valid market symbol.` | no | APPROVED: malformed signal filters fail closed with trader-safe copy. |

## 2026-06-14 Alert Symbol Mutation Validation Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/alerts` | `backend/app/api/v2/alerts_contracts.py` and `frontend/src/api/v2Alerts.ts` alert unavailable envelope | `Enter a valid market symbol` | `Enter a valid market symbol` | no | APPROVED: malformed alert symbols fail closed with trader-safe copy. |
| `/alerts` | `frontend/src/api/v2Alerts.ts` local unavailable envelope | `Enter a valid market symbol.` | `Enter a valid market symbol.` | no | APPROVED: malformed alert symbols fail closed before fetch with trader-safe copy. |

## 2026-06-14 Market Stream Status Validation Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `backend/app/api/v2/market_contracts.py` stream-status unavailable envelope | `Enter a valid market symbol` | `Enter a valid market symbol` | no | APPROVED: malformed stream-status symbols fail closed with trader-safe copy. |
| `/trade` | `backend/app/api/v2/market_contracts.py` stream-status unavailable envelope | `Enter a valid market symbol` | `Enter a valid market symbol` | no | APPROVED: malformed stream-status symbols fail closed with trader-safe copy. |

## 2026-06-14 Market Detail Route Symbol Guard Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/hooks/useMarketDetail.ts` route-derived state | `Invalid market symbol` | `Invalid market symbol` | no | APPROVED: malformed route symbols show designed invalid state. |
| `/market/:symbol` | `frontend/src/hooks/useSymbolData.ts` unavailable envelope | `Enter a valid market symbol.` | `Enter a valid market symbol.` | no | APPROVED: invalid route symbols withhold fallback market detail with trader-safe copy. |

## 2026-06-14 Market Detail Route Symbol Validation Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/hooks/useMarketDetail.ts` route invalid state | `Invalid market symbol` | `Invalid market symbol` | no | APPROVED: malformed route symbols are shown as designed unavailable state, not market identity. |
| `/market/:symbol` | `frontend/src/hooks/useSymbolData.ts` and `frontend/src/hooks/useMarketDetail.ts` unavailable envelope | `Enter a valid market symbol.` | `Enter a valid market symbol.` | no | APPROVED: invalid route symbols fail closed with trader-safe copy. |

## 2026-06-14 Account Scope Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` scoped account reason | `Trader-scoped portfolio response unavailable or withheld` | `Trader-scoped portfolio response unavailable or withheld` | no | APPROVED: explains row/account withholding without exposing internals. |
| `/api/v2/portfolio` | `backend/app/api/v2/market_contracts.py` warning | `Unscoped or mismatched fallback positions were withheld from authenticated trader account view` | `Unscoped or mismatched fallback positions were withheld from authenticated trader account view` | no | APPROVED: data-honesty warning for account isolation. |

## 2026-06-14 ProChart Data-Honesty Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` source posture | `Fallback candles withheld` | `Fallback candles withheld` | no | APPROVED: fallback candles are not presented as realtime chart data. |
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` source posture | `Stale candles withheld` | `Stale candles withheld` | no | APPROVED: stale chart data is explicit and not promoted as live. |
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` source posture | `Current candle source` | `Current candle source` | no | APPROVED: describes fresh API/repository candle data. |

## 2026-06-14 Standalone ProChart Data-Honesty Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` source title | `static chart overlays and AI targets withheld until current indicator evidence exists` | `static chart overlays and AI targets withheld until current indicator evidence exists` | no | APPROVED: makes static overlay withholding explicit. |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` empty state | `Current candle data unavailable. Static or stale chart snapshots are withheld from the primary chart until a current API, repository, or read-only public stream source is available.` | same | no | APPROVED: public-safe chart data-honesty state. |

## 2026-06-14 ProChart Indicator Control Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` control | `EMA unavailable` | `EMA unavailable` | no | APPROVED: clearly disables unavailable live indicator. |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` control | `BB unavailable` | `BB unavailable` | no | APPROVED: clearly disables unavailable live indicator. |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` control | `AI target unavailable` | `AI target unavailable` | no | APPROVED: avoids presenting static target as live. |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` tooltip | `Indicator source unavailable; static chart-file indicators are withheld.` | same | no | APPROVED: data-honesty copy for disabled controls. |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` control | `OI unavailable` | `OI unavailable` | no | APPROVED: disabled until typed derivatives overlay exists. |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` control | `L/S unavailable` | `L/S unavailable` | no | APPROVED: disabled until typed derivatives overlay exists. |

## 2026-06-14 Typed Market Indicators Contract Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/api/v2/market/:symbol/indicators` | `backend/app/api/v2/market_contracts.py` warning | `Indicator source unavailable` | `Indicator source unavailable` | no | APPROVED: structured missing indicator state. |
| `/api/v2/market/:symbol/indicators` | `backend/app/api/v2/market_contracts.py` warning | `Static chart-file indicators are withheld and are not presented as live` | `Static chart-file indicators are withheld and are not presented as live` | no | APPROVED: prevents fake-live indicator interpretation. |

## 2026-06-14 Market Detail Indicator Evidence Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` health copy | `Indicator source unavailable` | `Indicator source unavailable` | no | APPROVED: trader-safe source gap. |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` missing state | `Indicators unavailable` | `Indicators unavailable` | no | APPROVED: visible indicator gap state. |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` missing detail | `EMA, Bollinger Bands, and AI target overlays require a current indicator source.` | same | no | APPROVED: clear explanation without fake-live implication. |

## 2026-06-14 Trade Chart Indicator Gap Copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` toolbar | `MA unavailable` | `MA unavailable` | no | APPROVED: explicit missing indicator state. |
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` toolbar | `EMA unavailable` | `EMA unavailable` | no | APPROVED: explicit missing indicator state. |
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` toolbar | `VWAP unavailable` | `VWAP unavailable` | no | APPROVED: explicit missing indicator state. |
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` toolbar | `RSI unavailable` | `RSI unavailable` | no | APPROVED: explicit missing indicator state. |
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` toolbar | `MACD unavailable` | `MACD unavailable` | no | APPROVED: explicit missing indicator state. |
| `/trade`, `/market/:symbol` | `frontend/src/components/trade/TradingChartPanel.tsx` stats | `Indicator source unavailable` | `Indicator source unavailable` | no | APPROVED: source gap is visible and trader-safe. |

## Account readiness copy update - 2026-06-14

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/components/trade/TradeTerminal.tsx` | `Account readiness` | `Account readiness` | no | APPROVED: trader-specific readiness label. |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | `Trader account readiness scoped` | `Trader account readiness scoped` | no | APPROVED: signed-in scope is present. |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | `Trader account readiness incomplete` | `Trader account readiness incomplete` | no | APPROVED: designed incomplete-state copy. |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | `Sign in for trader readiness` | `Sign in for trader readiness` | no | APPROVED: public read-only sign-in state. |

## Market detail signal scope copy update - 2026-06-14

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/hooks/useMarketDetail.ts` | `Active signal was withheld because it is not scoped to this trader account.` | `Active signal was withheld because it is not scoped to this trader account.` | no | APPROVED: data-isolation warning. |

## Derivatives source-validation copy update - 2026-06-14

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | `Source validation` | `Source validation` | no | APPROVED: derivatives evidence posture label. |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | `Source evidence pending` | `Source evidence pending` | no | APPROVED: honest missing derivatives source evidence state. |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | `Source evidence verified` | `Source evidence verified` | no | APPROVED: only shown when sanitized artifact validates. |

## Public status derivatives copy update - 2026-06-14

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/status` | `frontend/src/pages/public-status/index.tsx` | `Derivatives data` | `Derivatives data` | no | APPROVED: public-safe data posture label. |
| `/status` | `frontend/src/pages/public-status/index.tsx` | `Derivatives source evidence pending` | `Derivatives source evidence pending` | no | APPROVED: honest missing source-evidence state. |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | `EMA`, `BB`, `AI target unavailable` | Approved typed-indicator controls; AI target remains disabled until typed prediction overlay exists | no | IN PROGRESS, pending validation rerun |
| `/chart/:symbol` | `backend/app/api/v2/market_contracts.py` | `EMA and Bollinger indicators are derived from Binance public USD-M closed klines` | Approved source/freshness wording | no | IN PROGRESS, pending validation rerun |
| shared public/trader missing states | `frontend/src/components/trading/TradingPrimitives.tsx` | `Data source unavailable` | `Data source unavailable` | yes before cleanup | IN PROGRESS, pending validation rerun |
| shared public/trader charts | `frontend/src/components/charts/V2RealtimeMarketChart.tsx` | `Data source unavailable` and raw chart source path subtitle | `Data unavailable`, `Data source unavailable`, public-safe source label | yes before cleanup | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChartSymbolPanel.tsx` | `Favorites`, `Markets`, `Search symbol...` | Approved watchlist/navigation copy; favorites are user-scoped when authenticated | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 continuation public/trader copy cleanup

| Route/surface | Component/file | Previous visible string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| public shell | `frontend/src/components/banners/LiveBlockBanner.tsx` | runtime-derived live-gate details and allowlist hints | `Paper / read-only mode active`; `Live trading disabled` | yes before cleanup | IN PROGRESS, pending validation rerun |
| public shell | `frontend/src/components/layout/PublicShell.tsx` | runtime-derived paper state and order guard text | `Paper mode: Read-only`; `Trading safety: Live trading disabled` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | runtime-derived live-gate status and allowlisted symbol count | `Live Trading: Disabled`; `Market coverage` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/markets` | `frontend/src/pages/markets/index.tsx` | `source key pending`; lowercase provider state copy | `Data source unavailable`; professional source-state copy | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/chart/:symbol` | `frontend/src/components/charts/ProChartSymbolPanel.tsx` | fallback-only favorites | signed-in trader watchlist first; fallback favorites only for public/read-only | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 ProChart overlay render and trader-scope copy continuation

| Route/surface | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| public/trader shell | `frontend/src/components/layout/PublicShell.tsx` | `Account scope`, `Paper account`, `Exchange link`, `Trading safety: Live trading disabled` | Approved signed-in account posture copy | no | IN PROGRESS, pending validation rerun |
| `/chart/:symbol` | `frontend/src/pages/pro-chart/index.tsx` | `Authenticated trader account`, `Trader account linked`, `read-only`, `Live trading disabled` | Approved account-scope and safety posture copy | no | IN PROGRESS, pending validation rerun |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | `Native public stream + candle source`, `Current candle source`, `Fallback/stale candles withheld`, `Candle source unavailable` | Approved source posture copy | no | IN PROGRESS, pending validation rerun |
| `/chart/:symbol` | `frontend/src/components/charts/ProChartSymbolPanel.tsx` | `Favorites`, `Markets`, `Search symbol...`, `No symbols match` | Approved symbol-panel copy; API overview is primary source | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 markets watchlist copy continuation

| Route/surface | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/markets` | `frontend/src/pages/markets/index.tsx` | `Favorites`, `Watchlist`, `Columns`, `Data quality` | Approved trader screener controls; favorites are backend-user scoped when authenticated | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 trade symbol-selector copy continuation

| Route/surface | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/components/trade/SymbolHeader.tsx` | `Select symbol`, `Professional paper trading terminal` | Approved symbol-selector copy; symbol universe includes signed-in watchlist | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 public shell session-aware nav copy

| Route/surface | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| public/trader shell | `frontend/src/components/layout/PublicShell.tsx` | `Sign In` for unsigned users; `Account` for signed-in users | Approved session-aware public navigation copy | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 account settings exchange-copy cleanup

| Route/surface | Component/file | Previous visible string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `read_only`, `no trading`, `account access pending/configured`, `live_trading_enabled=false` | `read only`, `Read-only access`, `Live trading disabled`, `Account access pending/configured` | yes before cleanup | CHECKED PENDING RERUN |

## 2026-06-14 account watchlist editor copy

| Route/surface | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `Market symbols`, `Save watchlist`, `Watchlist saved.`, `Symbols are saved to your signed-in trader profile and used by Markets, Trade, and ProChart.` | Approved trader-owned preference copy | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 account settings ID/copy cleanup

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `Trader ID`, raw `trader_id`, raw `paper_account_id` | `Trading profile`, `Paper workspace`, `Connected` / `Unavailable` | yes before cleanup | CHECKED PENDING RERUN |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `server admin`, direct credential-management wording | `server-side vault`, metadata-only account link copy | yes before cleanup | CHECKED PENDING RERUN |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | backend error/detail strings such as `invalid_watchlist_symbol` | friendly account-setting error messages | yes before cleanup | CHECKED PENDING RERUN |

## 2026-06-14 account settings no-scope copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | raw scope failure / backend-only `trader_account_scope_required` | `Exchange linking requires an assigned trader profile and paper workspace.` | yes before cleanup | CHECKED PENDING RERUN |
| `/trade` and `/chart/:symbol` | `frontend/src/hooks/useTraderContext.ts`, `frontend/src/components/trade/TradeTerminal.tsx` | backend-oriented credential tooltip / `Credential` label | `Read-only account access checked; no private values are exposed; live trading disabled`, `Account access` | yes before cleanup | CHECKED PENDING RERUN |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `Credential configured`, `Credential pending`, `Credential binding` | `Account access configured`, `Account access pending`, `Account access is managed through the secure account-link workflow` | yes before cleanup | CHECKED PENDING RERUN |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` safety notice | `Use read-only exchange credentials only`, `credential references` | `Use read-only exchange access only`, `account access references` | yes before cleanup | CHECKED PENDING RERUN |
| `/trade` | `frontend/tests/e2e/trade_terminal_redesign.spec.ts` expected visible copy | `Credential source unavailable` | `Account access source unavailable` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/dashboard` | `frontend/src/components/trading/ProfitTargetMonitorPanel.tsx` compact mode | `Trainer`, `Hedging`, `Live margin`, `Strategy weight` visible on trader dashboard | Hidden from compact trader-facing panel; full details remain outside the compact dashboard context | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/dashboard` | `frontend/src/components/trading/ProfitTargetMonitorPanel.tsx` compact title | `10K Monthly Net-Profit Objective` | `Paper Performance Objective` | no | IN PROGRESS, pending validation rerun |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` account-link form hint | `It never accepts API keys or secrets directly.` | `It never accepts private exchange values directly.` | yes before cleanup | CHECKED PENDING RERUN |
| `/trade` and `/chart/:symbol` | `frontend/src/hooks/useTraderContext.ts` account-access tooltip | `no secret values are exposed` | `no private values are exposed` | yes before cleanup | CHECKED PENDING RERUN |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` backend account-link errors | `unsupported_exchange`, `exchange_account_exists` | `That exchange is not available for account linking yet.`, `That exchange account is already linked.` | yes before cleanup | CHECKED PENDING RERUN |
| `/account-settings` API response | `backend/app/api/auth_rbac.py` account-link warnings | `Credential binding`, `Raw API keys` | `Account access setup`, `Private exchange values` | yes before cleanup | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChartSymbolPanel.tsx` missing price | bare dash | `Data unavailable` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/trade` | `frontend/src/components/trade/TradeTerminal.tsx` account strip | `Binding` | `Account scope` | yes before cleanup | CHECKED PENDING RERUN |
| public/trader shell | `frontend/src/components/layout/PublicShell.tsx` paper account state | `Sign in for trader account` | `Sign in for trader account scope` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` stream chips | `Realtime` for stream envelopes, `Current` for fresh non-stream typed data, `Waiting for stream frame` before first frame | same | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` stats strip | bare dash for missing OI/L/S/funding | `Data unavailable` | yes before cleanup | IN PROGRESS, pending validation rerun |

## 2026-06-14 incomplete trader scope and chart source copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| public/trader shared context | `frontend/src/hooks/useTraderContext.ts` | `Authenticated trader account` for signed-in users even when paper scope is incomplete | `Trader scope verified` only when trader and paper account scope exist; otherwise `Account scope incomplete` | yes before cleanup | CHECKED PENDING RERUN |
| `/portfolio/executions` | `frontend/src/pages/executions/index.tsx` | `Credential` | `Account access` | yes before cleanup | CHECKED PENDING RERUN |
| `/portfolio/history` | `frontend/src/pages/history/index.tsx` | `Credential` | `Account access` | yes before cleanup | CHECKED PENDING RERUN |
| chart panels | `frontend/src/components/charts/V2ProfessionalMarketChart.tsx` | `Realtime candle source` for fresh API/repository candles | `Current candle source` unless stream-backed realtime evidence exists | yes before cleanup | CHECKED PENDING RERUN |

## 2026-06-14 trade symbol source attribution copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/components/trade/SymbolHeader.tsx`, `frontend/src/hooks/useTradeTerminal.ts` | endpoint-unavailable tooltip copy for API/stream ticker values | active API/stream ticker source when available; unavailable copy only when source is missing | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 ProChart candle status copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | `Live forming candle`, `Live closed candle` | `Stream forming candle`, `Stream closed candle`, `Current candle update` | yes before cleanup | IN PROGRESS, pending validation rerun |

## 2026-06-14 public shell paper workspace copy guard

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| public/trader shell | `frontend/src/components/layout/PublicShell.tsx`, `frontend/src/hooks/useTraderContext.ts` | `Paper account linked`, raw account-ID-oriented shell risk | `Paper workspace connected`, `Paper workspace unavailable` with no raw `trader_id` or `paper_account_id` values | yes before cleanup | CHECKED PENDING RERUN |

## 2026-06-14 account settings trader approval copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | raw backend `trader_role_required` | `Trader approval is required before linking an exchange account.` | yes before cleanup | CHECKED PENDING RERUN |

## 2026-06-14 landing data-honesty copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | `Real-time derivatives markets`, training-row feed-quality ratio | `Current market snapshots`, `Data quality: Fallback snapshot available` | yes before cleanup | IN PROGRESS, pending validation rerun |

## 2026-06-14 trader context exchange availability copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| public/trader account surfaces | `frontend/src/hooks/useTraderContext.ts` | `Account scope incomplete` for scoped traders missing exchange metadata | `Exchange account unavailable` | yes before cleanup | CHECKED PENDING RERUN |

## 2026-06-14 portfolio state-contract copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/portfolio` | `frontend/src/pages/positions/index.tsx` | raw trader/paper account ID metrics and stale account fields | friendly `Trader`, `Account`, `Account access`, `Account scope`, and current paper-balance labels | yes before cleanup | IN PROGRESS, pending validation rerun |

## 2026-06-14 ProChart route realtime posture copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/pages/pro-chart/index.tsx` | chart route lacked a page-level read-only realtime/source posture | `Read-only market data`, `Realtime source: Binance public stream when frames arrive; public REST candle backfill when needed`, `Trader scope`, `Live trading disabled` | no | CHECKED PENDING RERUN |

## 2026-06-14 market screener missing-state copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/markets` | `frontend/src/pages/markets/index.tsx` | bare dash for missing long/short source | `Data source unavailable` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |

## 2026-06-14 account settings missing profile copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | bare dash for missing username/email | `Unavailable` | yes before cleanup | CHECKED PENDING RERUN |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `signed-in trader profile` | `signed-in trader profile` | yes before cleanup | IN PROGRESS, pending validation rerun |
| account API response | `backend/app/api/auth_rbac.py` | `signed-in user` | `signed-in user` | yes before cleanup | IN PROGRESS, pending validation rerun |
| account API response | `backend/app/api/auth_rbac.py` | `secure backend workflow` | `secure account-link workflow` | yes before cleanup | IN PROGRESS, pending validation rerun |

## 2026-06-14 shared chart source terminology

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| chart-bearing public/trader routes | `frontend/src/components/charts/V2ProfessionalMarketChart.tsx` | `Chart contract connected`, `Typed candle contract returned ...` | `Current candle source`, product-safe candle-source unavailable copy | yes before cleanup | CHECKED PENDING RERUN |

## 2026-06-14 derivatives/research/AI data-source terminology

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/derivatives` | `frontend/src/pages/liquidation-bridge/index.tsx` | `Current data source`, `unavailable-source` | `Current data source`, `Data source unavailable` / durable source unavailable copy | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/research` | `frontend/src/pages/market-intelligence/index.tsx` | `Current data source checked`, `durable typed research API` | `Data source checked`, `durable research API` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/index.tsx` | `signal sources` | `signal sources` | yes before cleanup | IN PROGRESS, pending validation rerun |

## 2026-06-14 chart/trade source terminology follow-up

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol`, `/trade` | `frontend/src/pages/market/index.tsx`, `frontend/src/components/trade/TradingChartPanel.tsx`, `frontend/src/components/trade/PositionsTable.tsx`, `frontend/src/components/trade/RecentTradesTape.tsx` | `unavailable-source`, `data-source wording`, `positions source`, `recent-trades source`, `candle data` | durable source / candle source / recent-trades source wording | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/status`, `/alerts` | `frontend/src/pages/public-status/index.tsx`, `frontend/src/pages/alerts/index.tsx` | `safe status source`, `alert source`, `Alert source present` | `safe status source`, `alert source`, `Alert source present` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/status` | `frontend/src/pages/public-status/index.tsx` | `backend live-gate controls` | `safety controls` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/portfolio/executions` | `frontend/src/pages/executions/index.tsx` | `backend-confirmed trader` | `signed-in trader` | yes before cleanup | IN PROGRESS, pending validation rerun |
| `/` | `frontend/src/pages/public-landing-v2/meta.ts` | `operator controls` / `admin controls` | `private controls` | yes before cleanup | CHECKED PENDING RERUN |
| `/ai-predictions/model-state`, `/portfolio/executions` | `frontend/src/pages/productNavigation.ts` | `Model runtime`, `exchange responses`, `strategy source` | `Model state`, `venue response status`, `strategy context` | yes before cleanup | CHECKED PENDING RERUN |

## Phase 14A continuation - trader-specific data and chart copy cleanup

| Route | Component/file | Previous string/state | Approved string/state | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/pages/pro-chart/index.tsx` | `Realtime source: Binance public stream when frames arrive; public REST candle backfill when needed` | same | no | CHECKED PENDING RERUN |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | `current API, repository, or stream source` plus source/endpoint tooltip details | `current market data source` and product-safe stale/current tooltip | yes before cleanup | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/TradingChartPanel.tsx`, `TradeShared.tsx` | endpoint/source IDs in chart missing states and source tooltips | product-safe market data source copy; endpoint hidden by default | yes before cleanup | CHECKED PENDING RERUN |
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | paper runtime signal preview | `/api/v2/signals` read-only signal preview with stale/unavailable guard | no | IN PROGRESS - pending validation |
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | `Confidence from validated paper path only` | `Read-only preview; sign in for trader-specific evidence` | no | IN PROGRESS - pending validation |
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | `source pending` | `Signal source unavailable` | yes, weak source copy | IN PROGRESS - pending validation |
| `/dashboard` | `frontend/src/pages/mission-control/meta.ts` | `Global health, alerts, and readiness across the V2 control plane.` | `Trader portfolio, market signal, and paper-mode readiness overview.` | yes | IN PROGRESS - pending validation |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | unscoped paper runtime symbol/freshness fallback | trader-scoped trade/account freshness only | no | IN PROGRESS - pending validation |
| `/markets` | `frontend/src/pages/markets/index.tsx` | unscoped paper runtime symbol/freshness fallback | market screener sources only; no paper runtime fallback | no | IN PROGRESS - pending validation |
| `/trade` | `frontend/src/components/trade/SymbolHeader.tsx` | unscoped paper runtime freshness fallback | scoped terminal/account freshness only | no | IN PROGRESS - pending validation |
| `/trade/paper` | `frontend/src/pages/paper-trading/index.tsx` | legacy paper trading page | redirect to canonical `/trade` paper terminal | no | IN PROGRESS - pending validation |

## Phase 14A continuation - public/trader runtime decoupling copy

| Route | Component/file | Previous string/state | Approved string/state | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | direct runtime ingestor/chart payload market preview | typed `/api/v2/market/overview` and `/api/v2/market/{symbol}/ticker` preview, unavailable state when absent | yes before cleanup | IN PROGRESS - pending validation |
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | `Market coverage` | `Market universe` | yes before cleanup | IN PROGRESS - pending validation |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | direct runtime truth / portfolio-state / system-observability status | trader-scoped paper account, trade terminal context, read-only prediction rows, and safe market aggregate status | yes before cleanup | IN PROGRESS - pending validation |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | runtime risk classification | `Paper guard active` | yes before cleanup | IN PROGRESS - pending validation |

## Phase 14A continuation - portfolio account source copy

| Route | Component/file | Previous string/state | Approved string/state | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/portfolio` | `frontend/src/pages/positions/index.tsx` | `Typed account source` | `Trader account source` | yes before cleanup | IN PROGRESS - pending validation |

## Phase 14A continuation - trade mode and risk scope copy

| Route | Component/file | Previous string/state | Approved string/state | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade`, `/portfolio/executions`, `/portfolio/history` | `frontend/src/hooks/useTradeTerminal.ts` | visible mode derived from terminal/runtime payload state | `Paper read-only mode` | yes before cleanup | IN PROGRESS - pending validation |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | risk fallback from unscoped paper runtime risk record | scoped risk record only; otherwise `Risk result unavailable` | yes before cleanup | IN PROGRESS - pending validation |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | model version fallback from runtime state | scoped signal model only; otherwise `Model unavailable` | yes before cleanup | IN PROGRESS - pending validation |
| `/trade` | `frontend/src/components/trade/SymbolHeader.tsx` | header freshness could fall back to terminal payload timestamp | header freshness uses scoped account timestamp only | no | IN PROGRESS - pending validation |

## Phase 14A continuation - raw trader identifier tooltip cleanup

| Route | Component/file | Previous string/state | Approved string/state | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/components/trade/TradeTerminal.tsx` | raw `trader_id` in trader tooltip | friendly trader display name only | yes before cleanup | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/TradeTerminal.tsx` | backend detail strings in account/access tooltips | generic read-only account-scope explanations | yes before cleanup | CHECKED PENDING RERUN |

## Phase 14A continuation - activity source label sanitization

| Route | Component/file | Previous string/state | Approved string/state | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/signals`, `/portfolio/executions`, `/portfolio/history` | `frontend/src/hooks/useTradeTerminal.ts` activity sources | raw API/repository/static source IDs could reach source metrics | `Trader signal source`, `Trader order source`, `Trader execution source`, `Paper audit source`, `Fallback data`, or unavailable states | yes before cleanup | CHECKED PENDING RERUN |
| `/trade`, `/portfolio`, `/dashboard` | `frontend/src/hooks/useTradeTerminal.ts` market/account source labels | raw source path, endpoint, repository, or stream IDs could reach headers/tooltips | `Current market data`, `Read-only market stream`, `Trader account source`, and specific unavailable states | yes before cleanup | CHECKED PENDING RERUN |

## Phase 14A continuation - trade legacy runtime removal

| Route | Component/file | Previous string/state | Approved string/state | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade`, `/portfolio`, `/signals`, `/portfolio/executions`, `/portfolio/history` | `frontend/src/hooks/useTradeTerminal.ts` | direct legacy operator terminal, paper runtime, portfolio-state, and live-gate runtime fallback state | typed trader/account/activity contracts, read-only market stream/contracts, and designed unavailable states | yes before cleanup | IN PROGRESS - pending validation |
| `/portfolio` | `frontend/src/pages/positions/index.tsx` | defensive literal check for legacy runtime source path | generic fallback source label only | yes before cleanup | IN PROGRESS - pending validation |
| `/trade`, `/market/:symbol` | `frontend/src/hooks/useSymbolData.ts` | `Static market terminal fallback` | Removed direct legacy fallback; typed API unavailable state remains visible | no | IN PROGRESS, pending validation |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` | stale derivative overlays after unavailable fetch | OI and long/short overlays clear when derivative source is unavailable | no | IN PROGRESS, pending validation |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | `Fill paper` / `Cancel paper` | Render only for active trader-scoped local paper rows with exchange-route mutation flags disabled | no | IN PROGRESS, pending validation |
| `/trade` | `frontend/src/components/trade/OpenOrdersTable.tsx` | `Paper action unavailable` | Local paper actions withheld unless row has explicit local paper repository evidence | no | IN PROGRESS, pending validation |

## 2026-06-14 continuation string ledger additions

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/dashboard` and trader app shell | `frontend/src/components/layout/AdminShell.tsx` | `Data freshness` | `Data freshness` | no | APPROVED - validation pending |
| `/dashboard` and trader app shell | `frontend/src/components/layout/AdminShell.tsx` | `Paper guard active` | `Paper guard active` | no | APPROVED - validation pending |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Market universe` | `Market universe` | no | APPROVED - validation pending |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Current V2 market overview` | `Current market overview` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Overview current` | `Overview current` | no | APPROVED - validation pending |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Fallback data` | `Fallback data` | no | APPROVED - validation pending |
| `/markets` | `frontend/src/pages/markets/index.tsx` | `Market overview source unavailable` | `Market overview source unavailable` | no | APPROVED - validation pending |
| `/markets` | `frontend/src/pages/markets/index.tsx` | `public symbols, current` | `public symbols, current` | no | APPROVED - validation pending |
| `/markets` | `frontend/src/pages/markets/index.tsx` | `public symbols, stale` | `public symbols, stale` | no | APPROVED - validation pending |

Operational strings `Ingestors`, `Failed`, `Redis`, and `Data rows` remain admin/superadmin shell-only after the shell telemetry remediation and must not appear in trader-visible app chrome.

| `/dashboard` and trader app shell | `frontend/src/components/layout/AdminShell.tsx` | `Read-only market stream` | `Read-only market stream` | no | APPROVED - validation pending |
| `/dashboard` and trader app shell | `frontend/src/components/layout/AdminShell.tsx` | `Market stream reconnecting` | `Market stream reconnecting` | no | APPROVED - validation pending |

| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `read-only public market stream and typed candles` | `read-only public market stream and typed candles` | no | APPROVED - validation pending |

## 2026-06-14 public/trader source wording continuation

| Route | Component/file | Current string/state | Approved string/state | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | `Market contract available` | `Market data available` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/trade` | `frontend/src/components/trade/PaperOrderTicket.tsx` | `Exchange route`, `Live trading disabled` | same | no | CHECKED 2026-06-14, pending validation rerun |
| `/trade` | `frontend/src/components/trade/PaperOrderTicket.tsx` | `Policy source unavailable` | `Policy check unavailable` | no | CHECKED 2026-06-14, pending validation rerun |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | `Trader-scoped exchange read-only account source unavailable` | `Exchange read-only account source unavailable` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` | `Trader-scoped exchange read-only account response unavailable or withheld` | `Exchange read-only account response unavailable or withheld` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/dashboard`, `/portfolio`, `/trade` | `frontend/src/hooks/usePaperAccountTruth.ts` | `operator_runtime/v2_portfolio_state/latest/v2_portfolio_state.json` | `Trader paper account source` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/trade`, `/chart/:symbol`, `/account-settings` | `frontend/src/hooks/useTraderContext.ts` | all-caps exchange/account type labels | title-case exchange/account labels such as `Binance USD-M Futures` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/chart/:symbol`, `/dashboard`, `/market/:symbol`, `/trade` | `frontend/src/components/charts/ProChart.tsx` | source ID plus endpoint path in tooltip | current/read-only/stale/unavailable market-data posture | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/signals`, `/ai-predictions`, `/dashboard` | `frontend/src/components/realtimeSignals/PredictionSignalExplanationPanel.tsx` | `raw + calibration + action edge` | `model confidence, calibration, and action edge` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/signals`, `/ai-predictions`, `/dashboard` | `frontend/src/components/realtimeSignals/PredictionSignalExplanationPanel.tsx` | `Live order status` | `Live trading guard` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/signals`, `/ai-predictions`, `/dashboard` | `frontend/src/components/realtimeSignals/PredictionSignalExplanationPanel.tsx` | `Coverage` | `Data completeness` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/signals`, `/ai-predictions`, `/dashboard` | `frontend/src/components/realtimeSignals/PredictionSignalExplanationPanel.tsx` | `Coverage gap` | `Data gap` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |
| `/signals`, `/ai-predictions`, `/dashboard` | `frontend/src/components/realtimeSignals/PredictionSignalExplanationPanel.tsx` | `What Website Controls Do` | `Signal explanation guide` | yes before cleanup | CHECKED 2026-06-14, pending validation rerun |

## 2026-06-14 ProChart fallback watchlist data-quality copy

| route | component/file | current string | approved string | forbidden? | copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/components/charts/ProChartSymbolPanel.tsx` fallback favorites | `BTCUSDT`, `ETHUSDT`, `SOLUSDT`, `BNBUSDT`, `XRPUSDT`, `LINKUSDT`, `LTCUSDT`, `AVAXUSDT`, `ADAUSDT` | Approved public fallback symbols; signed-in trader watchlist remains primary | no | IN PROGRESS, pending validation rerun |

## 2026-06-14 Trader Copy Hardening Continuation

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/components/trade/TradingChartPanel.tsx` | `Candle update` | Approved replacement for previous stream-candle label; unfinished candles remain display-only | no | CHECKED PENDING RERUN |
| `/trade` | `frontend/src/components/trade/PaperOrderTicket.tsx` | `Exchange route` | Approved replacement for previous live-exchange label; live trading disabled remains visible | no | CHECKED PENDING RERUN |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Exchange order state` | Approved disabled exchange-order posture label | no | CHECKED PENDING RERUN |
| `/` | `frontend/src/pages/public-landing-v2/index.tsx` | `Fallback market snapshot` | Approved replacement for legacy runtime-source wording | no | CHECKED PENDING RERUN |
| shared trader shell | `frontend/src/components/layout/PageShell.tsx` | `Data source unavailable`, `Trading mode`, `Trading safety`, `Paper PnL source`, `Route production source`, `CoinAnk read-only market source` | Approved source-safe shell copy replacing runtime/payload/legacy wording | no | CHECKED PENDING RERUN |

## 2026-06-14 update - browser storage copy hygiene

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| shared public/trader shell | `frontend/src/components/layout/ThemeToggle.tsx` | `ai_bot_v2_theme` localStorage key | `alphaforge_theme` with one-time legacy-key migration/removal | yes if retained in browser state | FIXED - pending validation |

## 2026-06-14 update - market liquidation stream copy

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | generic liquidation feed unavailable only | `Liquidation stream`, `Stream active`, `Liquidation levels`, `Data source unavailable` | no | IN PROGRESS - pending validation |

## Phase 15 account settings copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `Account labels cannot contain private exchange values.` | `Account labels cannot contain private exchange values.` | no | CHECKED - explains disabled metadata-only link state without exposing raw backend terms. |

## Phase 15 ProChart copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/components/charts/ProChartSymbolPanel.tsx` | `Data source unavailable` | `Data source unavailable` | no | CHECKED - honest missing-source state for symbol sidebar. |
| `/chart/:symbol` | `frontend/src/components/charts/ProChartSymbolPanel.tsx` | `Stale data` | `Stale data` | no | CHECKED - honest stale-state chip for symbol sidebar. |

## Phase 15 Signals copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/signals` | `frontend/src/components/realtimeSignals/RealtimeSignalVisibilityPanel.tsx` | `account-specific signal row withheld for this trader scope` | `account-specific signal row withheld for this trader scope` | no | CHECKED - explains multi-trader row filtering without raw account IDs. |

## Phase 15 Alerts copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/alerts` | `frontend/src/pages/alerts/index.tsx` | `Alert source unavailable` | `Alert source unavailable` | no | CHECKED - replaces contradictory source-present unavailable copy. |
| `/alerts` | `frontend/src/pages/alerts/index.tsx` | `Trader-scoped paper alerts for market, derivatives, signal, and risk events.` | `Trader-scoped paper alerts for market, derivatives, signal, and risk events.` | no | CHECKED - describes scoped paper records without implying live delivery. |
| `/alerts` | `frontend/src/pages/alerts/index.tsx` | `Notification delivery remains disabled until the production delivery service and audit evidence are complete.` | `Notification delivery remains disabled until the production delivery service and audit evidence are complete.` | no | CHECKED - honest remaining blocker copy. |

## Phase 15 Portfolio copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/portfolio` | `frontend/src/pages/positions/index.tsx` | `Trader account source` | `Trader account source` | no | CHECKED - prevents scoped typed portfolio data from being mislabeled as fallback data. |
| `/portfolio` | `frontend/src/pages/positions/index.tsx` | `Fallback account data withheld` | `Fallback account data withheld` | no | CHECKED - honest withheld fallback account state. |
| `/portfolio` | `frontend/src/pages/positions/index.tsx` | `Trader-specific account source required` | `Trader-specific account source required` | no | CHECKED - honest missing account scope/source state. |

## Phase 15 Derivatives copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/derivatives` | `frontend/src/pages/liquidation-bridge/index.tsx` | `Partial derivatives source` | `Partial derivatives source` | no | CHECKED - prevents overclaiming complete/current derivatives coverage when missing fields remain. |
| `/derivatives` | `frontend/src/pages/liquidation-bridge/index.tsx` | `Liquidation stream` | `Liquidation stream` | no | CHECKED - source-honest stream status label. |
| `/derivatives` | `frontend/src/pages/liquidation-bridge/index.tsx` | `Liquidation levels` | `Liquidation levels` | no | CHECKED - source-honest liquidation-level status label. |
| `/derivatives` | `frontend/src/pages/liquidation-bridge/index.tsx` | `Stale stream status` | `Stale stream status` | no | CHECKED - avoids presenting stale runtime evidence as active realtime data. |

## Phase 15 Research copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/research` | `frontend/src/pages/market-intelligence/index.tsx` | `Research source pending` | `Research data unavailable` | yes | SUPERSEDED - later row records updated unavailable-state copy. |
| `/research` | `frontend/src/pages/market-intelligence/index.tsx` | `Partial market context` | `Partial market context` | no | CHECKED - distinguishes market context from durable research data. |
| `/research` | `frontend/src/pages/market-intelligence/index.tsx` | `Research API` | `Research API` | no | CHECKED - professional missing API label without internal/debug terms. |

## Phase 15 Backtests copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/backtests` | `frontend/src/pages/strategy-backtesting/index.tsx` | `Paper account context only` | `Paper account context only` | no | CHECKED - prevents paper-account metrics from being read as backtest evidence. |
| `/backtests` | `frontend/src/pages/strategy-backtesting/index.tsx` | `They are not backtest results and do not prove strategy performance.` | `They are not backtest results and do not prove strategy performance.` | no | CHECKED - honest source/evidence boundary. |
| `/backtests` | `frontend/src/pages/strategy-backtesting/index.tsx` | `Backtest API` | `Backtest API` | no | CHECKED - professional missing API label. |

## Phase 15 AI predictions copy update - 2026-06-15

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/index.tsx` | `Paper forecast evidence only` | `Paper forecast evidence only` | no | CHECKED - prevents forecast UI from being read as live or performance proof. |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/index.tsx` | `Forecast evidence is not strategy-performance proof and does not approve live trading.` | `Forecast evidence does not prove strategy performance and does not approve live trading.` | yes | SUPERSEDED - later row records updated evidence-boundary copy. |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/index.tsx` | `Prediction source` | `Prediction source` | no | CHECKED - source label for current typed signal state. |

## 2026-06-14 `/markets/symbols` copy cleanup

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Current V2 symbol universe, provider coverage, trainer quality, and paper/backtest edge state.` | `Read-only symbol universe, account watchlist coverage, market data freshness, and forecast evidence availability.` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Realtime Market Charts And Universe Health` | `Market Chart Coverage And Symbol Health` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `CUDA Trainer Symbol Edge` | `Signal Quality Coverage` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Trainer And Edge Proof` | `Forecast Evidence Coverage` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | raw runtime/file-path source copy | read-only market snapshots and labeled fallback copy | yes | REDUCED, pending screenshot/test rerun |

## 2026-06-15 `/markets/symbols` and ProChart source-copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Aggregate source: /operator_runtime/...` | `Aggregate source: Ingestor health summary` | yes | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | raw provider paths | `KuCoin market source`, `CoinAPI REST source`, `CoinAPI stream source`, `CoinAnk derivatives source` | yes | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | raw ingestor/recommendation enum values | friendly status/recommendation labels | yes | UPDATED, pending screenshot/test rerun |
| `/chart/:symbol` | `frontend/src/pages/pro-chart/index.tsx` | `Realtime source: Binance public stream when frames arrive; public REST candle backfill when needed` | `Market data source: read-only public stream when frames arrive; public REST candle backfill when needed` | no | UPDATED, pending screenshot/test rerun |
| typed account APIs | `backend/app/api/v2/market_contracts.py` | local repository/fallback filesystem paths | `Trader account repository`, `Fallback runtime snapshot` | yes | UPDATED, pending backend/frontend rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `All-symbol chart payload status` | `All-symbol chart source status` | yes | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | raw provider status/freshness/classification/blocker values | friendly product status labels | yes | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Operator gate remains closed for live/canary execution.` | `Live and canary execution remain disabled.` | yes | UPDATED, pending screenshot/test rerun |

## 2026-06-15 public/trader product-copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/`, `/status`, `/dashboard` | `frontend/src/components/realtimeWebsite/RealtimeDataAtlasPanel.tsx` | runtime-key-derived public labels such as trainer/orchestrator labels | `Platform status`, `Market screener`, `Signal model source`, `Signal arbitration`, `Paper trading state` | yes | UPDATED, pending screenshot/test rerun |
| `/`, `/status`, `/dashboard` | `frontend/src/components/realtimeWebsite/RealtimeDataAtlasPanel.tsx` | `Public view summarizes safe market, trainer, signal, and paper-mode feeds.` | `Public view summarizes safe market, signal, and paper-mode data feeds.` | yes | UPDATED, pending screenshot/test rerun |
| `/dashboard` | `frontend/src/pages/mission-control/meta.ts` | admin surface metadata | app surface metadata | yes | UPDATED, pending route/test rerun |
| `/dashboard` | `frontend/src/pages/mission-control/route.ts` | `/admin/mission-control` raw route metadata | `/dashboard` | yes | UPDATED, pending route/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `read-only runtime chart` | `read-only market chart` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Professional OHLCV, TA, Signal Chart` | `Professional Market Chart` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `CUDA trainer symbol edge table` | `Signal quality by-symbol table` | yes | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Trainer rows` | `Signal sample rows` | yes | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Ingestor`, `Writes`, `Keys`, raw ingestor names | `Source`, `Updates`, source labels | yes | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Live And Canary Controls` | `Trading Safety State` | yes | UPDATED, pending screenshot/test rerun |
| `/trade` | `frontend/src/pages/trader/meta.ts` | admin surface metadata and orchestration wording | app surface metadata and account-scoped market evidence wording | yes | UPDATED, pending route/test rerun |
| `/trade` | `frontend/src/components/trade/TradingChartPanel.tsx` | `Read-only Binance USD-M public REST poll; no signed account data and no exchange mutation.` | `Read-only public REST candle source; no signed account data and no trading action.` | no | UPDATED, pending screenshot/test rerun |
| `/trade` | `frontend/src/components/trade/TradingChartPanel.tsx` | `Native public stream + candle source` | `Public market stream + candle source` | no | UPDATED, pending screenshot/test rerun |
| `/trade` | `frontend/src/components/trade/TradingChartPanel.tsx` | `Current Binance public candles` | `Current public exchange candles` | no | UPDATED, pending screenshot/test rerun |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | `Runtime level evidence at ...` | `Liquidation level evidence at ...` | yes | UPDATED, pending screenshot/test rerun |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | `Binance public funding history, read-only` | `Public funding history, read-only` | no | UPDATED, pending screenshot/test rerun |
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` | `Binance public open interest history, read-only` | `Public open interest history, read-only` | no | UPDATED, pending screenshot/test rerun |
| `/market/:symbol` | `frontend/src/pages/market/meta.ts` | implementation-focused route description | source-aware market detail description | no | UPDATED, pending route/test rerun |
| `/login` | `frontend/src/pages/login/meta.ts` | `Session creation. CSRF-protected. No internal IDs leaked.` | `Secure sign-in for AlphaForge accounts with read-only demo access separated from trader and admin roles.` | no | UPDATED, pending route/test rerun |
| `/status` | `frontend/src/pages/public-status/meta.ts` | `Public status. High-level health only; no internal IDs.` | `Public availability, data freshness, paper-mode posture, and incident status without sensitive system detail.` | no | UPDATED, pending route/test rerun |
| `/` | `frontend/src/pages/public-landing-v2/meta.ts` | `Evidence-cited, risk-gated overview of the paper-shadow exchange platform. No internal IDs or private controls.` | `Public overview of AlphaForge market intelligence, AI signal evidence, and paper-only trading posture.` | no | UPDATED, pending route/test rerun |
| `/` | `frontend/src/pages/public-landing-v2/meta.ts` | internal nav category metadata | public nav category metadata | yes | UPDATED, pending route/test rerun |
| `/chart/:symbol` | `frontend/src/pages/pro-chart/index.tsx` | `Binance USD-M · ...` | `Public market data · ...` | no | UPDATED, pending screenshot/test rerun |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | raw unmatched backend error text | `Account settings update unavailable.` | yes | UPDATED, pending route/test rerun |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `server-side vault` | `secure account-link workflow` | no | UPDATED, pending screenshot/test rerun |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `Live trading is blocked system-wide.` | `Live trading is blocked by platform policy.` | no | UPDATED, pending screenshot/test rerun |
| `/account-settings` | `frontend/src/pages/account-settings/index.tsx` | `Live trading remains disabled server-side and cannot be overridden from this page.` | `Live trading remains disabled and cannot be overridden from this page.` | no | UPDATED, pending screenshot/test rerun |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/meta.ts` | `Trainer Prediction Monitor` | `AI Predictions` | yes | UPDATED, pending route/test rerun |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/meta.ts` | `Reads evidence_packets + liveness_confidence_level. Subprocess boundary, no live mutation.` | `Trader-safe signal forecast page with direction, confidence, targets, risk context, and source freshness.` | yes | UPDATED, pending route/test rerun |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/route.ts` | `/admin/trainer-prediction-monitor` raw route metadata | `/ai-predictions` | yes | UPDATED, pending route/test rerun |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/index.tsx` | `Forecast evidence is not strategy-performance proof and does not approve live trading.` | `Forecast evidence does not prove strategy performance and does not approve live trading.` | yes | UPDATED, pending screenshot/test rerun |
| `/ai-predictions` | `frontend/src/pages/trainer-prediction-monitor/index.tsx` | `What the trainer is doing` | `What the signal model is doing` | yes | UPDATED, pending screenshot/test rerun |
| `/derivatives` | `frontend/src/pages/market-intelligence/index.tsx` | `remain source pending` | `remain unavailable until durable sources are connected` | yes | UPDATED, pending screenshot/test rerun |
| `/derivatives` | `frontend/src/pages/market-intelligence/index.tsx` | `Research source pending` | `Research data unavailable` | yes | UPDATED, pending screenshot/test rerun |
| `/signals` | `frontend/src/pages/signals/meta.ts` | admin surface with lineage-chain description | app surface with trader-facing signal description | yes | UPDATED, pending route/test rerun |
| `/alerts` | `frontend/src/pages/alerts/meta.ts` | `system alert readiness` | `account-risk alert readiness` | yes | UPDATED, pending route/test rerun |
| `/portfolio/history` | `frontend/src/pages/history/meta.ts` | admin/audit surface with fallback/native wording | app/portfolio surface with account-scoped history wording | yes | UPDATED, pending route/test rerun |
| `/portfolio` | `frontend/src/pages/positions/meta.ts` | admin/execution surface with generic paper-only description | app/portfolio surface with account-scoped positions description | yes | UPDATED, pending route/test rerun |
| `/portfolio/executions` | `frontend/src/pages/executions/meta.ts` | admin/execution surface with intents/fills wording | app/portfolio surface with account-scoped paper order history wording | yes | UPDATED, pending route/test rerun |
| `/trade` | `frontend/src/pages/trader/route.ts` | `/trader` raw route metadata | `/trade` | yes | UPDATED, pending route/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/meta.ts` | admin surface with generic universe member description | app surface with symbol universe, watchlist, freshness, and read-only tradability description | yes | UPDATED, pending route/test rerun |
| `/research` | `frontend/src/pages/market-intelligence/meta.ts` | admin market-intelligence metadata | app research metadata with read-only source freshness | yes | UPDATED, pending route/test rerun |
| `/research/technical-analysis` | `frontend/src/pages/technical-analysis/meta.ts` | live TA / no-placeholder overclaim | read-only chart overlay metadata with missing-data states | yes | UPDATED, pending route/test rerun |
| `/backtests` | `frontend/src/pages/strategy-backtesting/meta.ts` | admin strategy/backtesting metadata with live gate wording | app backtests metadata with paper-only review wording | yes | UPDATED, pending route/test rerun |
| `/backtests/replay` | `frontend/src/pages/replay/meta.ts` | admin replay metadata | app replay metadata for read-only trader review | yes | UPDATED, pending route/test rerun |
| `/signals` | `frontend/src/pages/signal-explainability/meta.ts` | `Per-signal lineage drilldown and confidence_explainability_block per CLAUDE.md.` | trader-facing signal rationale, confidence, target, risk, and source freshness metadata | yes | UPDATED, pending route/test rerun |
| `/ai-predictions/model-state` | `frontend/src/pages/ai-brain/meta.ts` | RL/MASA/PPO CUDA trainer runtime and live-control metadata | read-only model health and latest signal context metadata | yes | UPDATED, pending route/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Runtime symbol coverage meters` | `Symbol coverage meters` | yes | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Replay bundles` | `Review bundles` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `After-cost bps` | `After-cost signal` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `CI lower bps` | `Confidence lower bound` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `False +/-` | `False positive / negative` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Forecast edge proven` | `Forecast quality validated` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Primary blocker` | `Primary limiter` | no | UPDATED, pending screenshot/test rerun |
| `/markets/symbols` | `frontend/src/pages/symbols/index.tsx` | `Canary readiness` | `Safety test readiness` | yes | UPDATED, pending screenshot/test rerun |

## 2026-06-15 ProChart evidence panel copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/components/charts/V2ProfessionalMarketChart.tsx` | collapsed raw JSON evidence with backend-style keys | human-readable data evidence rows | yes | UPDATED, pending screenshot/test rerun |
| `/chart/:symbol` | `frontend/src/components/charts/V2ProfessionalMarketChart.tsx` | `RL target` | `AI target` | yes | UPDATED, pending screenshot/test rerun |
| `/chart/:symbol` | `frontend/src/components/charts/V2ProfessionalMarketChart.tsx` | `TA library pending` / library implementation detail | `Indicator method pending` / `Indicator method available` | no | UPDATED, pending screenshot/test rerun |

## 2026-06-15 public data atlas copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/`, `/status`, `/dashboard` | `frontend/src/components/realtimeWebsite/RealtimeDataAtlasPanel.tsx` | `Realtime data health` | `Data freshness` | no | UPDATED, pending screenshot/test rerun |
| `/`, `/status`, `/dashboard` | `frontend/src/components/realtimeWebsite/RealtimeDataAtlasPanel.tsx` | `Readable JSON feeds` | `Readable data sources` | no | UPDATED, pending screenshot/test rerun |
| `/`, `/status`, `/dashboard` | `frontend/src/components/realtimeWebsite/RealtimeDataAtlasPanel.tsx` | `live gate` | `live trading guard` | yes | UPDATED, pending screenshot/test rerun |
| `/`, `/status`, `/dashboard` | `frontend/src/components/realtimeWebsite/RealtimeDataAtlasPanel.tsx` | `feed could not be read` | `data source could not be read` | no | UPDATED, pending screenshot/test rerun |

## 2026-06-15 dashboard account-scope status copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Trader data checked` when only market aggregate data is available | `Market data checked; trader account data unavailable` | no | UPDATED, pending screenshot/test rerun |
| `/dashboard` | `frontend/src/pages/mission-control/index.tsx` | `Runtime status summary` | `Platform status summary` | yes | UPDATED, pending screenshot/test rerun |

## 2026-06-15 signals route contract correction

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/signals` | `frontend/src/pages/signals/route.ts` | `/admin/signals` route metadata for app-surface signal page | `/signals` | yes | UPDATED, pending route/test rerun |

## 2026-06-15 primary app route contract correction

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/portfolio` | `frontend/src/pages/positions/route.ts` | `/admin/positions` route metadata for app-surface portfolio page | `/portfolio` | yes | UPDATED, pending route/test rerun |
| `/portfolio/executions` | `frontend/src/pages/executions/route.ts` | `/admin/executions` route metadata for app-surface executions page | `/portfolio/executions` | yes | UPDATED, pending route/test rerun |
| `/research` | `frontend/src/pages/market-intelligence/route.ts` | `/admin/market-intelligence` route metadata for app-surface research page | `/research` | yes | UPDATED, pending route/test rerun |
| `/backtests` | `frontend/src/pages/strategy-backtesting/route.ts` | `/admin/strategy-backtesting` route metadata for app-surface backtests page | `/backtests` | yes | UPDATED, pending route/test rerun |

## 2026-06-15 secondary app legacy redirect inventory

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/admin/signal-explainability` | `frontend/src/pages/productNavigation.ts` / `frontend/src/pages/signal-explainability/route.ts` | legacy admin route metadata for app-surface signal evidence module | redirect-covered secondary module to `/signals` | yes if exposed | INVENTORIED, pending route/test rerun |
| `/admin/symbols` | `frontend/src/pages/productNavigation.ts` / `frontend/src/pages/symbols/route.ts` | legacy admin route metadata for app-surface symbols module | redirect-covered secondary module to `/markets` | yes if exposed | INVENTORIED, pending route/test rerun |
| `/admin/technical-analysis` | `frontend/src/pages/productNavigation.ts` / `frontend/src/pages/technical-analysis/route.ts` | legacy admin route metadata for app-surface technical-analysis module | redirect-covered secondary module to `/research` | yes if exposed | INVENTORIED, pending route/test rerun |
| `/admin/replay` | `frontend/src/pages/productNavigation.ts` / `frontend/src/pages/replay/route.ts` | legacy admin route metadata for app-surface replay module | redirect-covered secondary module to `/backtests` | yes if exposed | INVENTORIED, pending route/test rerun |

## 2026-06-15 secondary app legacy redirect tests authored

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/admin/signal-explainability` | `frontend/tests/e2e/trader_nav_cleanliness.spec.ts` | legacy signal explainability route unasserted in redirect coverage | asserts redirect to `/signals` and no signal-explainability/operator/payload/runtime copy | yes if exposed | TEST AUTHORED, pending run |
| `/admin/technical-analysis` | `frontend/tests/e2e/trader_nav_cleanliness.spec.ts` | legacy technical-analysis route unasserted in redirect coverage | asserts redirect to `/research` and no technical-analysis-runtime/operator/payload/live-gate copy | yes if exposed | TEST AUTHORED, pending run |

## 2026-06-15 ProChart indicator-control copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` control tooltip | generic indicator warning for every disabled overlay | field-specific EMA, Bollinger Bands, or AI target source-state tooltip | no | UPDATED, pending screenshot/test rerun |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` chart-source tooltip | `Static chart overlays and AI targets are withheld until current indicator evidence exists` for all indicator states | current typed indicator overlays listed when available; AI target remains source-pending when missing | no | UPDATED, pending screenshot/test rerun |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` AI target control | `AI target unavailable` | `AI target unavailable` with source-pending tooltip until typed prediction overlay exists | no | UPDATED, pending screenshot/test rerun |
| `/chart/:symbol` | `frontend/src/components/charts/ProChart.tsx` stream status chip | connected/current copy could appear while aggregate stream state was stale | `Stream data stale` | no | UPDATED, pending screenshot/test rerun |
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` market stream source label | connected copy could appear while aggregate stream state was stale | `Read-only market stream stale; using current market polling fallback` | no | UPDATED, pending screenshot/test rerun |

## 2026-06-15 trade activity-source scope label hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/trade` | `frontend/src/hooks/useTradeTerminal.ts` activity labels | `Trader order source`, `Trader execution source`, `Paper audit source`, `Trader signal source` could appear from unverified source envelopes | trader-specific labels only after matching `trader_id` plus `paper_account_id`; otherwise `Order source unavailable`, `Execution source unavailable`, `Paper audit event source unavailable`, or `Signal source unavailable` | no | UPDATED, pending screenshot/test rerun |

## 2026-06-15 market detail source-label copy hardening

| Route | Component/file | Current string | Approved string | Forbidden? | Copy QA status |
|---|---|---|---|---|---|
| `/market/:symbol` | `frontend/src/pages/market/index.tsx` source labels | `Typed API data` | `Current market data`, `Read-only market stream`, `Stale market data`, `Fallback data`, `Data source unavailable` | yes before cleanup | UPDATED, pending screenshot/test rerun |
