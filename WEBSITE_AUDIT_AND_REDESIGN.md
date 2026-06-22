# Website Full Audit & Enterprise Redesign Plan
**Audit Date:** 2026-05-22  
**Current Site:** V2 React/Vite frontend at `/v2/frontend/`  
**Backend:** FastAPI (NOT running — uvicorn not started)  
**Live Data Source:** Legacy Redis `localhost:6379/0` (live, 12,624 keys, 8GB limit)  
**Paper Runtime:** V2 paper loop running, BTCUSDT price ≈ $75,368 (live read-only feed)

---

## PART 1 — WHAT IS CURRENTLY STALE, INCOMPLETE, OR INCORRECT

### 1.1 Stale JSON Payloads Served to the Website

The frontend reads static JSON files from `/v2/frontend/public/`. These are pre-built payload files written by background workers. Below is the freshness audit:

| Payload File | Age | Status | What It Shows |
|---|---|---|---|
| `operator_truth/latest/operator_truth_payload.json` | **144 hours (6 days)** | 🔴 STALE | System truth — trainer status, signal lineage, blockers, freshness |
| `operator_runtime/coinank_market_intelligence/latest/...` | **171 hours (7 days)** | 🔴 STALE | CoinAnk OI, funding, L/S ratios, CVD |
| `operator_runtime/paper_online/latest/paper_runtime_status.json` | **< 1 min** | ✅ FRESH | Paper runtime state, price, paper equity |
| `operator_runtime/v2_market_ingestor/latest/...` | **MISSING** | 🔴 MISSING | Market ingestor status |
| `operator_runtime/v2_feature_pipeline_native/latest/...` | **MISSING** | 🔴 MISSING | Feature pipeline status |
| `operator_runtime/v2_trade_management_paper/latest/...` | **MISSING** | 🔴 MISSING | Paper trade management |
| `operator_runtime/v2_rl_core/latest/...` | **MISSING** | 🔴 MISSING | RL/AI core status |
| `operator_runtime/v2_top10_binance_dashboard_feed/...` | **< 3 min** | ✅ FRESH | Top-10 Binance tickers (but ALL rows are EMPTY — no actual data) |
| `operator_runtime/v2_alt_data_symbol_candidate_publisher/...` | **1,417 min (~24h)** | 🟡 STALE | Alt data scores |
| `operator_runtime/v2_lunarcrush_altdata_client/...` | **1,801 min (~30h)** | 🔴 STALE | LunarCrush alt data |
| `operator_runtime/v2_nansen_altdata_client/...` | **1,992 min (~33h)** | 🔴 STALE | Nansen alt data |
| `operator_runtime/legacy_runtime_observer/latest/current_runtime_truth_payload.json` | **MISSING** | 🔴 MISSING | Live legacy runtime bridge |
| `operator_runtime/v2_realtime_user_website_from_real_payloads/...` | **6,931 min (~4.8 days)** | 🔴 STALE | Realtime user website payload |

### 1.2 Pages with No Real Data (Stubs / Static Fixtures)

| Page | Current State | What's Missing |
|---|---|---|
| **Signals** | `PageShell` stub — renders empty shell. No signal data fetched. | All signal data. No hook, no API call, no display. |
| **Market Intelligence** | `PageShell` stub — no implementation. | CoinAnk CVD, OI, funding rates, L/S ratios — all exist in legacy Redis but not wired. |
| **Positions** | `PageShell` stub | Live positions from legacy Redis (`positions:*`, `active_positions:*`) |
| **System Health** | `PageShell` stub | Service heartbeats, Redis health, ingestor uptime |
| **Executions** | `PageShell` stub — "paper-only by default" | Actual paper fills + legacy execution history |
| **Replay** | Shows `STATIC_PROOF_FIXTURE` explicitly — offline only | Historical OHLCV + replay decisions |
| **Paper Trading** | Has implementation but most metrics show `MISSING_EVIDENCE` | trainer state=`V2_PAPER_TRAINER_WRAPPER_CURRENT` but confidence=null, direction=null |
| **Trainer Prediction Monitor** | Pulls live paper runtime but most trainer fields are null | Trainer predictions ARE in legacy Redis (`prediction:BTCUSDT:multi`) but not bridged to V2 |
| **Symbols** | `PageShell` stub | Symbol universe, rankings, alternative data scores |

### 1.3 Data That Is Incorrect or Misleading

