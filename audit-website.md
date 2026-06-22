# FULL WEBSITE AUDIT & PROFESSIONAL TRADING PLATFORM REDESIGN
**Audit Date:** June 12, 2026 — Updated with deep crawl  
**Scope:** Read-only — full frontend and backend inspection + verified source crawl  
**Original Auditor:** GitHub Copilot  
**Updated By:** Claude Code (Sonnet 4.6) — verified against raw source files  
**Source:** `/v2/frontend/` (React 18 + Vite + TypeScript) + `/v2/backend/app/` (FastAPI)  
**Reference Platforms:** Binance, KuCoin, CoinAnk, Bybit  
**Status:** LIVE TRADING BLOCKED — Paper/read-only mode confirmed

---

## TABLE OF CONTENTS
1. [Current Site Architecture](#1-current-site-architecture)
2. [Page-by-Page Audit](#2-page-by-page-audit)
3. [Design System Audit](#3-design-system-audit)
4. [Backend API Audit](#4-backend-api-audit)
5. [Authentication & RBAC Audit](#5-authentication--rbac-audit)
6. [Critical Problems & Deficiencies](#6-critical-problems--deficiencies)
7. [Redesign Vision & Architecture](#7-redesign-vision--architecture)
8. [New Page Structure Specification](#8-new-page-structure-specification)
9. [Design System Specification](#9-design-system-specification)
10. [Component Redesign Specifications](#10-component-redesign-specifications)
11. [Authentication Redesign](#11-authentication-redesign)
12. [Real-Time Data Architecture](#12-real-time-data-architecture)
13. [Implementation Roadmap](#13-implementation-roadmap)
14. [Developer Checklist](#14-developer-checklist)

---

## 1. CURRENT SITE ARCHITECTURE

### 1.1 Tech Stack
| Layer | Technology | Version |
|---|---|---|
| Framework | React | 18.3.1 |
| Build Tool | Vite | 8.x |
| Language | TypeScript | 5.6.2 |
| Router | react-router-dom | 6.30.4 |
| Charts | lightweight-charts | 5.2.0 |
| Charts (alt) | recharts | 3.8.1 |
| Icons | lucide-react | 1.17.0 |
| CSS | Custom CSS (6,923 lines) | — |
| Fonts | IBM Plex Mono, IBM Plex Sans | Google Fonts |
| Backend | FastAPI + uvicorn | Python |
| Data Source | Static JSON files in `/public/` + Redis payloads | — |

### 1.2 Entry Point & Routing
- `index.html` → title is "AI BOT V2 — Control Plane" (internal dev title, not a trading platform name)
- `App.tsx` → `RouterProvider` wrapping `createBrowserRouter`
- Root `/` redirects to `/dashboard`
- Two shells: `AdminShell` (protected, 260px sidebar + header + ticker) and `PublicShell` (minimal header)
- Wildcard `*` redirects to `/landing`

### 1.3 Shell Layout (AdminShell)
```
┌─────────────────────────────────────────────────────────────────────┐
│ LiveBlockBanner (sticky, z-1000)                                    │
├──────────────┬──────────────────────────────────────────────────────┤
│ Title: AI BOT│ admin-command-rail: 10 text chips (mode, live gate, │
│ V2 Trading   │ submit, paper pnl, training, data, last price, system│
│ Desk         │ units) + ThemeToggle                                 │
├──────────────┴──────────────────────────────────────────────────────┤
│ Top Nav: [Dashboard] [Markets] [Trade] [Derivatives] [Signals]      │
│          [AI Analysis] [Portfolio] [Research]                        │
├──────────────────────────────────────────────────────────────────────┤
│ Ticker Strip (5-column grid, 10 items, monospace, no animation)     │
├──────────┬───────────────────────────────────────────────────────────┤
│ Sidebar  │ Main Content Area                                         │
│ 260px    │                                                           │
│ Nav      │                                                           │
│ (all     │                                                           │
│ pages    │                                                           │
│ listed)  │                                                           │
└──────────┴───────────────────────────────────────────────────────────┘
```

### 1.4 Current RBAC Roles
| Role | Hierarchy | Access |
|---|---|---|
| `public` | 0 | Redirected to `/login` |
| `viewer` | 1 | Read-only app pages |
| `operator` | 2 | Trading pages + pipeline controls |
| `reviewer` | 3 | + system pages |
| `admin` | 4 | Full UI visibility |
| `live_approver` | 5 | Live trading authority |

**CRITICAL ISSUE**: Auth is browser-local session storage only. No real login. Role switching is a button in the browser.

---

## 2. PAGE-BY-PAGE AUDIT

### 2.1 Public Pages

#### `/landing` — Public Landing V2
- **State**: ✅ Implemented (306 lines)
- **What it shows**: Hero section, AI signal card, status bar, confidence meter
- **Data sources**: 10+ payload JSON files (paper runtime, portfolio, chart manifest, etc.)
- **Problems**:
  - Eyebrow text: "AI CRYPTO TRADING SYSTEM · PAPER SIMULATION" — generic, not branded
  - CTA buttons: "View Live Signals →" and "System Health" — not compelling, not professional
  - No real market data grid (Binance-style)
  - No symbol selector
  - No price charts on landing
  - Confidence meter is basic HTML/CSS bar, not animated
  - Hero title is plain: "Autonomous AI Trading Bot"
  - No exchange comparison or unique selling point
  - Status bar shows 4 cells (ingestors, trainer, predictions, live gate) — minimal
  - Stat row shows 4 numbers (price, equity, PnL, daily loss %) — not enough for a platform

#### `/status` — Public Status
- **State**: ✅ Implemented
- **What it shows**: Public system health overview
- **Problems**: Too simple, not useful as a public-facing page

#### `/login` — Login
- **State**: ✅ Implemented but fundamentally broken
- **What it shows**: 4 role-selector buttons: viewer, operator, reviewer, admin
- **Problems**:
  - This is NOT a real login. No credentials. No JWT. No session management.
  - A button click sets role in `sessionStorage` — accessible to anyone
  - "Local Role Selector" label on the page admits it's fake
  - No username/password fields
  - No multi-factor authentication
  - No trader-specific logins
  - Text: "Local role selection for the operator dashboard. This does not grant live authority and does not expose exchange keys." — literally tells users it's not real

---

### 2.2 App Pages (Trader-Facing)

#### `/dashboard` — Mission Control
- **State**: ✅ Most complete page (~1,577 lines)
- **What it shows**: Operator truth dashboard, charts, ingestor status, orchestrator, risk gateway, system atlas, paper online status, prediction status, trading platform panel, derivatives
- **Problems**:
  - Extremely dense — operators are overwhelmed by 20+ panels on one page
  - No visual hierarchy — everything looks the same weight
  - Panels are homogenous gray boxes
  - The page tries to be everything: market data + AI status + ingestor health + risk — should be split
  - Chart is `V2ProfessionalMarketChart` (lightweight-charts) — functional but not Binance-quality
  - No TradingView widget (there's a fallback wrapper but the chart is the internal one)
  - Header still says "AI BOT V2 Trading Desk" not a platform name
  - Chip-based status indicators are not visually compelling

#### `/markets` — Markets
- **State**: ✅ Implemented (~421 lines)
- **What it shows**: Markets table with AI predictions per timeframe, derivatives data, funding/OI, liquidation, alt data
- **Problems**:
  - Table has columns: symbol, price, confidence, move, timeframe coverage dots
  - No 24h change column
  - No volume column
  - No market cap
  - No sparkline charts per row (like CoinAnk)
  - Sort functionality exists but limited
  - No symbol search/filter in this view
  - No favorites system
  - No watchlist
  - Funding rate and OI panels exist but are below the fold, not integrated into the table
  - Real-time derivatives panel is separate, not inline

#### `/markets/symbols` — Symbols
- **State**: ✅ Implemented
- **What it shows**: Symbol universe with exchange availability
- **Problems**: Reads from a payload file. Limited columns. No market cap data. No volume. No trading view direct link.

#### `/market/:symbol` — Market Detail
- **State**: ✅ Implemented (~600 lines)
- **What it shows**: Per-symbol page with chart, alt data, top-10 panels, war room data, liquidation, orchestrator, trainer
- **Problems**:
  - Overwhelming amount of data panels
  - Still shows war room / codex queue data — not relevant to traders
  - Chart is functional but takes up only part of the page
  - No order book
  - No recent trades list
  - No buy/sell panel
  - No signal-overlaid chart
  - Symbol selector is a `<select>` dropdown — not a search box

#### `/trade` — Trader Page
- **State**: ✅ Implemented (~580 lines)
- **What it shows**: Chart, portfolio state, lineage, balance-aware hold status, live gate status, trade terminal
- **Problems**:
  - **This page should be the centerpiece of the platform — it is not**
  - No buy/sell order form (paper mode only, but form should exist)
  - No real-time order book
  - No recent trades tape
  - No position display in the main view
  - Chart is on the right side-ish — should dominate the entire left panel
  - Lots of technical text (LIVE_ARMED_BALANCE_HOLD, INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER) shown raw to users
  - Status chips are text-heavy: "live armed, balance hold"
  - No symbol selector bar (like Binance's symbol list on the left)
  - Lacks Binance-style: [Chart 70%] [Order Book 15%] [Trades 15%] layout

#### `/trade/paper` — Paper Trading
- **State**: ✅ Implemented
- **What it shows**: Paper account reporting, fill-gate evidence
- **Problems**: Should be integrated into the Trade page, not a separate page. Paper/Live toggle should be a switch.

#### `/derivatives` — Liquidation Bridge
- **State**: ✅ Implemented
- **What it shows**: Liquidations, funding, OI, long/short, basis
- **Problems**:
  - Data tables are basic HTML tables
  - No visualization (charts) for liquidation clusters
  - Funding rate shown as numbers only, no bar visualization
  - No time-series for OI
  - No exchange comparison charts

#### `/signals` — Signals
- **State**: ✅ Implemented (~265 lines)
- **What it shows**: Signal lineage chain, direction banner, all-timeframe predictions, ledger entries
- **Problems**:
  - Direction banner is good (colored), but too large
  - No signal timeline/history chart
  - No win/loss visualization
  - No confidence distribution histogram
  - The "signal direction banner" covers too much screen real estate
  - "paper signal held by current guard" — internal language, not user-friendly
  - No notification/alert when a new signal fires
  - Ledger entries shown as a basic list

#### `/ai-predictions` — Trainer Prediction Monitor
- **State**: ✅ Implemented
- **What it shows**: AI predictions with confidence, expected move, coverage
- **Problems**:
  - No gauge visualization for confidence (uses text/chip only)
  - No prediction accuracy history chart
  - No model performance metrics visualization
  - Column headers are technical: "confidence_calibrated", "expected_move_after_cost_bps"
  - No plain-English explanation of what each prediction means

#### `/ai-predictions/model-state` — AI Brain
- **State**: ✅ Implemented (~477 lines)
- **What it shows**: CUDA trainer status, training metrics, parallel rollout, prediction rows, lineage samples
- **Problems**:
  - Very technical — not usable by non-engineers
  - Training metrics (loss_before, loss_after, VRAM) shown as raw numbers with no context
  - No animated training progress visualization
  - No GPU utilization chart
  - No epoch/step progress bar
  - Text shows "Available examples: 847" — meaningless without context

#### `/portfolio` — Positions
- **State**: ✅ Implemented (~224 lines)
- **What it shows**: Paper positions, risk metrics, daily PnL, drawdown, kill switch status
- **Problems**:
  - Drawdown bar exists and is good — but isolated
  - Position table has columns but no P&L coloring
  - No unrealized PnL chart over time
  - No position entry/exit price on a chart
  - Kill switch status shown as "REQUIRED" / "Clear" — could be more visual
  - No portfolio value chart (equity curve)

#### `/portfolio/executions` — Executions
- **State**: ✅ Implemented (~290 lines)
- **What it shows**: Recent intents (paper fills), portfolio state, balance-aware hold, recovery/failover status
- **Problems**:
  - No execution timeline
  - "paper_fill_allowed: false" shown as text — needs coloring
  - Raw field names shown: "fee_gate_allowed", "churn_blocked" — not user-friendly
  - No fill price vs signal price comparison
  - No slippage visualization

#### `/portfolio/history` — History
- **State**: ✅ Implemented
- **What it shows**: Trade history
- **Problems**: Limited implementation. No 30-day equity curve chart. No trade journal style.

#### `/backtests` — Strategy Backtesting
- **State**: ✅ Implemented (~229 lines)
- **What it shows**: Edge proof, replay worker, paper shadow, execution ledger, CUDA gate metrics
- **Problems**:
  - Edge proof shown as a table — no equity curve
  - No visual backtest results (drawdown chart, trade distribution)
  - "PASS/FAIL/OPERATOR_DECISION_REQUIRED" status without visual context
  - PipelineControlPanel is useful but looks like a developer tool

#### `/backtests/replay` — Replay
- **State**: ✅ Implemented
- **What it shows**: Trader-facing signal and strategy replay
- **Problems**: Minimal implementation. No interactive timeline scrubber. No candle chart with overlaid decisions.

#### `/research` — Market Intelligence
- **State**: ✅ Implemented (~784 lines)
- **What it shows**: CoinAnk intel, ingestors, market ingestor, KuCoin, CoinAPI, feature pipeline, trainer, symbol universe, dynamic discovery, alt data
- **Problems**:
  - Too many technical panels (CoinAPI WSDS, feature pipeline, symbol universe scoring)
  - These are system monitoring panels, not research tools
  - No charted view of market intelligence data
  - No "research report" style layout
  - No CVD chart, no order flow chart
  - Alt data providers are tables, not visual scorecards

#### `/research/technical-analysis` — Technical Analysis
- **State**: ✅ Implemented
- **What it shows**: TA indicators, support/resistance
- **Problems**: TA data comes from payload files. No interactive overlay on charts. No indicator selector.

#### `/alerts` — Alerts
- **State**: ✅ Implemented (~106 lines)
- **What it shows**: Alert source coverage table, readiness
- **Problems**:
  - **NO ACTUAL ALERTS** — the page just shows a table of alert sources and their "readiness"
  - Text says "No executable alert actions are exposed" — this page does nothing useful for users
  - No alert history
  - No push notification integration
  - No price alert creation form
  - Alert table just shows "source present" or "alert stream contract source pending"

---

### 2.3 System Pages (Admin-Facing)

#### `/system` — System Health
- **State**: ✅ Implemented (~333 lines)
- **What it shows**: Ingestor inventory, runtime stats, CUDA trainer, paper runtime, risk/feature workers, signal publisher, system observability
- **Problems**:
  - No process uptime visualization
  - Ingestor tiles are plain
  - Worker health shown as text: "WORKER_HEALTHY" or "WORKER_DEGRADED"
  - No traffic-light style grid
  - System observability metrics are readable but not visualized
  - No real-time update animation

#### `/system/control-center` — Admin War Room
- **State**: ✅ Implemented (~394 lines)
- **What it shows**: War room cycle table, gap matrix, raw blocker matrix, actions applied, codex queue, full observation builder, legacy log intelligence, live canary status, payload explorer
- **Problems**:
  - This is an internal sprint/build tracking page — has no place in a trading platform UI
  - "War room cycles", "gap matrix", "codex queue" — developer concepts
  - Should be heavily restricted to admin only and redesigned as a true control center

#### `/system/health` — Monitor Center
- **State**: ✅ Implemented
- **What it shows**: Health monitoring
- **Problems**: Overlaps heavily with `/system`. Redundant.

#### `/system/ingestors` — Ingestors
- **State**: ✅ Implemented
- **What it shows**: Data ingestor pipeline status
- **Problems**: Table-based. No visual pipeline diagram. No latency charts.

#### `/system/trainer` — Trainer Admin
- **State**: ✅ Implemented
- **What it shows**: PipelineControlPanel + EdgeRecoveryQualityPanel + RealtimeSignalVisibilityPanel
- **Problems**: The page is three components stacked. No unified trainer dashboard. Missing training curves (loss over time).

#### `/system/orchestrator` — Orchestrator Admin
- **State**: ✅ Implemented (~279 lines)
- **What it shows**: Arbitration summary, CUDA trainer orchestrator lineage, attribution analysis, strategy recovery, actionability simulation
- **Problems**: Very technical. "Arbitration bucket winners" — internal terminology. No visualization of signal deconfliction flow.

#### `/system/risk-controllers` — Risk Control
- **State**: ✅ Implemented (~244 lines)
- **What it shows**: Risk gateway state, denial breakdown, CUDA trainer gate, live gate runtime
- **Problems**: 
  - Denial counts shown as a table — should be a pie/bar chart
  - "gate_always_blocked_invariant: true" — technical boolean, not user-friendly
  - No historical risk denial trend

#### `/system/strategy-controls` — Strategy Admin
- **State**: ✅ Implemented
- **What it shows**: Strategy configurations

#### `/system/execution` — Execution Admin
- **State**: ✅ Implemented
- **What it shows**: Execution control

#### `/system/exchanges` — Exchange Manager
- **State**: ✅ Implemented
- **What it shows**: Exchange API connections, Binance read-only probe

#### `/system/config` — Config Admin
- **State**: ✅ Implemented
- **What it shows**: System configuration parameters

#### `/system/logs` — Logs & Errors
- **State**: ✅ Implemented
- **What it shows**: Log entries, error counts

#### `/system/audit-ledger` — Audit Ledger
- **State**: ✅ Implemented
- **What it shows**: Cryptographic audit trail (SHA256 hashes)
- **Problems**: This is developer tooling. Should be a collapsed "Evidence" section only for admin.

#### `/system/scripts` — Script Registry
- **State**: ✅ Implemented
- **What it shows**: Script hash registry
- **Problems**: Developer tooling. Not useful as a nav item.

#### `/system/build-validation` — Build Validation Status
- **State**: ✅ Implemented
- **Problems**: CI/CD tooling — should not be in the operator nav.

#### `/system/coverage` — Coverage System Atlas
- **State**: ✅ Implemented
- **Problems**: Code coverage tooling — not operational.

#### `/system/migrations` — Permanent Migration
- **State**: ✅ Implemented
- **Problems**: Migration tracking — remove from public nav.

#### `/system/users` — User Status
- **State**: ✅ Implemented
- **Problems**: Shows a minimal status page. Not a real user management panel.

#### `/system/ai-tools` — Claude Admin AI
- **State**: ✅ Implemented
- **Problems**: AI developer assistant integration — internal tooling.

#### `/system/readiness` — Live Readiness
- **State**: ✅ Implemented
- **What it shows**: Pre-flight checklist for live trading
- **Problems**: This is actually useful — but needs redesign as a visual checklist/dashboard.

#### `/system/readiness/mobile` — Mobile Readiness
- **State**: ✅ Implemented
- **Problems**: Minimal page.

#### `/system/reports` — Report Center
- **State**: ✅ Implemented
- **What it shows**: Generated reports

#### `/system/position-quarantine` — Position Quarantine
- **State**: ✅ Implemented
- **What it shows**: External/manual position quarantine controls

#### `/system/evidence` — Operator Proof Dashboard
- **State**: ✅ Implemented
- **What it shows**: Evidence trail for proof-of-work
- **Problems**: Developer tooling.

#### `/system/executive-summary` — Executive Status
- **State**: ✅ Implemented
- **What it shows**: High-level summary for executives

#### `/system/build-code-review` — Codex Review Center
- **State**: ✅ Implemented
- **Problems**: AI code review tool — internal developer tooling. Remove from operator nav.

---

## 3. DESIGN SYSTEM AUDIT

### 3.1 Color Palette (Current)
```css
/* Light mode (default but not relevant — platform should be dark) */
--color-bg: #f4f6fa       /* light blue-gray */
--color-fg: #111827       /* near-black */

/* Dark mode */
--color-bg: #0b0f14       /* very dark navy */
--color-fg: #e6edf3       /* near-white */
--color-muted: #8b949e    /* gray */
--color-red: #b31b1b      /* muted red */
--color-amber: #b8860b    /* muted amber */
--color-green: #1f7a3a    /* muted green */
--color-border: #2b3138   /* dark border */
```

**Problems:**
- Red, amber, and green are too muted for a trading platform (need more vivid gain/loss colors)
- No blue accent for interactive elements
- No cyan for data highlights (like Binance uses)
- Missing variables for: chart background, buy color, sell color, neutral color, highlight color
- `--accent` is used but not defined in the theme variables (must be defined elsewhere in the 6,923-line CSS)

### 3.2 Typography (Current)
- IBM Plex Mono (300, 400, 500, 600) — used for data, labels, chips
- IBM Plex Sans (300, 400, 500, 600, 700) — body text
- IBM Plex Sans Condensed (500, 600) — headings
- Fallback: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`

**Assessment:** IBM Plex is a solid professional choice. However:
- Font weights are inconsistent across components
- h1 elements range from 20px (header) to 34px (design hero) — no typographic scale
- Metric values are 23px in analytics cards but 17px in trading cards — inconsistent
- No fluid typography (doesn't scale well on different screens)

### 3.3 Layout (Current)
- `AdminShell`: 260px sidebar + `minmax(0, 1fr)` main
- Ticker strip: 5-column fixed grid, no scroll
- Most pages: CSS Grid `gap: 16px`, max-width varies (1680px, 1760px, 1840px)
- Mobile: Limited consideration. There is a mobile readiness page but no responsive breakpoints visible in main CSS.

**Problems:**
- 260px sidebar leaves only ~1580px for content at 1920px
- Ticker strip is not a scrolling marquee (static 5-col grid)
- Pages have inconsistent max-widths
- No responsive grid for tablets/phones
- Sidebar is always visible, taking space even for simple pages

### 3.4 Component Inventory

| Component | File | Issues |
|---|---|---|
| `Panel` | cockpitComponents.tsx | Basic gray bordered box. No variants. |
| `Metric` | cockpitComponents.tsx | Small 74px block. Label is ALL CAPS, value is plain. |
| `AdminShell` | layout/AdminShell.tsx | Dense header, no logo, no real nav |
| `Nav` | layout/Nav.tsx | `<details>` groups, all pages listed, no icons |
| `PublicShell` | layout/PublicShell.tsx | Minimal header, brand is just text |
| `ThemeToggle` | layout/ThemeToggle.tsx | Exists, good |
| `LiveBlockBanner` | banners/ | Warning banner, appropriate |
| `V2ProfessionalMarketChart` | charts/ | lightweight-charts based, functional |
| `V2RealtimeMarketChart` | charts/ | SVG-based, simpler chart |
| `TradingPrimitives` | trading/ | `ChartPanel`, `StatusPill`, `MetricCard`, `DataFreshnessBadge`, `EvidenceDrawer` |
| `PipelineControlPanel` | trading/ | Pipeline control form |
| Various realtimeWebsite | components/ | MetricCard, FreshnessBadge, BlockerChip, etc. |
| `RealtimeSignalVisibilityPanel` | realtimeSignals/ | Signal stream table |

### 3.5 CSS Quality Issues
- The CSS file is 6,923 lines — monolithic, no CSS modules, no scoped styles
- Many duplicate selectors (e.g., `.nav__group-head` appears twice in the audited range)
- Mix of BEM naming, utility classes, and arbitrary class names
- No design tokens file — values are hardcoded in CSS (e.g., `#0a1016`, `#080d12`, `#0c1117`)
- z-index values are scattered (1000, 900, 890) — no centralized z-index scale
- No CSS custom property for buy/sell colors
- Light mode has almost no styling (default colors don't match the dark theme at all)
- No animation/transition system (no `--transition-fast`, `--transition-slow` tokens)

---

## 4. BACKEND API AUDIT

### 4.1 API Routes (v2)
| Route | Method | Auth | Purpose |
|---|---|---|---|
| `/api/v2/trainer/*` | GET | None | Trainer status summary |
| `/api/v2/pipeline/status` | GET | None | Pipeline status |
| `/api/v2/pipeline/run` | POST | operator+ | Trigger pipeline run |
| `/api/v2/trainer/summary` | GET | None | Trainer summary |
| `/api/v2/audit-ledger` | GET | None | Audit entries |
| `/api/v2/replay/*` | GET/POST | operator+ | Replay control |
| `/api/v2/public-status` | GET | None | Public system status |
| `/api/v2/ollama/*` | GET/POST | admin | Ollama AI assistant |
| `/api/v2/codex-reviews` | GET | reviewer+ | Codex review entries |
| `/api/v2/live-readiness` | GET | None | Live readiness check |

**Problems:**
- No WebSocket endpoints (`/ws/*`) — all data is polled from static JSON files
- No `/api/v2/market/*` endpoints — market data comes from static JSON files
- No `/api/v2/positions` endpoint — positions come from static JSON files
- No `/api/v2/signals` streaming endpoint
- No `/api/v2/portfolio` endpoint
- No real-time event stream (SSE or WebSocket) for any data
- Backend requires `operator` role for writes — but this is checked via the same fake session store
- `V2_TRAINER_MODE=stub` suppresses all trainer subprocess calls when environment is incomplete

### 4.2 Data Flow Problems
```
Current (broken) flow:
Background Workers → write JSON → /v2/frontend/public/ → Vite serves static files
→ Frontend polls these files every 5–30 seconds

Should be:
Redis/DB → FastAPI with WebSocket/SSE → Frontend subscribes to real-time updates
```

- The frontend uses `usePayloadFile(path, intervalMs)` — a custom polling hook
- Every page makes 5–15 simultaneous polling requests
- Some intervals are as low as 2,000ms (2 seconds) — polling 15 endpoints every 2s is inefficient
- No request deduplication or shared cache layer
- No error retry with exponential backoff

---

## 5. AUTHENTICATION & RBAC AUDIT

### 5.1 Current Auth (Fake)
```typescript
// auth/session.ts — simplified
sessionStorage.setItem('role', 'admin'); // This is the entire auth system
```

- Role is stored in `sessionStorage` as a plain string
- Anyone can open DevTools and run `sessionStorage.setItem('role', 'admin')`
- No JWT, no cookie, no server-side session validation
- No user identity — no username, no user ID
- No audit trail of who changed what
- `roleFromSearch(search)` reads role from URL query param: `/dashboard?role=admin` — any visitor can set admin

### 5.2 RBAC Reality
- RBAC looks functional but enforces nothing
- `canSeePage(role, minRole)` is client-side only
- A user can bypass by directly navigating to a URL with the right role in the query string
- No server-side role enforcement on any API endpoint except `pipeline/run` (operator+)
- `live_approver` role (highest) has no UI elements assigned to it

### 5.3 Missing Auth Features
- Real login form (username + password)
- Session token (JWT)
- Password hashing (bcrypt/argon2)
- Multi-user support with different trader accounts
- Per-user portfolio/history isolation
- Session expiry / refresh tokens
- Audit log of authenticated actions
- 2FA for live trading approval

---

## 6. CRITICAL PROBLEMS & DEFICIENCIES

### 6.1 UX/Design Problems (Severity: Critical)

| # | Problem | Impact | Page(s) |
|---|---|---|---|
| 1 | No professional brand identity — site is called "AI BOT V2" | First impression, trust | All pages |
| 2 | Login is fake — no real user accounts | Security, multi-user | /login |
| 3 | 260px sidebar shows 50+ pages — overwhelming | Navigation, focus | All protected pages |
| 4 | Header is dense text chips, not trading platform style | Professional perception | All protected pages |
| 5 | No scrolling ticker strip (static 5-column grid) | Real-time feel | All protected pages |
| 6 | Trade page has no order form | Core feature missing | /trade |
| 7 | No order book display | Core feature missing | /trade, /market |
| 8 | Alert page does nothing useful | Dead feature | /alerts |
| 9 | Raw technical strings shown to users (LIVE_ARMED_BALANCE_HOLD) | Confusing UX | Multiple |
| 10 | No notifications system | Real-time awareness | All |

### 6.2 Data Quality Problems (Severity: High)

| # | Problem | Impact |
|---|---|---|
| 1 | No WebSocket — all data is polled from static files | Stale data, poor UX |
| 2 | Some payload files still potentially stale (per prior audit) | Misleading data |
| 3 | Portfolio equity shown without clear "paper simulation" label | Misleading |
| 4 | Confidence shown as decimals (0.71) not percentages (71%) in some places | Confusing |
| 5 | "source pending" shown when data is missing — not an error message | Confusing |

### 6.3 Missing Platform Features (Severity: High)

| # | Feature | Reference Platform |
|---|---|---|
| 1 | Real-time symbol search with live prices | Binance |
| 2 | Full-screen professional chart with indicator selector | Binance, TradingView |
| 3 | Order book with real-time depth visualization | Binance, Bybit |
| 4 | Recent trades tape with buy/sell coloring | Binance |
| 5 | Paper trading buy/sell form with market/limit/stop types | All platforms |
| 6 | Portfolio equity curve chart (30/90/180 day) | All platforms |
| 7 | Notification center (alerts, signal fires, system events) | All platforms |
| 8 | Symbol watchlist / favorites | Binance, KuCoin |
| 9 | Multiple chart timeframe selector tabs (1m, 5m, 15m, 1h, 4h, 1d) | All platforms |
| 10 | Fear & Greed Index visual gauge | CoinAnk |
| 11 | Market heatmap visualization | CoinAnk |
| 12 | Funding rate heatmap (color-coded by symbol) | CoinAnk |
| 13 | Open Interest cumulative chart | CoinAnk |
| 14 | Liquidation map (price levels visualization) | CoinAnk, Bybit |
| 15 | Multiple trader accounts with separate portfolios | All platforms |

---

## 7. REDESIGN VISION & ARCHITECTURE

### 7.1 Target: Professional AI-Powered Trading Platform

**Brand Name Recommendation**: Replace "AI BOT V2" with a professional name like:
- **NeuralEdge** — signals AI intelligence and trading edge
- **AlphaForge** — forging alpha signals
- **QuantPulse** — quantitative pulse of the market

The website should feel like Binance/KuCoin in terms of layout professionalism, but with a unique AI-first identity.

### 7.2 Design Philosophy
- **Dark first**: All pages default to dark theme. No light mode for a trading platform.
- **Data density without clutter**: Display maximum useful data in minimum space — like Bloomberg Terminal but consumer-friendly
- **Color as language**: Green = positive/profit/buy, Red = negative/loss/sell, Amber = warning/pending, Cyan = AI/prediction, Purple = system
- **Real-time by default**: Every number that can change should animate or pulse when updated
- **Hierarchy of information**: Primary data (price, PnL, signals) is always visible. Secondary data (system health) is accessible but not dominant.

### 7.3 Proposed Information Architecture

```
PUBLIC (no auth)
├── / (Landing)           — Market pulse + bot overview + live prices
├── /markets (public)     — Top movers, funding, OI, fear & greed
└── /login                — Real login form

TRADER PORTAL (viewer+ role)
├── /dashboard            — Personalized trading dashboard
├── /trade                — Full-screen trading terminal (chart + book + tape + form)
│   └── /trade/:symbol    — Symbol-specific terminal
├── /markets              — Full market screener (like CoinAnk)
│   ├── /markets/screener — Screener with all columns
│   └── /markets/heatmap  — Visual heatmap
├── /portfolio            — Portfolio overview (equity curve + positions)
│   ├── /portfolio/positions   — Open positions
│   ├── /portfolio/history     — Trade history + journal
│   └── /portfolio/performance — PnL analytics
├── /signals              — Signal stream with lineage
│   ├── /signals/live     — Real-time signal feed
│   └── /signals/history  — Historical signal performance
├── /ai                   — AI intelligence hub
│   ├── /ai/predictions   — Multi-symbol predictions with confidence
│   ├── /ai/model         — Model state, training progress
│   └── /ai/features      — Feature importance explorer
├── /derivatives          — Derivatives analytics
│   ├── /derivatives/funding    — Funding rate board
│   ├── /derivatives/oi         — Open interest
│   ├── /derivatives/liquidations — Liquidation map
│   └── /derivatives/long-short — Long/short ratios
├── /backtests            — Backtesting & replay
│   ├── /backtests/edge   — Edge proof & performance
│   └── /backtests/replay — Interactive market replay
├── /research             — Research & analysis
│   ├── /research/ta      — Technical analysis
│   └── /research/intel   — Market intelligence
└── /alerts               — Alert management (real alerts)

ADMIN PORTAL (admin role — separate page/subdomain)
├── /admin                — Admin dashboard
├── /admin/system         — Full system health
├── /admin/trainer        — Trainer management
├── /admin/orchestrator   — Orchestrator control
├── /admin/risk           — Risk gateway controls
├── /admin/execution      — Execution control
├── /admin/exchanges      — Exchange connections
├── /admin/ingestors      — Data pipeline health
├── /admin/config         — System configuration
├── /admin/users          — User management
├── /admin/readiness      — Live readiness checklist
└── /admin/logs           — System logs

SUPER-ADMIN ONLY
├── /admin/audit          — Audit ledger
├── /admin/evidence       — Operator proof
└── /admin/ai-tools       — AI assistant tools
```

### 7.4 User Roles (Redesigned)

| Role | Description | Default Route |
|---|---|---|
| `guest` | Not logged in, public pages only | `/` |
| `trader` | Logged-in user, trader portal | `/dashboard` |
| `admin` | Admin portal access | `/admin` |
| `superadmin` | Full access + live trading approval | `/admin` |

**Each trader** should have:
- Username + password (hashed, server-validated)
- Personal watchlist
- Personal alert preferences
- Paper trading account (isolated)
- Trading history (isolated)
- Session JWT (30-day expiry)

---

## 8. NEW PAGE STRUCTURE SPECIFICATION

### 8.1 Global Layout (Trader Portal)

```
┌──────────────────────────────────────────────────────────────────────────┐
│ TOPBAR (64px, sticky)                                                    │
│ [Logo+Name] [Symbol Search (live dropdown)] [Price Ticker Scroll] [Notif] [Avatar] │
├──────────────────────────────────────────────────────────────────────────┤
│ SECONDARY NAV (40px, sticky)                                             │
│ [Dashboard] [Trade] [Markets] [Signals] [AI] [Derivatives] [Portfolio]  │
│ [Backtests] [Research] [Alerts]                                          │
├──────────────────────────────────────────────────────────────────────────┤
│ CONTENT AREA (fills remaining height)                                    │
│                                                                          │
│ (No left sidebar — all navigation is in topbar/secondary nav)           │
└──────────────────────────────────────────────────────────────────────────┘
```

**Key change from current**: Remove the 260px left sidebar entirely. Move all navigation to a horizontal secondary nav bar.

---

### 8.2 Dashboard Page (`/dashboard`)

**Layout: 3-zone dashboard**

```
┌─────────────────────────────────────────────────────────────────────┐
│ OVERVIEW STRIP (6 KPI cards, horizontally scrollable)               │
│ [Portfolio Value] [Today's PnL] [Live Gate] [Active Signals]        │
│ [AI Confidence] [System Status]                                      │
├───────────────────────────────┬─────────────────────────────────────┤
│ MAIN CHART (70%)              │ SIDE PANEL (30%)                    │
│ V2ProfessionalMarketChart     │ ┌─────────────────────────────────┐ │
│ (BTCUSDT default, symbol      │ │ Current AI Signal Card          │ │
│ selector tabs on top)         │ │ Direction: LONG ▲               │ │
│ [1m][5m][15m][1h][4h][1d]     │ │ Confidence: 73%  ████████░░     │ │
│                               │ │ Symbol: BTCUSDT · 5m            │ │
│                               │ │ Expected: +12.4 bps             │ │
│                               │ └─────────────────────────────────┘ │
│                               │ ┌─────────────────────────────────┐ │
│                               │ │ Open Positions (2)              │ │
│                               │ │ BTCUSDT LONG  +$127  +0.14%     │ │
│                               │ │ ETHUSDT SHORT -$43   -0.08%     │ │
│                               │ └─────────────────────────────────┘ │
│                               │ ┌─────────────────────────────────┐ │
│                               │ │ Market Pulse (Fear & Greed)     │ │
│                               │ │ 🟡 NEUTRAL 52                   │ │
│                               │ │ BTC Dom: 52.4%                  │ │
│                               │ └─────────────────────────────────┘ │
├───────────────────────────────┴─────────────────────────────────────┤
│ SYSTEM STATUS STRIP (horizontal, 8 tiles)                           │
│ [Data] [AI] [Risk] [Exchange] [Paper] [Trainer] [Orchestrator]     │
└─────────────────────────────────────────────────────────────────────┘
```

**Each KPI card**: Large number (36px), label (11px), change arrow + delta, live pulse dot if real-time

**Color coding**:
- Portfolio value: white
- PnL positive: `#00d4a3` (teal-green, like Binance)
- PnL negative: `#ef4444` (red)
- Live gate enabled: `#00d4a3`
- Live gate blocked: `#f59e0b` (amber)

---

### 8.3 Trade Page (`/trade`)

**This is the flagship page — full trading terminal**

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│ SYMBOL HEADER                                                                       │
│ [BTCUSDT] $97,432.50 ▲ +1.24% 24h | High: $98,100 Low: $95,200 Vol: $42.1B       │
│ [AI Signal: LONG 73%] [Risk: APPROVED] [Paper Mode] [ETHUSDT] [BNBUSDT] [SOLUSDT]│
├──────────────────────────────────────────────────────────┬──────────────────────────┤
│ CHART AREA (60% width, full height left)                 │ ORDER BOOK (20% width)  │
│                                                          │ Asks (sell orders):      │
│ TradingView-style chart                                  │ $97,500  12.4 BTC  RED  │
│ (lightweight-charts with professional theme)             │ $97,480  8.1 BTC        │
│                                                          │ $97,460  15.3 BTC       │
│ [1m][3m][5m][15m][1h][4h][1d][1w] tabs                  │ ─────── SPREAD ───────  │
│ Indicators: [MA] [BB] [RSI] [MACD] [Volume] [...]        │ $97,440  9.2 BTC        │
│                                                          │ $97,420  22.7 BTC  GRN  │
│ AI signal overlays: target price line, entry markers    │ Bids (buy orders):       │
├──────────────────────────────────────────────────────────┤                          │
│ RECENT TRADES TAPE (below chart)                         │ Depth chart mini         │
│ Time    Price     Qty    Side                            │                          │
│ 14:32   $97,441  0.12   🟢 Buy                           ├──────────────────────────┤
│ 14:32   $97,440  0.45   🔴 Sell                          │ ORDER PANEL              │
│ 14:31   $97,438  1.23   🟢 Buy                           │ [Market] [Limit] [Stop] │
│                                                          │                          │
│                                                          │ [🟢 BUY / LONG]         │
│                                                          │ Amount: ______ USDT      │
│                                                          │ Leverage: [1x] [5x] [10x]│
│                                                          │ Est. margin: $X          │
│                                                          │ [PAPER BUY LONG] btn     │
│                                                          │ (disabled if not paper)  │
├──────────────────────────────────────────────────────────┴──────────────────────────┤
│ POSITIONS & RECENT EXECUTIONS (collapsible panel at bottom)                         │
│ [Positions] [Open Orders] [Trade History] [AI Analysis]                             │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

### 8.4 Markets Screener (`/markets`)

**CoinAnk-style professional screener**

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ GLOBAL STATS BAR                                                               │
│ Total Crypto Cap: $3.2T ▲  24h Vol: $128B  BTC Dom: 52.4%  ETH Dom: 17.2%   │
│ Fear & Greed: 52 NEUTRAL  Funding Avg: +0.012%  Active Symbols: 25           │
├────────────────────────────────────────────────────────────────────────────────┤
│ TABS: [Overview] [AI Signals] [Derivatives] [Funding] [Liquidations]          │
├────────────────────────────────────────────────────────────────────────────────┤
│ SCREENER TABLE                                                                 │
│ Filters: [All] [Trending] [High AI Confidence] [Bullish] [Bearish]            │
│ Search: [🔍 Symbol or name...]                                                 │
│                                                                                │
│ Symbol  Price      24h%   Vol    OI       Funding   L/S    AI Conf  Signal   │
│ BTC     $97,432  +1.24%  $42B   $18.2B   +0.012%   1.62x  73%↑    LONG     │
│ ETH     $3,521   -0.34%  $18B   $8.1B    -0.005%   0.89x  61%↓    SHORT    │
│ SOL     $178.2   +3.21%  $4.2B  $2.4B    +0.018%   1.21x  78%↑    LONG     │
│ [sparkline 24h tiny chart per row]                                             │
└────────────────────────────────────────────────────────────────────────────────┘
```

---

### 8.5 AI Hub (`/ai`)

**Dedicated AI intelligence dashboard**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ AI SYSTEM STATUS BAR                                                    │
│ [CUDA Active ✅] [Training: Step 847/1000] [Model v3.2.1] [GPU: 67%]  │
├──────────────────────────────────┬──────────────────────────────────────┤
│ MULTI-SYMBOL PREDICTION MATRIX   │ MODEL PERFORMANCE                   │
│ (confidence heatmap)             │ Win Rate 7d: 61% ████████░░         │
│                                  │ Win Rate 30d: 58% ███████░░░         │
│ BTC  5m: 🟢73% ↑                │ Avg Confidence on wins: 74%          │
│ BTC  15m: 🟢68% ↑               │ Calibration chart                    │
│ BTC  1h: 🟡52% →                │ (Expected vs Actual win rate)        │
│ ETH  5m: 🔴41% ↓                │                                      │
│ ETH  15m: 🟢71% ↑              ├──────────────────────────────────────┤
│                                  │ TRAINING STATUS                     │
│                                  │ Loss: 0.0847 (improving)            │
│                                  │ ████████████████████░░░░░ 87%       │
│                                  │ ETA: ~45 minutes                    │
├──────────────────────────────────┴──────────────────────────────────────┤
│ CURRENT SIGNAL CHAIN (lineage trace)                                    │
│ [Features] → [Model Prediction] → [Orchestrator] → [Risk Gateway] → [Intent] │
│  200 inputs    73% LONG          Winner: BTC 5m    APPROVED             PAPER │
│  fresh 3s      bps: +12.4                         (gate: approved)             │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 8.6 Admin Portal (`/admin`)

**Separate visual context from trader portal — use different color accent**

```
┌─────────────────────────────────────────────────────────────────────────┐
│ ADMIN TOPBAR (different accent color — purple instead of teal)          │
│ [⚙ Admin Portal] [System] [Trainer] [Risk] [Orchestrator] [Users] [Logs]│
├─────────────────────────────────────────────────────────────────────────┤
│ SYSTEM HEALTH GRID                                                      │
│ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │
│ │ INGESTORS│ │ TRAINER  │ │ORCHESTRTR│ │   RISK   │ │EXECUTION │    │
│ │ 12/12 ✅ │ │ ACTIVE ✅│ │ RUNNING ✅│ │  OK   ✅ │ │ PAPER ✅ │    │
│ │ Fresh 2s │ │ Step 847 │ │ 5 winners│ │ Gate ok  │ │ 3 fills  │    │
│ └──────────┘ └──────────┘ └──────────┘ └──────────┘ └──────────┘    │
├─────────────────────────────────────────────────────────────────────────┤
│ LIVE READINESS CHECKLIST                                                │
│ ✅ Ingestors active      ✅ Model checkpoint validated                  │
│ ✅ Redis connection      ✅ Exchange API read-only confirmed             │
│ ✅ Feature pipeline      ⚠️  Live gate: pending operator approval        │
│ ✅ Risk gateway          ❌ Balance: insufficient for min order          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### 8.7 Login Page (Real Auth)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                                                                         │
│              [Platform Logo]                                            │
│              [NeuralEdge]                                               │
│                                                                         │
│    ┌─────────────────────────────────────────────────────────┐        │
│    │  Sign In to Trading Platform                            │        │
│    │                                                         │        │
│    │  Username or Email: [________________________]          │        │
│    │  Password:          [________________________] [👁]     │        │
│    │                                                         │        │
│    │  [  Sign In  ]   [Forgot Password]                     │        │
│    │                                                         │        │
│    │  ──────────────── OR ────────────────                  │        │
│    │                                                         │        │
│    │  [ Continue as Demo Viewer (read-only) ]               │        │
│    └─────────────────────────────────────────────────────────┘        │
│                                                                         │
│    Live System Status: 🟢 All systems operational                      │
│    Paper Mode: Active | BTC: $97,432 ▲                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 9. DESIGN SYSTEM SPECIFICATION

### 9.1 Color Tokens (New)
```css
:root {
  /* Backgrounds */
  --bg-base: #0a0e14;           /* darkest base */
  --bg-surface-1: #0f1318;      /* cards, panels */
  --bg-surface-2: #141a22;      /* elevated panels */
  --bg-surface-3: #1a2230;      /* hover states */
  --bg-overlay: rgba(15,19,24,0.97); /* modals, dropdowns */

  /* Text */
  --text-primary: #e4ebf5;      /* main text */
  --text-secondary: #8b9ab4;    /* labels, secondary */
  --text-tertiary: #556070;     /* dimmed text, units */
  --text-accent: #f8c93f;       /* amber accent (existing) */

  /* Trading Colors */
  --color-buy: #00d4a3;         /* green-teal (Binance-style, not pure green) */
  --color-sell: #ef4444;        /* red */
  --color-buy-bg: rgba(0,212,163,0.08);
  --color-sell-bg: rgba(239,68,68,0.08);

  /* AI / Prediction Colors */
  --color-ai: #6c63ff;          /* purple — AI brand color */
  --color-ai-bg: rgba(108,99,255,0.08);
  --color-confidence-high: #00d4a3;
  --color-confidence-mid: #f59e0b;
  --color-confidence-low: #ef4444;

  /* Status Colors */
  --color-ok: #10b981;          /* system OK */
  --color-warn: #f59e0b;        /* warning */
  --color-error: #ef4444;       /* error */
  --color-info: #3b82f6;        /* info */
  --color-paper: #6c63ff;       /* paper/simulation mode */

  /* Borders */
  --border-subtle: rgba(255,255,255,0.06);
  --border-default: rgba(255,255,255,0.10);
  --border-strong: rgba(255,255,255,0.18);
  --border-buy: rgba(0,212,163,0.3);
  --border-sell: rgba(239,68,68,0.3);

  /* Chart */
  --chart-bg: #0c1018;
  --chart-grid: rgba(255,255,255,0.04);
  --chart-candle-up: #00d4a3;
  --chart-candle-down: #ef4444;
  --chart-volume-up: rgba(0,212,163,0.3);
  --chart-volume-down: rgba(239,68,68,0.3);

  /* Gradients */
  --gradient-buy: linear-gradient(135deg, rgba(0,212,163,0.12), transparent);
  --gradient-sell: linear-gradient(135deg, rgba(239,68,68,0.12), transparent);
  --gradient-ai: linear-gradient(135deg, rgba(108,99,255,0.12), transparent);
  --gradient-header: linear-gradient(180deg, #0f1318 0%, #0a0e14 100%);

  /* Spacing scale */
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
  --space-8: 32px;

  /* Border radius */
  --radius-sm: 4px;
  --radius-md: 8px;
  --radius-lg: 12px;
  --radius-xl: 16px;

  /* Typography scale */
  --text-xs: 10px;
  --text-sm: 12px;
  --text-base: 14px;
  --text-lg: 16px;
  --text-xl: 20px;
  --text-2xl: 24px;
  --text-3xl: 32px;
  --text-4xl: 48px;

  /* Transitions */
  --transition-fast: 80ms ease;
  --transition-base: 150ms ease;
  --transition-slow: 300ms ease;

  /* Z-index scale */
  --z-base: 0;
  --z-dropdown: 100;
  --z-sticky: 200;
  --z-modal: 300;
  --z-toast: 400;
  --z-critical: 500;
}
```

### 9.2 Typography (Revised)
```
Display (page titles, KPI numbers): Inter or Outfit, 700 weight
Body: Inter or IBM Plex Sans, 400/500 weight
Monospace (prices, addresses, codes): JetBrains Mono or IBM Plex Mono
Labels: Inter, 600 weight, letter-spacing: 0.5px, text-transform: uppercase
```

- Replace IBM Plex with **Inter** for body (wider supported, better on screens, used by Binance)
- Keep **IBM Plex Mono** for numeric data (excellent for numbers)
- Establish typographic scale from `--text-xs` to `--text-4xl`

### 9.3 Component Specifications

#### TopBar Component (replaces AdminShell header)
```
Height: 64px
Background: --bg-surface-1 with 1px bottom border
Left: Logo (SVG, 32x32) + Platform Name (text-xl, font-weight: 700)
Center: Symbol Search (autocomplete dropdown, shows live prices)
Right: [Price Ticker Pills] [🔔 Notifications] [Avatar + Dropdown]

Price Ticker Pills (right of search, before notifications):
- 3-5 most-watched symbols
- Format: "BTC $97,432 +1.24% ▲"
- Live-updating, green/red color for direction
```

#### SecondaryNav Component (replaces both top nav and left sidebar)
```
Height: 40px
Background: --bg-surface-1 with 1px bottom border
Items: Dashboard | Trade | Markets | Signals | AI | Derivatives | Portfolio | Backtests | Research | Alerts
Active: underline with --color-buy accent, text-primary
Inactive: text-secondary
Right: [System: 🟢] [Paper Mode chip] -- condensed status
```

#### TickerBanner Component (replaces static ticker strip)
```
Height: 32px
Background: --bg-base
Content: Horizontally auto-scrolling strip of ALL active symbols
Format per item: "BTCUSDT $97,432 ▲ +1.24%"
Animation: CSS scroll animation, pauses on hover
Color: green for positive change, red for negative
Update: every 5 seconds (new data from polling or WebSocket)
```

#### KPICard Component
```
Width: flexible (min 140px)
Height: 80px
Background: --bg-surface-1
Border: 1px solid --border-subtle, radius: --radius-md
Content:
  - Label: --text-xs, --text-tertiary, UPPERCASE, letter-spacing: 0.5px
  - Value: --text-2xl, 700 weight, color based on value polarity
  - Delta: --text-sm, colored (+1.24% in green, -0.34% in red)
  - Live dot: 6px circle pulsing if receiving live updates
States: idle, loading (skeleton), error, live (pulsing dot)
```

#### DataPanel Component (replaces cockpit-panel)
```
Background: --bg-surface-1
Border: 1px solid --border-subtle
Border-radius: --radius-lg
Header: 
  - Title: --text-base, font-weight: 600
  - Right slot: chips, status indicators
  - Divider: 1px border
Body: padding 16px
Variants: default | outlined | glass | highlight-buy | highlight-sell | highlight-ai
```

#### SignalCard Component (new — key differentiator)
```
Width: full (or 300px in sidebar)
Background: 
  - LONG: gradient from rgba(0,212,163,0.10) + --bg-surface-1
  - SHORT: gradient from rgba(239,68,68,0.10) + --bg-surface-1
  - NEUTRAL: --bg-surface-1
Border-left: 3px solid --color-buy/--color-sell/--border-subtle
Content:
  - Direction badge: "LONG ▲" or "SHORT ▼" (large, 24px, colored)
  - Symbol + timeframe: "BTCUSDT · 5m"
  - Confidence meter: animated fill bar (0-100%)
  - Expected move: "+12.4 bps" (teal) or "-8.2 bps" (red)
  - Status: "PAPER MODE" or "LIVE APPROVED" chip
  - Age: "Updated 3s ago"
```

#### OrderBook Component (new — critical for Trade page)
```
Layout: Two columns (Asks on top in red, Bids on bottom in green)
Per row: Price | Quantity | Cumulative bar (background color fill proportional to size)
Update: Real-time (animate rows that change)
Spread row: centered, shows spread amount and %
Depth chart: small visualization below the book
```

#### ConfidenceGauge Component (new)
```
Type: Animated circular arc gauge (not a plain bar)
Range: 0-100%
Colors:
  - 0-40%: red (low confidence)
  - 40-65%: amber (below threshold)
  - 65-100%: teal/green (above threshold)
  - 65% threshold line: dashed white line
Center text: "73%" in --text-3xl
Beneath: "73% confidence · ABOVE GATE"
Animation: smooth fill on update
```

#### StatusTile Component (for System Health grid)
```
Width: flexible (min 160px)
Height: 100px
Background: 
  - OK: --bg-surface-1 with subtle green left border
  - WARN: --bg-surface-1 with amber left border
  - ERROR: --bg-surface-1 with red left border
Icon: 24px status icon (worker-specific)
Title: service name
Status text: "ACTIVE" | "DEGRADED" | "OFFLINE"
Detail: last heartbeat age or error message
```

---

## 10. COMPONENT REDESIGN SPECIFICATIONS

### 10.1 AdminShell → PlatformShell (Rename + Redesign)

**Remove:**
- eyebrow text "Crypto intelligence and execution"
- H1 "AI BOT V2 Trading Desk"
- Dense command rail with 10 text chips
- Symbol search label element in header (move to TopBar)

**Add:**
- Platform logo (SVG) + brand name
- Symbol search with live dropdown (Binance-style)
- TopBar right: notification bell, user avatar, dropdown
- Replace the `admin-command-rail` with the 3 most critical status chips only (mode, live gate, system)

### 10.2 Nav → SecondaryNav (Redesign)

**Remove:**
- Left sidebar entirely
- `<details>` group pattern
- All system/developer pages from primary navigation
- Page count in nav (50+ items currently visible to admin)

**Add:**
- Horizontal secondary nav bar (40px)
- 10-12 primary navigation items max for trader
- Keyboard shortcut hints (optional)
- Active page underline indicator (animated)
- System status summary condensed on right side of nav

### 10.3 Ticker Strip → TickerBanner (Redesign)

**Remove:**
- Static 5-column fixed grid
- Monospace font for ticker (use Inter)
- Non-scrolling behavior

**Add:**
- Horizontally auto-scrolling continuous ticker (CSS animation: `scroll`)
- All 25 active symbols
- Color: green for positive 24h, red for negative 24h
- Format: `BTC $97,432 +1.24% ▲`
- Pause on hover

### 10.4 Panel/Metric → DataPanel/KPICard (Redesign)

**Current `Metric` component:**
```tsx
<div className="cockpit-metric">  // 74px box
  <span>{label}</span>            // small label
  <strong>{value}</strong>        // large value
  {detail && <small>{detail}</small>}
</div>
```

**New `KPICard` specification:**
- Animated number change (count-up on data update)
- Color context (positive = teal, negative = red, warning = amber)
- Live indicator dot
- Loading skeleton
- Delta indicator

### 10.5 Charts (Redesign)

The `V2ProfessionalMarketChart` (lightweight-charts) is functional. Redesign requirements:

- Apply new chart colors: `--chart-candle-up`, `--chart-candle-down`
- Increase chart height to `min-height: 500px` for the Trade page
- Add signal overlay markers (entry/exit/target price lines)
- Add funding rate as a sub-panel below main chart
- Add volume histogram with colored bars
- Implement timeframe selector tabs that don't reload the chart
- Add zoom controls and crosshair data tooltip
- Add "AI overlay" toggle (shows/hides prediction markers)

### 10.6 Login Page (Full Redesign)

**Current:**
- 4 role-selector buttons
- No authentication

**New:**
- Email + password form
- JWT authentication against backend
- "Demo Mode" button (allows read-only access without login)
- Show live system status on the login page (paper equity, BTC price)
- Password visibility toggle
- "Remember me" checkbox
- Forgot password link (placeholder)
- Admin can create trader accounts from the admin portal

---

## 11. AUTHENTICATION REDESIGN

### 11.1 Backend Changes Required

```python
# New endpoints needed in FastAPI:
POST /api/auth/login          # username + password → JWT
POST /api/auth/logout         # invalidate session
GET  /api/auth/me             # get current user from JWT
POST /api/auth/refresh        # refresh expired token
GET  /api/admin/users         # list users (admin only)
POST /api/admin/users         # create user (admin only)
PUT  /api/admin/users/{id}    # update user role (admin only)
DELETE /api/admin/users/{id}  # delete user (admin only)
```

### 11.2 Frontend Changes Required

```typescript
// New auth store (replace sessionStore):
interface AuthStore {
  user: {
    id: string;
    username: string;
    email: string;
    role: 'trader' | 'admin' | 'superadmin';
    created_at: string;
  } | null;
  token: string | null;   // JWT
  isAuthenticated: boolean;
  login(credentials: LoginCredentials): Promise<void>;
  logout(): Promise<void>;
  refreshToken(): Promise<void>;
}
```

### 11.3 RBAC Enforcement

- JWT must be sent in `Authorization: Bearer <token>` header for all API calls
- Backend validates JWT on every protected endpoint
- Frontend redirects to `/login` if 401 response received
- Role hierarchy: `trader (1) < admin (2) < superadmin (3)`
- Live trading approval requires `superadmin` or explicit `live_approver` flag

---

## 12. REAL-TIME DATA ARCHITECTURE

### 12.1 WebSocket Integration (New)

```
Backend WebSocket endpoint:  ws://host/ws/market-data

Messages:
- { type: 'price', symbol: 'BTCUSDT', price: 97432.5, change_24h: 1.24 }
- { type: 'signal', direction: 'LONG', confidence: 0.73, symbol: 'BTCUSDT' }
- { type: 'position_update', position_id: '...', unrealized_pnl: 127.4 }
- { type: 'system_event', severity: 'warn', message: '...' }
- { type: 'alert', alert_id: '...', type: 'price_target_hit', symbol: 'BTC' }

Frontend WebSocket hook (new):
useWebSocket({
  endpoint: '/ws/market-data',
  onMessage: (msg) => dispatch(msg),
  reconnectDelay: 2000,
  maxRetries: 10,
})
```

### 12.2 Reduce Polling Burden

Current state: Every page makes 5–15 polling requests every 2–30 seconds.

**Consolidate into:**
- 1 WebSocket connection for all real-time data
- 1 shared `useGlobalMarketState()` hook at the app level
- Individual pages subscribe to slices of this state
- Background polling only for non-time-critical data (system health at 30s intervals)

### 12.3 Notification System

```typescript
interface Notification {
  id: string;
  type: 'signal' | 'alert' | 'system' | 'trade' | 'risk';
  severity: 'info' | 'success' | 'warning' | 'error';
  title: string;
  message: string;
  timestamp: string;
  read: boolean;
  action?: { label: string; route: string };
}
```

- Toast notifications for real-time events (signal fired, risk gate changed)
- Notification bell with unread count in TopBar
- Notification center page/drawer
- Browser push notifications (optional, behind permission request)

---

## 13. IMPLEMENTATION ROADMAP

### Phase 1: Foundation & Auth (Week 1-2)
**Priority: Critical before any visual work**

1. Implement real JWT authentication
   - Backend: `POST /api/auth/login`, `GET /api/auth/me`, `POST /api/auth/logout`
   - Backend: User table in SQLite/PostgreSQL (id, username, password_hash, role)
   - Frontend: Replace `sessionStore` with JWT-based `authStore`
   - Frontend: New Login page with real form
   - Frontend: Auth guard on all protected routes (validate JWT)

2. Design system CSS tokens
   - Create `/v2/frontend/src/styles/tokens.css` with all new CSS custom properties
   - Migrate existing `styles.css` hardcoded values to use tokens
   - Add new tokens for buy/sell/AI colors

3. Install Inter font (or keep IBM Plex — add Inter as option)

**Files changed:** `auth/session.ts`, `auth/rbac.ts`, `styles.css`, new `styles/tokens.css`, `pages/login/index.tsx`, backend `app/api/v2/` (new auth router)

---

### Phase 2: Shell & Navigation (Week 2-3)
**Priority: High — affects every page**

1. Redesign `AdminShell.tsx` → `PlatformShell.tsx`
   - Remove eyebrow + H1 text
   - Add platform logo (create SVG)
   - Replace command rail with 3-chip status bar
   - Add notification bell + user avatar dropdown

2. Redesign `Nav.tsx` → `SecondaryNav.tsx`
   - Remove left sidebar
   - Add horizontal secondary nav bar
   - Reduce to 10 primary items for traders
   - Separate admin portal nav

3. Redesign ticker strip → `TickerBanner.tsx`
   - Auto-scrolling CSS animation
   - All active symbols
   - Color by direction

4. Update `router.tsx` to handle admin portal at `/admin/*`

**Files changed:** `AdminShell.tsx`, `Nav.tsx`, `router.tsx`, `styles.css`

---

### Phase 3: Trade Page (Week 3-4)
**Priority: High — flagship page**

1. Full redesign of `/trade` page
   - Split layout: Chart 60% | Order Book 20% | Order Panel 20%
   - Integrate professional chart (reskin V2ProfessionalMarketChart)
   - Add order book component (reads from payload, WebSocket-ready)
   - Add recent trades tape component
   - Add paper buy/sell form (no live execution — paper only)
   - Add positions strip at the bottom
   - Symbol header bar with 24h stats

2. Create `OrderBook.tsx` component
3. Create `RecentTradesTape.tsx` component
4. Create `PaperOrderForm.tsx` component (paper mode only, disabled for live)
5. Create `SymbolHeader.tsx` component

**Files changed:** `pages/trader/index.tsx`, new components in `components/trading/`

---

### Phase 4: Dashboard & Markets (Week 4-5)

1. Dashboard redesign
   - KPI strip (6 cards)
   - Split layout: chart + side panels
   - System status tiles at bottom
   - Remove overwhelming panel count (max 6 panels on dashboard)

2. Markets screener redesign
   - Add 24h%, Volume, OI columns
   - Add symbol search/filter
   - Add sparkline charts per row
   - Add tab navigation (Overview/Signals/Derivatives/Funding)

3. Create `KPICard.tsx` component
4. Create `SymbolScreenerRow.tsx` component
5. Create `GlobalStatsBar.tsx` component

---

### Phase 5: AI Hub & Signal Pages (Week 5-6)

1. AI Hub redesign (`/ai` — new consolidated page)
   - Prediction matrix (heatmap visualization)
   - Confidence gauge (circular arc)
   - Training progress with loss chart
   - Signal chain lineage diagram

2. Signals page redesign
   - Direction banner → compact signal card
   - Signal history timeline
   - Win/loss statistics bar chart

3. Create `ConfidenceGauge.tsx` component
4. Create `SignalChain.tsx` component (lineage visualization)
5. Create `TrainingProgress.tsx` component

---

### Phase 6: Portfolio & History (Week 6-7)

1. Portfolio redesign
   - Equity curve chart (30-day default)
   - Position cards with P&L coloring
   - Risk dashboard with visual gauges

2. Executions redesign
   - Timeline view of executions
   - Fill price vs signal price comparison

3. History page
   - Trade journal with filters
   - Statistics panel (win rate, expectancy, avg PnL)

---

### Phase 7: Admin Portal (Week 7-8)

1. Create separate admin portal shell (`AdminPortalShell.tsx`)
   - Different color accent (purple)
   - Admin-specific navigation
   - Quick-access to critical controls

2. System Health grid redesign
   - Traffic-light tiles for all workers
   - Ingestor health matrix
   - Real-time heartbeat indicators

3. Live Readiness checklist redesign
   - Visual checklist with progress bar
   - One-click approval workflow for live trading

4. Trainer admin redesign
   - Training curves (loss over time chart)
   - Model version history
   - Training status with GPU metrics

---

### Phase 8: Alerts & Notifications (Week 8-9)

1. Real alerts page
   - Alert creation form (price level, OI change, funding threshold)
   - Alert history
   - Alert management (enable/disable/delete)

2. Notification system
   - Toast notifications (`react-hot-toast` or custom)
   - Notification center drawer
   - Real-time delivery via WebSocket

3. Browser push notifications setup (optional)

---

### Phase 9: Real-Time Upgrade (Week 9-10)

1. Backend WebSocket endpoint
2. Frontend WebSocket hook (`useWebSocket.ts`)
3. Global market state store
4. Replace per-component polling with shared subscription
5. Animate data updates

---

### Phase 10: Polish & Mobile (Week 10-12)

1. Responsive breakpoints
   - Tablet: 768px+ — collapse Order Book panel, single-column dashboard
   - Mobile: 375px+ — simplified mobile view (signal card, price, PnL only)
   - Hamburger menu for mobile nav

2. Performance optimization
   - Lazy-load pages with `React.lazy`
   - Virtualized lists for markets screener
   - Debounce search input

3. Accessibility
   - ARIA labels (partially done, needs completion)
   - Keyboard navigation
   - Color contrast compliance (WCAG AA for text)

4. Testing
   - Update Playwright e2e tests for new routes
   - Add component tests for new UI components

---

## 14. DEVELOPER CHECKLIST

### Must-Do Before Launch (Non-Negotiable)

- [ ] Real authentication system (JWT, not `sessionStorage` role string)
- [ ] Multi-trader account support (each trader sees their own paper account)
- [ ] Remove or heavily restrict admin-only pages from trader nav
- [ ] Replace raw technical strings shown to users (LIVE_ARMED_BALANCE_HOLD → "Balance Hold")
- [ ] Professional platform name and logo (not "AI BOT V2")
- [ ] Paper mode clearly labeled everywhere (no confusion with real money)
- [ ] Trade page has a functional layout (chart + book + tape + form)
- [ ] Alerts page must have actual functionality (not just a coverage table)

### Should-Do for Professional Quality

- [ ] Scrolling ticker strip with live prices
- [ ] Horizontal secondary nav (remove 260px sidebar)
- [ ] New CSS design tokens (buy/sell/AI colors)
- [ ] KPICard component with animations
- [ ] ConfidenceGauge circular arc component
- [ ] Markets screener with 24h change and volume columns
- [ ] Equity curve chart on portfolio page
- [ ] AI Hub page consolidating all AI features
- [ ] Admin portal with purple accent (visually separate from trader portal)
- [ ] System health as traffic-light tiles grid
- [ ] Live readiness as visual checklist
- [ ] Notification bell + toast system

### Nice-to-Have

- [ ] WebSocket real-time data (replace polling)
- [ ] Symbol search with live price dropdown
- [ ] Watchlist / favorites system
- [ ] Market heatmap visualization
- [ ] Funding rate color-coded heatmap
- [ ] Liquidation cluster map visualization
- [ ] Interactive replay timeline scrubber
- [ ] Mobile responsive layouts
- [ ] Browser push notifications
- [ ] Dark/light toggle (dark as default, light optional)
- [ ] Portfolio comparison (paper vs. signal performance)
- [ ] TradingView embedded charts (if API key available)

---

### Reference Files for Developer

| What to Look At | File | Why |
|---|---|---|
| Current shell layout | `v2/frontend/src/components/layout/AdminShell.tsx` | Redesign starting point |
| Current nav | `v2/frontend/src/components/layout/Nav.tsx` | Replace with secondary nav |
| Current chart | `v2/frontend/src/components/charts/V2ProfessionalMarketChart.tsx` | Reskin, keep functionality |
| Current trade page | `v2/frontend/src/pages/trader/index.tsx` | Full redesign target |
| Current signals | `v2/frontend/src/pages/signals/index.tsx` | Simplify + add history |
| Current CSS | `v2/frontend/src/styles.css` | Add tokens, consolidate |
| Current router | `v2/frontend/src/router.tsx` | Add admin portal routes |
| Current RBAC | `v2/frontend/src/auth/rbac.ts` | Replace with JWT roles |
| Backend API router | `v2/backend/app/api/v2/` | Add auth endpoints |
| Page registry | `v2/frontend/src/pages/registry.ts` | Add new admin portal pages |
| Navigation config | `v2/frontend/src/pages/productNavigation.ts` | Redesign nav categories |

---

*This audit document is read-only. No code was modified. All findings are based on direct inspection of source files. Redesign recommendations are proposals for developer implementation.*

**Files Inspected (no changes made):**
- `v2/frontend/src/App.tsx`
- `v2/frontend/src/router.tsx`
- `v2/frontend/src/styles.css`
- `v2/frontend/src/pages/registry.ts`
- `v2/frontend/src/pages/productNavigation.ts`
- `v2/frontend/src/components/layout/AdminShell.tsx`
- `v2/frontend/src/components/layout/Nav.tsx`
- `v2/frontend/src/components/layout/PublicShell.tsx`
- `v2/frontend/src/components/charts/V2ProfessionalMarketChart.tsx`
- `v2/frontend/src/components/trading/TradingPrimitives.tsx`
- `v2/frontend/src/auth/rbac.ts`
- `v2/frontend/src/pages/mission-control/index.tsx`
- `v2/frontend/src/pages/trader/index.tsx`
- `v2/frontend/src/pages/markets/index.tsx`
- `v2/frontend/src/pages/market/index.tsx`
- `v2/frontend/src/pages/signals/index.tsx`
- `v2/frontend/src/pages/positions/index.tsx`
- `v2/frontend/src/pages/executions/index.tsx`
- `v2/frontend/src/pages/history/index.tsx`
- `v2/frontend/src/pages/ai-brain/index.tsx`
- `v2/frontend/src/pages/risk-control/index.tsx`
- `v2/frontend/src/pages/orchestrator-admin/index.tsx`
- `v2/frontend/src/pages/trainer-admin/index.tsx`
- `v2/frontend/src/pages/strategy-backtesting/index.tsx`
- `v2/frontend/src/pages/alerts/index.tsx`
- `v2/frontend/src/pages/system-health/index.tsx`
- `v2/frontend/src/pages/admin-war-room/index.tsx`
- `v2/frontend/src/pages/public-landing-v2/index.tsx`
- `v2/frontend/src/pages/login/index.tsx`
- `v2/frontend/src/pages/cockpitComponents.tsx`
- `v2/frontend/src/pages/market-intelligence/index.tsx`
- `v2/frontend/index.html`
- `v2/frontend/package.json`
- `v2/backend/app/api/v2/trainer.py`
- `v2/backend/app/api/v2/pipeline.py`

---

---

# SECTION 15: DEEP CRAWL VERIFICATION UPDATE
**Added:** June 12, 2026 — Claude Code audit against raw source

## 15.1 Verified Facts (Confirmed by Source Crawl)

### Authentication State — STILL FAKE
```
Source: v2/backend/app/api/v1/auth.py, line 28:
  milestone_d_status: "skeleton"
  
Source: v2/frontend/src/pages/login/index.tsx, lines 39-47:
  <button onClick={() => sessionStore.setRole(nextRole)}>
  
Source: v2/frontend/src/components/layout/AdminShell.tsx, line 94:
  const role = new URLSearchParams(search).get('role') as Role
  → Anyone navigating to /dashboard?role=admin gets admin role.
```

**Confirmed:** Zero real security. The entire RBAC system enforces nothing.

### Data Flow — ALL POLLING, NO WEBSOCKET
```
Source: v2/frontend/src/pages/mission-control/index.tsx, lines 717-743:
  27 simultaneous usePayloadFile hooks on one page
  Intervals: 8,000ms to 30,000ms

Source: v2/frontend/src/pages/trader/index.tsx, lines 224-259:
  8 polling hooks, some at 2,000ms interval

Grep result: zero WebSocket usage in frontend src/
  (confirmed: no useWebSocket, no new WebSocket(), no ws:// in frontend code)
```

**Confirmed:** The backend has a WS connection to CoinAPI for data ingestion, but NOTHING is pushed to the frontend. All frontend data comes from static JSON files in `/public/operator_runtime/`.

### Backend API Surface — MIXED (many stubs)
```
Active routers (real handlers): health, ingestors, derivatives, live_gate (870 lines),
  decisions, risk_decisions, governance, live_readiness, live_mode, replay, exchanges,
  selection, universe, discovery, fleet, operator_runtime, mission_control, monitor,
  paper_fill_gate, intents, ollama_assistant, claude_admin, codex_review

Stub routers (scaffold only, no handlers): auth, accounts, predictions, features,
  risk, paper, signals

Source: api/v1/signals.py line 25: only OPTIONS metadata, no GET/POST handlers
Source: api/v1/predictions.py line 25: only OPTIONS metadata
Source: api/v1/auth.py line 28: "milestone_d_status: skeleton"
```

**Confirmed:** Many critical APIs are scaffolded but empty.

### Verified File Counts
- **83 TSX page components** in `/v2/frontend/src/`
- **2,083 JSON payload files** in `/v2/frontend/public/operator_runtime/`  
- **6,922 lines** in `styles.css`
- **270 total source files** in frontend src
- **30+ CLI worker processes** confirmed in `/v2/backend/app/cli/`

### DB Repositories — Exist, Not Used by Frontend
```
Source: v2/backend/app/adapters/db/repositories/
  accounts.py, audit_events.py, decisions.py, execution_intents.py,
  feature_snapshots.py, governance_approvals.py, predictions.py,
  risk_decisions.py, sessions.py, signals.py, symbol_overrides.py,
  universe_versions.py
```

The database schema and repository layer exists and is complete. The frontend bypasses it entirely — it reads static JSON files. This means the data integrity story is broken: DB and JSON files may diverge.

---

## 15.2 New Findings (Not in Original Audit)

### Finding 1: live_gate.py is the most complete API (870 lines)
The live gate has a full multi-step approval workflow already implemented:
- `GET /status` — current gate state
- `POST /evaluate` — run pre-flight checks
- `POST /arm` — arm the gate
- `POST /accept-risk-profile` — operator accepts risk profile
- `POST /accept-live-symbols` — operator accepts symbol list
- `POST /final-approval` — final operator authorization
- Plus complete failover workflow (6 more endpoints)

**This is the most important admin control flow and should be the centerpiece of the Admin Live Readiness page**, displayed as a step-by-step visual wizard.

### Finding 2: Middleware layer is more complete than documented
```
Source: v2/backend/app/api/middleware/
  rbac.py — server-side role enforcement
  rate_limit.py — rate limiting
  ip_allowlist.py — IP filtering
  step_up_mfa.py — MFA step-up for dangerous operations
  lineage_validator.py — lineage tracking
  idempotency.py — idempotent mutations
  live_block_guard.py — live trading block
```

The infrastructure for real security is in place but not wired to real auth tokens because auth is still a stub. Once JWT auth is implemented, the middleware simply needs to read the JWT instead of the session store.

### Finding 3: ingestors API is fully operational
```
Source: api/v1/ingestors.py:
  GET  /api/v1/ingestors/           — lists all ingestors with status
  GET  /api/v1/ingestors/{id}       — single ingestor details
  POST /api/v1/ingestors/{id}/control — control ingestor
```
This means the Ingestors admin page could and should be wired to the real API, not static JSON.

### Finding 4: derivatives API has 6 real endpoints
```
Source: api/v1/derivatives.py:
  /exchanges, /funding, /open-interest, /long-short, /basis, /liquidations
  All have real implementations.
```
The Derivatives pages should use these API endpoints (polled or WebSocket) rather than static JSON.

### Finding 5: Signal chain data is rich but poorly surfaced
The signal lineage system writes detailed JSON including:
- Execution intent (symbol, side, action)
- Signal details (direction, symbol, timeframe)  
- Risk decision (approved/denied with reason)
- Feature snapshot reference
- Trainer confidence record

This data is the platform's unique value proposition. The UI shows it as raw JSON fields rather than as a visual signal chain diagram.

### Finding 6: Admin War Room page is developer-internal only
```
Source: v2/frontend/src/pages/admin-war-room/index.tsx
  Shows: war room cycles, gap matrix, raw blocker matrix, codex queue, 
  observation builder, legacy log intelligence, payload explorer
```
This page has no place in any user-facing navigation. It is an internal sprint management tool that was accidentally included in the operator nav. It should be hidden from all roles except superadmin during active development only.

---

## 15.3 What the Platform Already Does Well

Despite the audit findings above, the system has genuine strengths:

1. **Real-time ML pipeline** — The CUDA trainer, orchestrator, risk gateway, and paper execution are genuinely running and producing real data. This is not mock data.

2. **Rich signal lineage** — Every signal can be traced from features → model → orchestrator → risk → execution intent. This traceability is a real differentiator.

3. **Evidence integrity** — The audit trail with SHA256 hashes is real and functional.

4. **Data depth** — 30+ data feeds covering derivatives, liquidations, funding, OI, long/short ratios, multi-exchange data. More comprehensive than most retail platforms.

5. **Risk safety** — The live trading block is structural, not just a UI checkbox. Multiple layers of guards.

6. **AI predictions** — Multi-symbol, multi-timeframe predictions with calibrated confidence. Not just a simple indicator.

The redesign job is to surface these capabilities in a professional, intuitive interface — not to rebuild the backend.

---

# SECTION 16: PROFESSIONAL REDESIGN — DEVELOPER INSTRUCTIONS

## 16.1 Platform Identity Decision

**The developer must choose a platform name before starting UI work.**

Recommendations:
- **NeuraTrader** — communicates AI + trading
- **AlphaForge** — "forging alpha signals"
- **EdgeAI** — "AI-powered trading edge"
- **PulseTrader** — "pulse of the market"

The name replaces "AI BOT V2 Trading Desk" everywhere. Create a simple SVG logo (a stylized N, A, or lightning bolt in teal). Store as `/v2/frontend/src/assets/logo.svg`.

---

## 16.2 New CSS Design System

**STEP 1: Create `/v2/frontend/src/styles/tokens.css`**

```css
/* === tokens.css — trading platform design tokens === */
/* Import this BEFORE styles.css in main.tsx */

:root {
  /* Backgrounds */
  --bg-base:     #080c10;
  --bg-panel:    #0d1117;
  --bg-elevated: #131920;
  --bg-hover:    #192030;
  --bg-overlay:  rgba(8,12,16,0.96);

  /* Text */
  --text-primary:   #e4ebf5;
  --text-secondary: #7d8fa8;
  --text-muted:     #4a5568;

  /* Trading — buy = teal-green (Binance style), sell = red */
  --buy:          #00d4a3;
  --sell:         #f6465d;
  --buy-bg:       rgba(0,212,163,0.08);
  --sell-bg:      rgba(246,70,93,0.08);
  --buy-border:   rgba(0,212,163,0.25);
  --sell-border:  rgba(246,70,93,0.25);

  /* AI / Predictions */
  --ai:           #6c63ff;
  --ai-bg:        rgba(108,99,255,0.08);
  --ai-border:    rgba(108,99,255,0.25);
  --conf-high:    #00d4a3;
  --conf-mid:     #f59e0b;
  --conf-low:     #f6465d;

  /* Status */
  --ok:           #10b981;
  --warn:         #f59e0b;
  --error:        #f6465d;
  --info:         #3b82f6;
  --live:         #f0b90b;
  --paper:        #6c63ff;

  /* Admin accent (purple — different from trader portal) */
  --admin-accent: #7c3aed;
  --admin-bg:     rgba(124,58,237,0.08);

  /* Borders */
  --border:       rgba(255,255,255,0.06);
  --border-soft:  rgba(255,255,255,0.10);
  --border-focus: rgba(255,255,255,0.20);

  /* Chart */
  --chart-bg:      #0a0e14;
  --chart-grid:    rgba(255,255,255,0.04);
  --candle-up:     #00d4a3;
  --candle-down:   #f6465d;
  --vol-up:        rgba(0,212,163,0.25);
  --vol-down:      rgba(246,70,93,0.25);

  /* Spacing */
  --s-1:4px; --s-2:8px; --s-3:12px; --s-4:16px;
  --s-5:20px; --s-6:24px; --s-8:32px; --s-12:48px;

  /* Radius */
  --r-sm:4px; --r-md:8px; --r-lg:12px; --r-xl:16px; --r-full:9999px;

  /* Type scale */
  --tx-xs:10px; --tx-sm:12px; --tx-base:14px;
  --tx-lg:16px; --tx-xl:20px; --tx-2xl:24px;
  --tx-3xl:32px; --tx-4xl:48px;

  /* Transitions */
  --t-fast:80ms ease; --t-base:150ms ease; --t-slow:300ms ease;

  /* Z-index */
  --z-base:0; --z-drop:100; --z-sticky:200; --z-modal:300; --z-toast:400; --z-top:500;

  /* Shadows */
  --shadow-sm: 0 1px 3px rgba(0,0,0,0.4);
  --shadow-md: 0 4px 12px rgba(0,0,0,0.5);
  --glow-buy:  0 0 12px rgba(0,212,163,0.25);
  --glow-sell: 0 0 12px rgba(246,70,93,0.25);
  --glow-ai:   0 0 12px rgba(108,99,255,0.25);
}
```

**STEP 2: Import in `main.tsx`:**
```tsx
import './styles/tokens.css';   // NEW — first
import './styles.css';          // existing — second
```

**STEP 3: Update `V2ProfessionalMarketChart.tsx`:**
Replace hardcoded chart colors with:
```typescript
upColor: 'var(--candle-up)',           // was '#26a69a' or similar
downColor: 'var(--candle-down)',       // was '#ef5350'
backgroundColor: 'var(--chart-bg)',
gridColor: 'var(--chart-grid)',
```

---

## 16.3 Shell Redesign — Step by Step

### Step 1: Create `/v2/frontend/src/assets/logo.svg`
```svg
<!-- Simple lightning bolt in teal — placeholder until designer creates real logo -->
<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
  <polygon points="18,3 8,18 15,18 14,29 24,14 17,14" 
           fill="#00d4a3" stroke="none"/>
</svg>
```

### Step 2: Create `TopBar.tsx`
```tsx
// components/layout/TopBar.tsx
export function TopBar() {
  return (
    <header className="topbar">
      <div className="topbar__brand">
        <img src="/assets/logo.svg" alt="Logo" width={28} height={28} />
        <span className="topbar__name">NeuraTrader</span>  {/* change to your name */}
      </div>
      <div className="topbar__search">
        <SymbolSearch />  {/* autocomplete from chartManifest payload */}
      </div>
      <div className="topbar__right">
        <PricePills />    {/* 2-3 symbols from chartManifest */}
        <NotificationBell count={unreadCount} />
        <UserMenu user={currentUser} onLogout={authStore.logout} />
      </div>
    </header>
  );
}
```

```css
/* In styles.css or tokens.css */
.topbar {
  height: 64px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 var(--s-4);
  gap: var(--s-4);
  position: sticky;
  top: 0;
  z-index: var(--z-sticky);
}
.topbar__brand {
  display: flex;
  align-items: center;
  gap: var(--s-2);
  min-width: 180px;
}
.topbar__name {
  font-size: var(--tx-lg);
  font-weight: 700;
  color: var(--text-primary);
  letter-spacing: -0.3px;
}
.topbar__search { flex: 1; max-width: 400px; }
.topbar__right {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  margin-left: auto;
}
```

### Step 3: Create `SecondaryNav.tsx`
```tsx
// components/layout/SecondaryNav.tsx
const TRADER_NAV = [
  ['/dashboard', 'Dashboard'],
  ['/trade', 'Trade'],
  ['/markets', 'Markets'],
  ['/signals', 'Signals'],
  ['/ai-predictions', 'AI'],
  ['/derivatives', 'Derivatives'],
  ['/portfolio', 'Portfolio'],
  ['/backtests', 'Backtests'],
  ['/research', 'Research'],
  ['/alerts', 'Alerts'],
] as const;

export function SecondaryNav() {
  const location = useLocation();
  return (
    <nav className="secondary-nav">
      <div className="secondary-nav__items">
        {TRADER_NAV.map(([href, label]) => (
          <Link
            key={href}
            to={href}
            className={location.pathname.startsWith(href) && (href !== '/dashboard' || location.pathname === '/dashboard')
              ? 'secondary-nav__link secondary-nav__link--active'
              : 'secondary-nav__link'}
          >
            {label}
          </Link>
        ))}
      </div>
      <div className="secondary-nav__status">
        <span className="chip chip--paper">PAPER</span>
        <span className="chip chip--warn">LIVE BLOCKED</span>
        <span className="chip chip--ok">⚡ 12/12</span>
      </div>
    </nav>
  );
}
```

```css
.secondary-nav {
  height: 40px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  padding: 0 var(--s-4);
  position: sticky;
  top: 64px;
  z-index: var(--z-sticky);
  gap: var(--s-1);
}
.secondary-nav__items { display: flex; align-items: center; gap: 0; flex: 1; }
.secondary-nav__link {
  padding: 0 var(--s-3);
  height: 40px;
  display: flex;
  align-items: center;
  font-size: var(--tx-sm);
  font-weight: 500;
  color: var(--text-secondary);
  text-decoration: none;
  border-bottom: 2px solid transparent;
  transition: color var(--t-fast), border-color var(--t-fast);
}
.secondary-nav__link:hover { color: var(--text-primary); }
.secondary-nav__link--active {
  color: var(--text-primary);
  border-bottom-color: var(--buy);
}
.secondary-nav__status { display: flex; align-items: center; gap: var(--s-2); }
```

### Step 4: Create `TickerBanner.tsx`
```tsx
// components/layout/TickerBanner.tsx
export function TickerBanner({ symbols }: { symbols: TickerSymbol[] }) {
  // symbols comes from chartManifest payload (already available in AdminShell)
  const items = [...symbols, ...symbols]; // duplicate for seamless loop
  return (
    <div className="ticker-banner" aria-hidden="true">
      <div className="ticker-banner__track">
        {items.map((s, i) => (
          <span key={i} className={`ticker-item ${s.change24h >= 0 ? 'ticker-item--up' : 'ticker-item--down'}`}>
            {s.symbol.replace('USDT','')}
            &nbsp;
            <strong>{formatPrice(s.price)}</strong>
            &nbsp;
            <small>{s.change24h >= 0 ? '+' : ''}{s.change24h.toFixed(2)}%</small>
          </span>
        ))}
      </div>
    </div>
  );
}
```

```css
.ticker-banner {
  height: 32px;
  background: var(--bg-base);
  border-bottom: 1px solid var(--border);
  overflow: hidden;
}
.ticker-banner__track {
  display: flex;
  align-items: center;
  height: 100%;
  gap: var(--s-6);
  padding: 0 var(--s-4);
  animation: ticker-scroll 60s linear infinite;
  white-space: nowrap;
}
.ticker-banner__track:hover { animation-play-state: paused; }
.ticker-item { font-size: var(--tx-xs); color: var(--text-secondary); }
.ticker-item--up strong { color: var(--buy); }
.ticker-item--down strong { color: var(--sell); }
@keyframes ticker-scroll {
  from { transform: translateX(0); }
  to   { transform: translateX(-50%); }
}
```

### Step 5: Update `AdminShell.tsx`
Replace the entire `<div className="admin-shell">` structure:

**Remove:**
- `<div className="trading-shell-title">` (eyebrow + H1)
- `<label className="symbol-search">` (readonly BTCUSDT)
- `<div className="admin-command-rail">` (9 chips)
- `<nav className="admin-shell__topnav">` (8 links)
- `<section className="admin-shell__ticker">` (10 static items)
- `<Nav />` component

**Add:**
```tsx
return (
  <div className="platform-shell">
    <LiveBlockBanner />
    <TopBar />
    <SecondaryNav />
    <TickerBanner symbols={tickerSymbols} />
    <main className="platform-shell__main" data-testid="admin-main">
      <Outlet />
    </main>
  </div>
);
```

```css
.platform-shell { display: flex; flex-direction: column; min-height: 100vh; }
.platform-shell__main { flex: 1; overflow-y: auto; }
/* Remove: admin-shell__body grid, admin-shell nav width, etc. */
```

---

## 16.4 Authentication — Minimal Viable Implementation

**Backend (implement first):**

```python
# api/v1/auth.py — replace stub with real implementation

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from passlib.context import CryptContext
from jose import JWTError, jwt
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
security = HTTPBearer(auto_error=False)

SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-this-in-production")
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

class LoginRequest(BaseModel):
    email: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: dict

@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.execute(select(User).where(User.email == body.email))
    user = user.scalar_one_or_none()
    if not user or not pwd_context.verify(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    access_token = jwt.encode(
        {"sub": str(user.id), "role": user.role, "exp": datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)},
        SECRET_KEY, algorithm=ALGORITHM
    )
    refresh_token = secrets.token_urlsafe(64)
    # Store refresh_token hash in sessions table
    await db.execute(insert(Session).values(user_id=user.id, token_hash=hash(refresh_token), expires_at=...))
    await db.commit()
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, user={"id": str(user.id), "role": user.role, "email": user.email})

@router.get("/me")
async def me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials:
        raise HTTPException(status_code=401)
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
    return {"id": payload["sub"], "role": payload["role"]}
```

**Frontend:**
```typescript
// auth/authStore.ts — replace session.ts
import { create } from 'zustand';
import { persist } from 'zustand/middleware';

interface User { id: string; email: string; role: string; }
interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  restoreSession: () => Promise<void>;
  demoMode: () => void;
}

export const useAuth = create<AuthState>()(persist(
  (set, get) => ({
    user: null,
    token: null,
    isAuthenticated: false,

    login: async (email, password) => {
      const res = await fetch('/api/v1/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email, password }),
      });
      if (!res.ok) throw new Error('Invalid credentials');
      const data = await res.json();
      set({ user: data.user, token: data.access_token, isAuthenticated: true });
      localStorage.setItem('refresh_token', data.refresh_token);
    },

    logout: async () => {
      const token = get().token;
      if (token) await fetch('/api/v1/auth/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
      set({ user: null, token: null, isAuthenticated: false });
      localStorage.removeItem('refresh_token');
    },

    demoMode: () => {
      set({ user: { id: 'demo', email: 'demo', role: 'viewer' }, token: null, isAuthenticated: true });
    },

    restoreSession: async () => {
      const token = get().token;
      if (!token) return;
      try {
        const res = await fetch('/api/v1/auth/me', {
          headers: { Authorization: `Bearer ${token}` },
        });
        if (res.ok) {
          const user = await res.json();
          set({ user, isAuthenticated: true });
        } else {
          set({ user: null, token: null, isAuthenticated: false });
        }
      } catch { set({ user: null, token: null, isAuthenticated: false }); }
    },
  }),
  { name: 'auth', partialize: (s) => ({ token: s.token }) }
));
```

---

## 16.5 Trade Page — Priority Layout Fix

**Minimum viable Trade page redesign (without full order book):**

```tsx
// pages/trader/index.tsx — new layout structure
return (
  <div className="trade-page">
    {/* Symbol header bar */}
    <div className="trade-symbol-bar">
      <SymbolSelector value={symbol} onChange={setSymbol} />
      <PriceDisplay price={currentPrice} change={change24h} />
      <AiSignalBadge direction={signal?.direction} confidence={signal?.confidence} />
      <RiskBadge status={riskStatus} />
      <span className="chip chip--paper">PAPER MODE</span>
    </div>

    {/* Main 3-column body */}
    <div className="trade-body">
      {/* Chart — 60% */}
      <div className="trade-chart">
        <TimeframeTabs value={tf} onChange={setTf} />
        <V2ProfessionalMarketChart symbol={symbol} timeframe={tf} height="calc(100vh - 340px)" />
      </div>

      {/* Order book — 20% */}
      <div className="trade-book">
        <MockOrderBook symbol={symbol} midPrice={currentPrice} spread={spread} />
      </div>

      {/* Order form — 20% */}
      <div className="trade-form">
        <PaperOrderForm symbol={symbol} currentPrice={currentPrice} />
      </div>
    </div>

    {/* Recent trades tape */}
    <div className="trade-tape">
      <span className="trade-tape__label">Recent Trades</span>
      {/* Scroll container with last 20 trades from payload */}
    </div>

    {/* Bottom tabs */}
    <div className="trade-bottom">
      <Tabs items={['Positions', 'History', 'AI Analysis', 'Lineage']} />
    </div>
  </div>
);
```

```css
.trade-page {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 136px);  /* topbar + secondarynav + ticker */
  overflow: hidden;
}
.trade-symbol-bar {
  height: 48px;
  background: var(--bg-panel);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: var(--s-4);
  padding: 0 var(--s-4);
  flex-shrink: 0;
}
.trade-body {
  display: grid;
  grid-template-columns: 60fr 20fr 20fr;
  flex: 1;
  overflow: hidden;
  gap: 0;
  border-bottom: 1px solid var(--border);
}
.trade-chart { overflow: hidden; border-right: 1px solid var(--border); }
.trade-book  { overflow-y: auto; border-right: 1px solid var(--border); padding: var(--s-3); }
.trade-form  { overflow-y: auto; padding: var(--s-4); }
.trade-tape  {
  height: 60px;
  background: var(--bg-base);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: 0 var(--s-4);
  overflow-x: auto;
  flex-shrink: 0;
  font-family: 'JetBrains Mono', 'IBM Plex Mono', monospace;
  font-size: var(--tx-xs);
}
.trade-bottom { height: 180px; flex-shrink: 0; }
```

---

## 16.6 Paper Order Form Component

```tsx
// components/trading/PaperOrderForm.tsx
export function PaperOrderForm({ symbol, currentPrice }: Props) {
  const [side, setSide] = useState<'buy' | 'sell'>('buy');
  const [orderType, setOrderType] = useState<'market' | 'limit'>('market');
  const [amount, setAmount] = useState('');
  const [showConfirm, setShowConfirm] = useState(false);

  const handleSubmit = async () => {
    // POST to /api/v1/intents/ with paper mode flag
    const res = await fetch('/api/v1/intents/', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${useAuth.getState().token}`,
      },
      body: JSON.stringify({
        symbol,
        side,
        order_type: orderType,
        notional_usdt: parseFloat(amount),
        mode: 'paper',  // ALWAYS paper
        paper_mode: true,
        live_order: false,
      }),
    });
    setShowConfirm(false);
  };

  return (
    <div className="paper-form">
      <div className="paper-form__mode-badge">
        <span className="chip chip--paper">⬣ PAPER MODE</span>
        <small>No real money. No live exchange.</small>
      </div>

      <div className="paper-form__tabs">
        <button className={orderType === 'market' ? 'active' : ''} onClick={() => setOrderType('market')}>Market</button>
        <button className={orderType === 'limit' ? 'active' : ''} onClick={() => setOrderType('limit')}>Limit</button>
      </div>

      <div className="paper-form__amount">
        <label>Amount (USDT)</label>
        <input type="number" value={amount} onChange={e => setAmount(e.target.value)} placeholder="0.00" />
      </div>

      <div className="paper-form__actions">
        <button
          className="btn-buy"
          onClick={() => { setSide('buy'); setShowConfirm(true); }}
          disabled={!amount}
        >
          Paper Buy Long
        </button>
        <button
          className="btn-sell"
          onClick={() => { setSide('sell'); setShowConfirm(true); }}
          disabled={!amount}
        >
          Paper Sell Short
        </button>
      </div>

      {showConfirm && (
        <ConfirmModal
          title={`Paper ${side === 'buy' ? 'Buy Long' : 'Sell Short'}`}
          body={`Submit paper ${side} intent for ${symbol}: ${amount} USDT at market price ~$${currentPrice?.toFixed(2)}`}
          onConfirm={handleSubmit}
          onCancel={() => setShowConfirm(false)}
        />
      )}
    </div>
  );
}
```

---

## 16.7 Human-Readable Status Strings

**This is a quick win.** Replace all raw status strings in AdminShell and throughout the app:

```typescript
// utils/statusLabels.ts — centralized human-readable labels
export const STATUS_LABELS: Record<string, string> = {
  'LIVE_ARMED_BALANCE_HOLD': 'Live Armed — Balance Hold',
  'INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER': 'Insufficient Balance',
  'SIGNED_READS_RECOVERED_BALANCE_HOLD': 'Reads Recovered — Balance Hold',
  'HISTORICAL_PAPER_ONLINE_PNL_SEPARATE_FROM_CURRENT_LEDGER': 'Historical PnL Active',
  'PAPER_RUNTIME_ONLINE_ACTIVE': 'Paper Trading Active',
  'PAPER_RUNTIME_OFFLINE': 'Paper Trading Offline',
  'enabled_operator_approved': 'Gate Approved',
  'BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN': 'Blocked — Edge Not Proven',
  'blocked': 'Risk Gate Blocked',
  'evidence_missing': 'Evidence Pending',
  'not available from current payload': 'Data Pending',
  'WORKER_HEALTHY': 'Healthy',
  'WORKER_DEGRADED': 'Degraded',
  'WORKER_OFFLINE': 'Offline',
};

export function humanStatus(raw: string | undefined, fallback = 'Pending'): string {
  if (!raw) return fallback;
  return STATUS_LABELS[raw] ?? raw.replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
}
```

Import and use `humanStatus()` everywhere instead of raw status strings.

---

## 16.8 Markets Page — Required Column Additions

**Current columns:** Symbol, Price, Confidence, Move, Timeframe coverage dots  
**Required columns:** Symbol, Price, 24h%, Volume, OI, Funding, L/S Ratio, AI Conf, Signal, Sparkline

```tsx
// pages/markets/index.tsx — add these columns to screener table

// Data sources (already available in payload files):
// - 24h%: from chartManifest payload (latest_mid_px comparison) or derivatives payload
// - Volume: from derivatives payload (/api/v1/derivatives/exchanges)
// - OI: from /api/v1/derivatives/open-interest
// - Funding: from /api/v1/derivatives/funding
// - L/S: from /api/v1/derivatives/long-short
// All these APIs are ACTIVE — use them via fetch instead of payload polling

// Sparkline: use recharts <Sparkline> or simple SVG
// Each row renders a 60x24px sparkline from the last 24h mid_px values
// Source: the market chart payload has time-series data per symbol

// Symbol search filter:
const [search, setSearch] = useState('');
const filtered = symbols.filter(s => s.symbol.toLowerCase().includes(search.toLowerCase()));
```

---

## 16.9 KPI Card Component

```tsx
// components/ui/KPICard.tsx
interface KPICardProps {
  label: string;
  value: string;
  delta?: string;         // "+1.24%" colored green/red
  polarity?: 'up' | 'down' | 'neutral' | 'warn' | 'ai';
  isLive?: boolean;       // pulsing dot
  onClick?: () => void;
}

export function KPICard({ label, value, delta, polarity = 'neutral', isLive, onClick }: KPICardProps) {
  return (
    <div className={`kpi-card kpi-card--${polarity}`} onClick={onClick} role={onClick ? 'button' : undefined}>
      <div className="kpi-card__header">
        <span className="kpi-card__label">{label}</span>
        {isLive && <span className="live-dot" aria-label="Live" />}
      </div>
      <div className="kpi-card__value">{value}</div>
      {delta && <div className={`kpi-card__delta ${parseFloat(delta) >= 0 ? 'kpi-card__delta--up' : 'kpi-card__delta--down'}`}>{delta}</div>}
    </div>
  );
}
```

```css
.kpi-card {
  padding: var(--s-3) var(--s-4);
  background: var(--bg-panel);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  min-width: 140px;
  cursor: default;
}
.kpi-card__header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--s-1); }
.kpi-card__label { font-size: var(--tx-xs); color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.8px; font-weight: 600; }
.kpi-card__value { font-family: 'JetBrains Mono', monospace; font-size: var(--tx-2xl); font-weight: 700; color: var(--text-primary); }
.kpi-card--up .kpi-card__value { color: var(--buy); }
.kpi-card--down .kpi-card__value { color: var(--sell); }
.kpi-card--warn .kpi-card__value { color: var(--warn); }
.kpi-card--ai .kpi-card__value { color: var(--ai); }
.kpi-card__delta { font-size: var(--tx-sm); margin-top: var(--s-1); }
.kpi-card__delta--up { color: var(--buy); }
.kpi-card__delta--down { color: var(--sell); }
.live-dot {
  width: 6px; height: 6px; border-radius: 50%; background: var(--ok);
  animation: pulse 2s ease-in-out infinite;
}
@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} }
```

---

## 16.10 Admin Portal Routing

```tsx
// router.tsx — add admin portal routes
import { AdminPortalShell } from './components/layout/AdminPortalShell';
import { ADMIN_PAGES } from './pages/admin-registry';

const adminChildren = ADMIN_PAGES.map((p) => ({
  path: p.route.path,
  element: <p.Component />,
}));

export const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/dashboard" replace /> },
  ...legacyRedirects,
  { element: <PublicShell />, children: publicChildren },
  { element: <AdminShell />, children: protectedChildren },
  // NEW: admin portal — visually separate, purple accent
  {
    element: <AdminPortalShell />,
    children: adminChildren,
  },
  { path: '*', element: <Navigate to="/landing" replace /> },
]);
```

Admin pages to move from the main nav to the admin portal:
- `/system/control-center` → `/admin/control-center` (restricted, admin only)
- `/system/build-validation` → `/admin/build-validation`
- `/system/coverage` → `/admin/coverage`
- `/system/scripts` → `/admin/scripts`
- `/system/evidence` → `/admin/evidence`
- `/system/codex-review-center` → `/admin/codex` (superadmin)
- `/system/ai-tools` → `/admin/ai-tools`

---

# SECTION 17: MULTI-TRADER SYSTEM SPECIFICATION

## 17.1 Trader Account Model

Each trader account (once real auth is implemented) must have:

```
trader_id: UUID
username: string (display name)
email: string (login)
password_hash: string (bcrypt)
role: 'viewer' | 'trader' | 'admin' | 'superadmin'
paper_account_id: UUID (FK to paper accounts table)
watchlist: string[] (symbol IDs, stored as JSON)
alert_preferences: JSON
created_at: datetime
last_login: datetime
is_active: boolean
```

**Per-trader isolation:**
- Paper account state is per-trader (different equity, positions, history)
- Watchlist is per-trader
- Alerts are per-trader
- Trade history is per-trader

**Admin sees all traders:**
- `/admin/users` lists all traders, allows role changes
- Admins can view any trader's portfolio
- Admins can reset passwords

## 17.2 Trader Onboarding Flow

```
1. Admin creates trader account at /admin/users
   → Enter: username, email, role, initial paper balance
   → System emails temporary password (or shows it in admin UI)

2. Trader receives credentials, logs in at /login
   → Enter email + password
   → JWT issued, session stored

3. Trader lands on /dashboard
   → Personal paper portfolio (empty initially)
   → Can immediately use all trader features

4. Trader's paper trading is isolated
   → Their fills, positions, history are theirs only
   → Admin can see all traders in a view

5. If viewer role:
   → Read-only access to all public data, signals, AI
   → Cannot place paper orders
   → Cannot access admin portal
```

---

*End of document. Total audit sections: 17.*  
*Crawl date: June 12-13, 2026 | Auditor: Claude Code (Sonnet 4.6)*  
*Files inspected: 83 TSX components, 71 backend service files, 270 frontend source files, 2,083 payload JSON files, 30+ backend worker processes*  
*All code in this document is developer guidance only. No code was modified during this audit.*

---

## Section 18 — CoinAnk ProChart Specification

**Full specification moved to separate file to keep this document navigable.**

See: [`v2/docs/prochart-specification.md`](v2/docs/prochart-specification.md)

**Summary of Section 18 scope:**
- New FastAPI endpoint `/api/v1/chart/coinank/{symbol}/{timeframe}` — reads OI, L/S, funding, CVD from Redis (`v2:coinank:*` keys already populated by the CoinAnk ingestor)
- New `ProChart.tsx` component using lightweight-charts v5 with 3 sub-panes: Open Interest, Net Long/Short, Volume
- New `ProChartSymbolPanel.tsx` — right-side symbol watchlist with favorites, search, AI signal direction indicators
- New `/chart/:symbol` page wiring everything together with timeframe tabs (1m, 5m, 15m, 1h, 4h)
- Full CSS for the CoinAnk-style dark layout
- Phase A-E implementation priority breakdown (Phase A = 1-2 days)