| What the Site Shows | What's Actually True | Severity |
|---|---|---|
| Top-10 Binance dashboard has fresh timestamp (3 min ago) but **all rows are empty** — `futures_trades_12h.rows: []` | Worker is running but writing no data | 🔴 Misleading |
| Paper equity = `$9,950.65` presented as if meaningful | This is a simulated starting equity of $10,000 minus small paper losses. Not real money. | 🟡 Needs clearer label |
| `market_price: 75368.6` with source `READONLY_MARKET_FEED` | This IS real (Binance read-only feed), accurate | ✅ Correct |
| `trainer_state: V2_PAPER_TRAINER_WRAPPER_CURRENT` with `confidence: null` | The V2 trainer wrapper is a bridge to the legacy trainer — but confidence output is not being bridged through | 🔴 Misleading |
| `operator_truth` payload is **6 days stale** but page may show it as "current" | Truth payload writer is not running | 🔴 Critical |
| CoinAnk market intelligence panel is **7 days stale** | `live_coinank.py` IS running live in legacy right now — the bridge worker hasn't written a new payload in 7 days | 🔴 Major gap |
| Live gate shown as `blocked_human_only` | Correct | ✅ Accurate |
| `prediction:BTCUSDT:multi` in Redis has data | Frontend has NO component reading this key | 🔴 Data exists but not displayed |

### 1.4 What the Backend API Should Serve (But Backend is NOT Running)

The frontend tries to fetch from relative paths like `/operator_truth/latest/operator_truth_payload.json`. Currently these resolve to **static files in the `public/` folder** — not a live API. This means:
- All data is batch-refreshed, not truly real-time
- FastAPI backend (uvicorn) is NOT started — any route needing `/api/v2/*` returns 404
- No WebSocket connection to push live updates to the browser
- All data is at best 60-second intervals (refresh cycle of background workers)

---

## PART 2 — WHAT TO REMOVE FROM THE WEBSITE

These pages/panels serve no useful purpose currently and add confusion:

| Page/Panel | Reason to Remove |
|---|---|
| **Codex Review Center** | Internal AI audit tooling — not relevant to a trading operations website |
| **Claude Admin AI** | Internal AI supervision page — developer tooling, not operator-facing |
| **Permanent Migration** | Developer migration tracking — irrelevant to live operations |
| **Coverage System Atlas** | Developer code coverage map — irrelevant to users |
| **Build Validation Status** | CI/CD status — developer tooling |
| **Audit Ledger (internal provenance)** | The cryptographic SHA256 audit chain is developer tooling, not operational |
| **Proof panels** (on every page with "STATIC_PROOF_FIXTURE" chips) | Clutters operator view with developer evidence trails |
| **`operator_truth` provenance chain** displayed inline on Mission Control | Deeply technical, adds noise. Move to separate developer page. |
| **Admin War Room** | Internal sprint tooling page |
| **Script Registry** (as currently built — just a list of file hashes) | Replace with a live service health dashboard instead |
| **All "Source Ribbon" banners** showing `CONTINUOUS_NON_LIVE / V2_PROOF_ARTIFACT` | These are developer labels, not useful to operators or public visitors |

---

## PART 3 — WHAT WE CAN ADD (WHAT LEGACY HAS, ALREADY MIGRATED OR READABLE)

### Available RIGHT NOW from Legacy Redis (live, accurate data):

| Data | Redis Key(s) | Legacy Script | Available for Site |
|---|---|---|---|
| **Live BTCUSDT price** | `price:BTCUSDT`, `price:realtime:BTCUSDT` | `live_binance.py` | ✅ Already wired (read-only feed) |
| **OHLCV candles** (all 25 symbols, 5 TFs) | `ohlcv:list:binance:{SYM}:{TF}` | `live_binance.py` | ✅ Can be wired |
| **Orderbook bids/asks** | `orderbook:bids:BTCUSDT`, `orderbook:asks:BTCUSDT` | `live_binance.py` | ✅ Can be wired |
| **TA indicators** (300+ per symbol/TF) | `ta:{SYM}:{TF}` | `live_technical_analysis.py` | ✅ Running live |
| **Feature vector** | `unified_features:BTCUSDT:5m` | `feature_pipeline.py` | ✅ Running live (confirmed 200+ fields) |
| **Trainer predictions** | `prediction:BTCUSDT:multi`, `prediction:{SYM}:{TF}` | `hybrid_trainer.py` | ✅ Running, data in Redis |
| **Signals stream** | `signals:trading:primary` (50,000 entries) | `orchestrator_worker.py` | ✅ Live stream |
| **Liquidations** | `liquidations:events` stream | `live_binance_liquidations.py` | ✅ Running live |
| **CoinAnk CVD** | `features:coinank:{SYM}:{TF}` | `live_coinank.py` | ✅ Running live |
| **CoinAnk funding rates** | `features:coinank:{SYM}:{TF}` | `live_coinank.py` | ✅ Running live |
| **CoinAnk OI** | `features:coinank:{SYM}:{TF}` | `live_coinank.py` | ✅ Running live |
| **CoinAnk L/S ratios** | `features:coinank:{SYM}:{TF}` | `live_coinank.py` | ✅ Running live |
| **Global market aggregates** | `features:global_coinank:*` | `live_coinank_global_aggregator.py` | ✅ Running live |
| **CoinAPI microstructure** | `msnap:coinapi_wsds:{SYM}` | `live_coinapi_wsds.py` | ✅ Running live |
| **KuCoin prices** | various KuCoin keys | `live_kucoin.py` | ✅ Running live |
| **TokenMetrics AI scores** | `features:tokenmetrics:*` | `live_tokenmetrics.py` | ✅ Running live |
| **Paper equity + PnL** | V2 paper runtime | V2 paper loop | ✅ Already shown |
| **Top-10 Binance rankings** | `v2:dashboards:binance_top10:*` | V2 top10 feed | ✅ Worker running but empty rows — bug to fix |
| **Liquidation levels** | `liq_levels:{SYM}` | `liquidation_levels_engine.py` | ✅ Can be wired |
| **Market regime** | `unified_features:*` (regime field) | `feature_pipeline.py` | ✅ In feature vector |
| **Trainer checkpoint info** | `checkpoints/` directory + Redis | `hybrid_trainer.py` | ✅ Can be read |
| **Portfolio PnL history** | Various Redis position keys | `monitor_portfolio_primary.py` | ✅ Running live |

---

## PART 4 — ENTERPRISE REDESIGN SUGGESTIONS (READ-ONLY)

### Design Principle: "Even a Small Kid Can Understand"

Every section should answer one simple question in plain English, with a colour (green/yellow/red) and a number. Technical details collapse below.

---

### Proposed Page Structure

```
HOME (PUBLIC)
  ├── Live Market Pulse          — What is the market doing RIGHT NOW?
  ├── Bot Status Summary         — Is the bot running? Is it healthy?
  ├── Today's Performance        — How much profit/loss today?
  └── What the AI is Thinking    — Simple signal: BUY / SELL / WAIT

MARKET INTELLIGENCE (PUBLIC)
  ├── Top 10 Movers              — Biggest gainers/losers (Binance Top-10)
  ├── Funding Rates              — Are traders paying to be long or short?
  ├── Open Interest Heatmap      — How much money is in the market?
  ├── Long/Short Ratio           — Who is winning — bulls or bears?
  ├── Liquidation Map            — Where will forced sell-offs happen?
  └── Orderbook Depth            — How strong is the buy/sell wall?

AI BRAIN (OPERATOR / OBSERVER)
  ├── Current Prediction         — What the AI thinks will happen next
  ├── Confidence Meter           — How sure is the AI? (0-100%)
  ├── Top Features               — Why does it think that?
  ├── Training Progress          — Is the AI learning? What epoch?
  ├── Model Performance          — How accurate has the AI been?
  └── Signal Timeline            — History of AI calls (right/wrong)

TRADER (OPERATOR)
  ├── Current Positions          — What is open right now?
  ├── Recent Trades              — Last 10 trades with P&L
  ├── Risk Dashboard             — How much risk are we taking?
  ├── Paper vs Real Comparison   — Paper simulation vs real outcome
  └── Trade Entry/Exit Logic     — Why did it enter? Why did it exit?

SYSTEM HEALTH (OPERATOR)
  ├── Ingestor Status Board      — All 12 data feeds: green/red
  ├── Redis Memory               — How full is the database?
  ├── Process Monitor            — All running scripts: alive/dead
  ├── Data Freshness             — Is the data we have fresh?
  └── Error Log                  — Recent errors in plain English

HISTORY (OBSERVER / PUBLIC)
  ├── 30-Day PnL Chart           — Past performance
  ├── Trade Journal              — Every past trade explained
  ├── Market Replay              — Replay any day with AI decisions overlaid
  └── Strategy Evolution         — How the AI has changed over time
```

---

### Page-by-Page Enterprise Redesign Spec

---

#### 🏠 HOME PAGE — "The Mission Briefing"

**What a small kid sees:** "The AI is watching 25 markets. It made 3 trades today. It is UP $47."

**Sections:**
1. **Status Bar (top, always visible)**
   - 🟢/🔴/🟡 indicator for: Bot Running · AI Training · Data Fresh · Last Trade
   - Live BTC price (large, prominent)
   - Time since last signal

2. **Market Mood** (derived from `features:global_coinank:*` + `unified_features:BTCUSDT:1h`)
   - Simple gauge: EXTREME FEAR → FEAR → NEUTRAL → GREED → EXTREME GREED
   - BTC 24h change %, funding rate, dominant side (longs or shorts)
   - Source: CoinAnk global aggregator (live, running)

3. **AI Signal Card** (from `prediction:BTCUSDT:multi` in Redis)
   - Current direction: BUY / SELL / HOLD
   - Confidence: % bar
   - "The AI thinks BTC will go UP with 71% confidence"
   - Why: Top 3 positive features in plain English
   - Source: `hybrid_trainer.py` (running now), `prediction:BTCUSDT:multi`

4. **Today's Performance** (from legacy portfolio monitor, V2 paper runtime)
   - Paper PnL today, paper equity
   - Open positions count
   - Last trade result

5. **Quick Links** → Market Intelligence, AI Brain, Trade History

**Data available RIGHT NOW:** All of above is live in Redis.

---

#### 📊 MARKET INTELLIGENCE PAGE

**What a small kid sees:** "BTC costs $75,368. Big traders are mostly buying. The funding rate means it costs money to bet it goes up."

**Sections:**
1. **Live Price Ticker Strip** — All 25 symbols (from `price:realtime:*`)
   - Symbol, price, 1h change, 24h change
   - Colour coded: green up, red down

2. **Top 10 Movers Panel** (from `v2:dashboards:binance_top10:*` — currently empty, bug to fix)
   - Top gainers / losers by volume, trades, volatility
   - Last 12h data

3. **Funding Rate Table** (from `features:coinank:{SYM}:{TF}` — live)
   - All 25 symbols with funding rate
   - Positive = longs paying = bullish bias
   - Negative = shorts paying = bearish bias
   - Plain English: "BTC bulls are paying 0.01% every 8 hours"

4. **Open Interest Bar Chart** (from `features:coinank:{SYM}:{TF}` OI fields)
   - OI in USD per symbol
   - OI change 24h (arrow: rising or falling)
   - Plain English: "More money entered BTC futures today"

5. **Long/Short Ratio** (from CoinAnk `ls_buy_sell` data)
   - Per symbol: % longs vs % shorts
   - Simple visual: bar split green/red
   - Plain English: "70% of traders are betting BTC goes up"

6. **Liquidation Heatmap** (from `liquidations:events` Redis stream + `liq_levels:*`)
   - Where will liquidations happen if price moves ±2%, ±5%, ±10%
   - Plain English: "If BTC drops to $72,000, $200M in long positions get liquidated"

7. **CVD (Cumulative Volume Delta)** (from `features:coinank:{SYM}:{TF}` CVD fields)
   - Are buyers or sellers dominating the actual trades?
   - Simple line chart: positive = buyers winning

8. **Orderbook Depth** (from `orderbook:bids/asks:BTCUSDT`)
   - Visual depth chart showing buy wall vs sell wall

**ALL data above is available live in legacy Redis right now.**

---

#### 🧠 AI BRAIN PAGE — "What is the AI Thinking?"

**What a small kid sees:** "The AI studied 57,000 lines of rules and 200 signals. It thinks BTC will go UP. It's 71% sure. Here's why..."

**Sections:**
1. **Current Prediction Card** (from `prediction:BTCUSDT:multi`)
   - Direction: BUY / SELL / HOLD (big, bold, coloured)
   - Confidence: animated gauge 0-100%
   - Timeframes: what does it think for 5m? 15m? 1h? 4h?
   - Prediction age: "Made 8 seconds ago"

2. **Why It Thinks That** (from feature importance in prediction payload)
   - Top 5 bullish signals: e.g. "RSI is rising", "Big buyers dominating", "Funding rate negative = shorts paying"
   - Top 5 bearish signals
   - Plain English translations of technical indicators

3. **Confidence History** (from `signals:trading:primary` stream)
   - Last 50 predictions with confidence over time
   - How often was it right? Win rate.

4. **Training Status** (from `hybrid_trainer.py` process + Redis)
   - Current epoch / total epochs
   - Training loss (lower = better)
   - "The AI is on training round 847 of 1000. It's getting smarter."
   - GPU utilisation %
   - Last checkpoint: when? How good?

5. **Feature Inputs Dashboard** (from `unified_features:BTCUSDT:5m`)
   - Key inputs the AI used for its last decision
   - Grouped: Price Momentum · Volume · Market Structure · CoinAnk · Liquidations
   - Each with a simple bar showing how bullish/bearish it is

6. **Model Performance** (from past signals vs outcomes in `signals:trading:primary`)
   - Win rate last 24h, 7d, 30d
   - Avg confidence on winning trades vs losing trades
   - Calibration: "When AI says 80% confidence, does it win 80% of the time?"

---

#### 💼 TRADER PAGE — "What Trades Are Running?"

**What a small kid sees:** "The bot is watching 1 trade right now. It's making $12. It will close if it drops to $X."

**Sections:**
1. **Live Positions** (from legacy Redis `positions:*`, V2 paper positions)
   - Symbol, direction (LONG/SHORT), entry price, current price
   - Unrealised PnL ($ and %)
   - Stop loss level, take profit level
   - Time in trade

2. **Recent Trades** (from legacy signals stream + portfolio monitor)
   - Last 20 trades: symbol, direction, entry, exit, PnL, reason for exit
   - Colour coded: green profit / red loss

3. **Paper vs Reality Comparison** (V2 paper loop vs legacy signals)
   - What did the paper simulation decide vs what the real bot did?
   - Are they matching? Differences highlighted.

4. **Risk Dashboard**
   - Current exposure ($)
   - Max daily loss limit and how close we are
   - Hedge status: hedging active or not?
   - Daily trades used vs daily limit

5. **Trade Logic Explainer** (from orchestrator decisions)
   - For current open position: step-by-step why it entered
   - Entry criteria met: ✅ RSI crossing, ✅ Confidence > 70%, ✅ Funding negative...
   - Exit plan: "Will exit at +2% or if confidence drops below 60%"

---

#### 🏥 SYSTEM HEALTH PAGE — "Is Everything Running?"

**What a small kid sees:** "12 out of 12 systems are running. The data is fresh. No errors."

**Sections:**
1. **Ingestor Health Board** (from heartbeat keys + process check)
   - Each ingestor as a tile: GREEN = running + fresh data, RED = down
   - `live_binance.py` ✅ · `live_coinank.py` ✅ · `live_kucoin.py` ✅ etc.
   - Last data received: "2 seconds ago"

2. **Process Monitor** (from `pgrep` output exposed via API)
   - All 15 legacy processes listed
   - Uptime, PID, last log line
   - Colour: green alive / red dead

3. **Data Freshness Board** (from Redis TTL checks)
   - Each data category: HOW OLD is the newest data?
   - Price: 0.3s · TA: 4s · Predictions: 12s · CoinAnk: 45s

4. **Redis Health** (from Redis INFO)
   - Memory used vs 8GB limit (% bar)
   - Keys count: 12,624
   - Operations per second

5. **Error Log** (from log files, plain English summarized)
   - Last 10 errors across all scripts
   - Plain English: not raw Python tracebacks

---

#### 📈 HISTORY PAGE — "What Happened Before?"

**What a small kid sees:** "Last 30 days: 147 trades. 61% winners. Total profit: +$824."

**Sections:**
1. **30-Day PnL Chart** (from portfolio monitor Redis keys)
   - Line chart: equity over time
   - Annotated: drawdown periods, best days

2. **Trade Journal** (from `signals:trading:primary` stream)
   - Every trade with: entry, exit, reason, P&L
   - Filterable by symbol, date, direction, result

3. **Strategy Evolution** (from checkpoint history)
   - How the AI's win rate changed over time as it trained
   - Key turning points

4. **Market Replay** (from OHLCV in Redis + signal history)
   - Pick any day → see candle chart + AI decisions overlaid
   - "On May 10th, the AI made 4 calls. It was right 3 times."

---

### Navigation Redesign

**Current nav is too technical and developer-focused.** Replace with:

```
PUBLIC (no login)
  Home          — Market pulse + bot summary
  Markets       — Price, funding, OI, L/S, liquidations
  Status        — Is the system healthy?

OBSERVER (read-only login)
  AI Brain      — Predictions, confidence, features
  Trader        — Positions, recent trades, risk
  History       — PnL chart, trade journal, replay

OPERATOR (admin login)
  Mission Control    — Full operator dashboard (existing)
  Risk Control       — Risk gates, hedging, limits
  Config Admin       — Parameters and settings
  Paper Trading      — Paper simulation details
  Exchange Manager   — API connection status
```

---

## PART 5 — IMPLEMENTATION PRIORITY (WHAT TO BUILD FIRST)

All of the below reads from legacy Redis or the V2 paper runtime. Nothing requires new data sources.

### Priority 1 — Fix What's Broken (1-2 days)
1. **Start uvicorn** — backend must be running to serve real API responses
2. **Fix operator_truth worker** — it's been 6 days stale, restart the background writer
3. **Fix CoinAnk bridge worker** — it's 7 days stale despite live_coinank.py running
4. **Fix Top-10 feed rows** — worker runs but rows are empty; the Redis keys `v2:dashboards:binance_top10:*` need the Binance data actually fetched and written
5. **Wire `prediction:BTCUSDT:multi`** → paper_runtime trainer fields (confidence, direction are null despite Redis having data)

### Priority 2 — Add Real Data to Existing Pages (2-3 days)
1. **Market Intelligence page** — wire CoinAnk funding, OI, L/S from `features:coinank:*`
2. **Signals page** — read `signals:trading:primary` Redis stream, show last 20 signals
3. **Positions page** — read paper positions from V2 paper loop (already in public JSON)
4. **Trainer Prediction page** — wire confidence + direction from `prediction:BTCUSDT:multi`

### Priority 3 — New Enterprise Sections (1 week)
1. **Home page redesign** — Market mood gauge, AI signal card, today's performance
2. **System Health board** — Ingestor tiles, process monitor, Redis health
3. **AI Brain page** — Feature inputs dashboard, confidence history
4. **History/Trade Journal** — Read from signals stream

### Priority 4 — Polish & Public-Facing (ongoing)
1. Plain English labels everywhere
2. Mobile-responsive layout
3. Auto-refresh every 10-15 seconds (not 60s batch)
4. Colour-coded status badges (green/yellow/red) for every metric
5. Tooltip explanations for every technical term

---

## PART 6 — DATA WIRING MAP (What Redis Key → What Page Section)

| Redis Key | Page | Section | Plain English Label |
|---|---|---|---|
| `price:realtime:BTCUSDT` | Home, Markets | Live Price | "Current BTC Price" |
| `ohlcv:list:binance:BTCUSDT:5m` | Markets, AI Brain | Chart | "5-Minute Candles" |
| `prediction:BTCUSDT:multi` | Home, AI Brain | AI Signal | "What AI Thinks" |
| `signals:trading:primary` (stream) | AI Brain, History | Signal Timeline | "Past AI Calls" |
| `unified_features:BTCUSDT:5m` | AI Brain | Feature Inputs | "AI's Inputs" |
| `features:coinank:BTCUSDT:1h` | Markets, AI Brain | CoinAnk Data | "Market Sentiment" |
| `features:global_coinank:*` | Home, Markets | Market Mood | "Overall Crypto Mood" |
| `orderbook:bids/asks:BTCUSDT` | Markets | Orderbook | "Buy vs Sell Wall" |
| `liquidations:events` (stream) | Markets | Liquidations | "Forced Closures" |
| `liq_levels:BTCUSDT` | Markets | Liq Map | "Where Pain Happens" |
| `ta:BTCUSDT:5m` | AI Brain | TA Indicators | "Technical Signals" |
| `heartbeat:*` | System Health | Ingestor Board | "Is X Running?" |
| V2 paper_runtime_status.json | Trader, Home | Paper Performance | "Paper Simulation" |
| `features:tokenmetrics:*` | Markets, AI Brain | TokenMetrics | "AI Market Scores" |
| Redis `INFO memory` | System Health | Redis Health | "Database Usage" |

---

*Audit produced from direct source code inspection, Redis key scan, payload freshness check, and process listing. No assumptions made.*
