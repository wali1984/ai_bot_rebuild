# AI BOT V2 — Master Operator Manual
Generated: 2026-07-01T22:56:31Z
Operator: Wali

---

## 1. System Overview

AI BOT V2 is a **non-live** algorithmic trading research platform. It ingests market data from multiple providers, builds features, trains a GPU-native reinforcement learning model (PPO + MASA), generates predictions, and paper-trades those predictions to collect outcomes and refine the model. **Live trading is permanently blocked until explicit operator approval.**

Current mode: **PAPER / SHADOW ONLY** — no real orders, no real money at risk.

---

## 2. Architecture Diagram

```
EXCHANGE (Binance USDM Futures)
    │ (read-only websocket / REST)
    ▼
INGESTORS (16 services — public or credentialed, all read-only)
    │
    ▼
FEATURE PIPELINE (TA-Lib + multi-source aggregation)
    │ v2:features:latest:{sym}:{tf}
    ▼
SNAPSHOT BUILDER (indexes feature vectors with lineage hashes)
    │ v2:features:snapshot:v2_fsnap_{hash}
    ▼
NATIVE CUDA TRAINER (RTX 5080, PPO+MASA, checkpoint .npz)
    │ v2:prediction:{sym}:{tf}
    ▼
ORCHESTRATOR (arbitration — 393 preds → 130 winners)
    │ v2:orchestrator:decisions
    ▼
RISK GATEWAY (rule engine — currently deny_default)
    │ v2:risk:gateway:decisions
    ▼
PAPER TRADER (sole owner; no real orders)
    │ v2:paper:ledger
    ▼
FEEDBACK LOOP (outcome labels → trainer)
    └──────────────────────────────────────► TRAINER (reward signal)

WEBSITE BACKEND (FastAPI / uvicorn)
    │ REST + SSE
    ▼
FRONTEND (React/Vite)
    + Mobile app (SwiftUI, TestFlight build 5)
```

---

## 3. Data-Source / Ingestor Table

| Ingestor | Provider | Status | Credential | Key Written |
|----------|---------|--------|-----------|-------------|
| Binance Kline WSS | Binance USDM | WORKING | None (public) | v2:features:latest:{sym}:{tf} |
| Binance Liq WSS | Binance forceOrder | WORKING | None (public) | v2:liq:events:stream |
| Liquidation Levels | Internal | WORKING | None | v2:liq:levels:{sym} |
| CoinAPI WSDS | CoinAPI | WORKING | COINAPI_KEY (present) | v2:market:coinapi:ohlcv:{sym}:{tf} |
| CoinAPI REST | CoinAPI | WORKING | COINAPI_KEY (present) | v2:market:coinapi:rest:{sym}:{tf} |
| KuCoin REST | KuCoin | WORKING | None (public) | v2:features:kucoin:{sym}:{tf} |
| CoinAnk Live | CoinAnk | WORKING | COINANK_KEY (present) | v2:altdata:coinank:{sym} |
| CoinAnk Aggregator | CoinAnk | WORKING | COINANK_KEY (present) | v2:altdata:coinank:global |
| AICoin Whale Walls | AICoin | CRED_BLOCKED | 5 keys MISSING | v2:altdata:aicoin:symbol:{sym} (partial) |
| LunarCrush | LunarCrush | UNKNOWN | LUNARCRUSH_KEY | v2:altdata:lunarcrush:{sym} |
| Nansen | Nansen | UNKNOWN | NANSEN_KEY | v2:altdata:nansen:{sym} |
| Public Intel | CoinGecko/CoinGlass | WORKING | None | v2:altdata:public_intel:global |
| TA-Lib | Internal | WORKING | None | v2:features:ta_full:{sym}:{tf} |
| Feature Pipeline | Internal | WORKING | None | v2:features:latest:{sym}:{tf} |
| Symbol Discovery | Binance exchange info | WORKING | None | v2:altdata:symbol_score:{sym} |
| Arkham (presence) | Internal stub | WORKING | None | v2:alt_data:arkham:presence |

---

## 4. Redis Key and Payload Map

| Key Pattern | Producer | Consumer | Purpose |
|-------------|---------|---------|---------|
| v2:features:latest:{sym}:{tf} | Feature Pipeline | Trainer | Feature vector per symbol/timeframe |
| v2:features:snapshot:v2_fsnap_{hash} | Snapshot Builder | Trainer | Immutable feature snapshot with lineage |
| v2:features:ta_full:{sym}:{tf} | TA-Lib loop | Feature Pipeline | Technical indicators |
| v2:liq:levels:{sym} | Liq Engine | Risk Gateway | Liquidation price levels |
| v2:prediction:{sym}:{tf} | Trainer Publisher | Orchestrator | Model predictions |
| v2:orchestrator:decisions | Orchestrator | Risk Gateway | Selected arbitrated signals |
| v2:risk:gateway:decisions | Risk Gateway | Paper Trader | Risk-approved/denied decisions |
| v2:paper:ledger | Paper Trader | Website | Open positions, PnL |
| v2:paper:closed_trades | Paper Trader | Feedback Loop | Closed trade history |
| v2:trainer:feedback:outcomes | Feedback Loop | Trainer | Outcome labels for training |
| v2:trainer:hybrid_cuda:heartbeat | Trainer | Monitor | Trainer health |
| v2:paper:heartbeat | Paper Trader | Monitor | Paper trader health |
| v2:live_gate:state | Operator (manual) | All | Live gate config |

Full map: `docs/system_audit_2026_master/redis_keyspace_map.json`

---

## 5. How Market Data Becomes Features

1. **Binance Kline WSS** streams 1m, 5m, 15m, 1h, 4h candles → `v2:market:kline:{sym}:{tf}`
2. **KuCoin REST** provides cross-exchange price/volume → `v2:features:kucoin:{sym}:{tf}`
3. **CoinAPI WSDS/REST** provides multi-exchange OHLCV → `v2:market:coinapi:ohlcv:{sym}:{tf}`
4. **TA-Lib loop** reads candle data and computes 50+ technical indicators → `v2:features:ta_full:{sym}:{tf}`
5. **CoinAnk** provides funding rate, OI, long/short ratio, basis → `v2:altdata:coinank:{sym}`
6. **Liquidation WSS** provides recent liq events; **Liq Levels Engine** computes estimated liq levels
7. **Feature Pipeline** aggregates all sources → unified feature vector → `v2:features:latest:{sym}:{tf}`
8. **Snapshot Builder** adds lineage hash and writes immutable snapshot → `v2:features:snapshot:v2_fsnap_{hash}`

---

## 6. How Trainer Learns

1. Trainer reads feature snapshots from Redis (`v2:features:snapshot:*`) in batches of ~4,000
2. Constructs tensors from feature vectors
3. Runs PPO actor-critic forward pass on CUDA (RTX 5080)
4. Computes PPO loss: clip ratio + entropy bonus + value loss
5. Runs backward pass and updates AdamW optimizer
6. Saves checkpoint to `.local_models/v2_native_rl_masa_ppo/{checkpoint_id}.weights.npz`
7. Reads outcome labels from `v2:trainer:feedback:outcomes` to update reward signal
8. **CURRENT ISSUE**: 741/741 feedback rows quarantined → trainer learning from paper outcomes is broken

---

## 7. How Predictions Are Produced

1. After each training step, trainer runs inference on latest feature snapshot
2. Outputs: `direction`, `selected_action`, `confidence_raw`, `confidence_calibrated`, `expected_move_bps`, `action_probabilities`, `price_targets`, `checkpoint_id`, `feature_snapshot_id`, `feature_cutoff`
3. Written to `v2:prediction:{symbol}:{timeframe}` (1,070 keys at audit time)
4. All-timeframe publisher aggregates and writes to website payload

---

## 8. How Signals Are Produced

1. Orchestrator reads all 1,070 prediction keys every cycle
2. Groups by (symbol, side) buckets
3. Selects winner per bucket (highest `confidence_calibrated`)
4. If LONG and SHORT conflict: `OPPOSITE_SIDES_DOMINANT_CONFIDENCE_WINS` rule selects one
5. 393 predictions → 130 bucket winners at audit time
6. Winners written to `v2:orchestrator:decisions` + `v2:signals:paper`

---

## 9. How Strategy Router Works

The **Continuous Edge Guardian** (`v2_continuous_edge_guardian`) acts as the A-grade gate:
- Evaluates whether signals meet quality thresholds
- Writes gate status to `v2:continuous_edge_guardian:a_grade_execution_gate`
- Orchestrator checks this gate before routing to paper trader
- If A-grade gate is FAIL, intents are held

---

## 10. How Risk Controller Works

The **Risk Gateway** (`v2_risk_gateway_live_loop`) evaluates each orchestrator proposal:
- Checks live gate state (currently: blocked_human_only → deny_default ALL)
- If live were enabled: checks data freshness, confidence, expected move, spread, liquidity, drawdown, exposure
- Writes `ALLOW` or `DENY` to `v2:risk:gateway:decisions`
- **Current**: 130/130 decisions = DENY (deny_default)
- `fail_closed = true` — any unknown state → DENY

---

## 11. How Orchestrator Works

See section 8 above. Additional details:
- Script: `v2_orchestrator_arbitration_loop.py`
- Cannot bypass risk gateway (`cannot_bypass_risk_gateway: true`)
- Holds intents if paper fill gate is active
- Runs continuously; each cycle takes ~6 seconds

---

## 12. How Paper Trader Works

The **Paper Trader** (`v2_trade_management_paper_loop`) is the sole paper owner (since 2026-06-27):
- Reads orchestrator decisions from `v2:signals:paper`
- Checks risk-approved decisions from `v2:risk:gateway:paper_online_decisions`
- Simulates fills at mark price ± slippage + fee
- Manages position lifecycle (LONG/SHORT → hold → close on exit signal/TP/SL)
- Writes fill to `v2:paper:ledger`, closed trade to `v2:paper:closed_trades`
- **Current state**: 456 accepted fills, 743 closed trades, -$253.49 realized PnL

---

## 13. How Live Trader Is Gated

Live trading is **permanently blocked** unless:
1. `live_gate` state updated to `live_enabled` (operator action)
2. `order_transport_submit_enabled` set to true (operator action)
3. Live symbols configured and matching accepted symbols
4. Kill switch inactive
5. Operator approved = true

Current status: BLOCKED (5 active blockers). See Phase 9 audit.

**NEVER enable live trading without:**
- Positive paper trading edge (currently negative)
- Trainer feedback loop repaired (currently 100% quarantined)
- Full pre-flight checklist completed

---

## 14. How Adaptive Capital/Leverage/Margin Works

Adaptive allocator (`v2/backend/app/services/adaptive_capital_allocator/`):
- Computes position size based on confidence, expected move, risk budget
- Enforces exchange min notional and lot size filters
- Tracks portfolio exposure and drawdown
- **In paper mode**: max_leverage = 1.0 (hard cap from live gate state)
- `v2_adaptive_capital_productivity_status.py` (13,098 lines) is the full status report

---

## 15. Website Route Guide

Access the website at: `http://localhost:8000` (or configured host/port)

Login: `admin` user with `Trader2026!` password (from `.auth_process_secret`)

| Page | URL | Purpose |
|------|-----|---------|
| Dashboard | /dashboard | System overview, key metrics |
| Markets | /markets | Market overview, symbol list |
| Market Detail | /market/{symbol} | Chart, TA, signals for one symbol |
| Trader | /trader | Paper trading terminal |
| Paper Trading | /paper-trading | Paper position management |
| Signals | /signals | Signal status |
| AI Predictions | /ai-predictions | Model prediction grid |
| Risk Control | /risk-control | Risk gateway status |
| Monitor Center | /monitor-center | All monitors |
| Ingestors | /ingestors | Ingestor status |
| Trainer Admin | /trainer-admin | Trainer status |
| Live Readiness | /live-readiness | Live gate checklist |
| Audit Ledger | /audit-ledger | Audit events |
| Config Admin | /config-admin | Config management |
| System Health | /system-health | All services health |

---

## 16. Runtime Health Checklist

Run these commands to verify system health:

```bash
# Check all V2 services
systemctl --user list-units 'ai-bot-v2-*' --no-legend | grep -v 'running'

# Check failed services
systemctl --user --failed --no-legend | grep 'ai-bot'

# Check core service heartbeats (should all have TTL > 0)
redis-cli --no-auth-warning ttl v2:paper:heartbeat
redis-cli --no-auth-warning ttl v2:trainer:hybrid_cuda:heartbeat
redis-cli --no-auth-warning ttl v2:risk:gateway:heartbeat
redis-cli --no-auth-warning ttl v2:orchestrator:heartbeat
redis-cli --no-auth-warning ttl v2:features:pipeline:heartbeat

# Verify live gate is blocked (MUST show blocked_human_only)
redis-cli --no-auth-warning get v2:live_gate:state | python3 -c "import sys,json; d=json.load(sys.stdin); print('live_gate:', d['live_gate']); print('places_real_order:', d['places_real_order'])"

# Check paper trader is sole owner (forbidden_entry_process_count must be 0)
redis-cli --no-auth-warning get v2:paper:active_runtime_owner_status | python3 -c "import sys,json; d=json.load(sys.stdin); print('status:', d.get('status','')); print('forbidden_entry_process_count:', d.get('forbidden_entry_process_count',99))"

# Check website is serving
curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health
```

Expected outputs:
- All services: `active running`
- TTLs: all > 0 (fresh heartbeats)
- live_gate: `blocked_human_only` (ALWAYS)
- places_real_order: `false` (ALWAYS)
- forbidden_entry_process_count: `0`
- Health check: `200`

---

## 17. Daily Startup Checklist

```bash
# 1. Verify all V2 services are running
systemctl --user list-units 'ai-bot-v2-*' | grep -c 'running'
# Expected: ~53

# 2. Check no failed services
systemctl --user --failed | grep 'ai-bot'
# Expected: only ai-bot-v2-autonomous-no-manual-next-task-policy (known/acceptable)

# 3. Verify live gate blocked
redis-cli --no-auth-warning get v2:live_gate:state | python3 -m json.tool | grep live_gate
# Expected: "live_gate": "blocked_human_only"

# 4. Verify feature pipeline heartbeat is fresh
redis-cli --no-auth-warning ttl v2:features:pipeline:heartbeat
# Expected: 200-400 (seconds remaining; pipeline is writing every few minutes)

# 5. Verify trainer heartbeat is fresh
redis-cli --no-auth-warning ttl v2:trainer:hybrid_cuda:heartbeat
# Expected: 100-300

# 6. Check paper trader status
redis-cli --no-auth-warning get v2:paper:heartbeat | python3 -c "import sys,json; d=json.load(sys.stdin); print('cycle_state:', d.get('cycle_state','')); print('paper_only:', d.get('paper_only','')); print('places_real_order:', d.get('places_real_order',''))"
# Expected: cycle_state=RUNNING_CYCLE, paper_only=true, places_real_order=false

# 7. Check website is responding
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool
```

---

## 18. Daily Shutdown Checklist

```bash
# Safe V2 services can be stopped individually
systemctl --user stop ai-bot-v2-{service-name}.service

# NEVER stop the legacy trader
# NEVER stop the legacy trainer  
# NEVER restart legacy processes

# Log paper PnL before shutdown
redis-cli --no-auth-warning get v2:paper:ledger | python3 -c "import sys,json; d=json.load(sys.stdin); print('realized_pnl:', d.get('realized_pnl_usd',0)); print('closed_trades:', d.get('closed_trade_count',0))"
```

---

## 19. Every Systemd Service and What It Does

| Service Name | Purpose | Critical? |
|-------------|---------|-----------|
| ai-bot-v2-public-website-backend.service | FastAPI/uvicorn website server | YES |
| ai-bot-v2-trade-management-paper-loop.service | Primary paper trader | YES |
| ai-bot-v2-risk-gateway-live-loop.service | Risk gateway | YES |
| ai-bot-v2-binance-kline-wss-loop.service | Binance kline data | YES |
| ai-bot-v2-feature-pipeline-native-loop.service | Feature computation | YES |
| ai-bot-v2-full-talib-ta-loop.service | TA indicators | YES |
| ai-bot-v2-liquidation-wss-paper-shadow.service | Liquidation events | YES |
| ai-bot-v2-liquidation-levels-engine.service | Liquidation levels | YES |
| ai-bot-v2-coinapi-wsds-loop.service | CoinAPI WSDS | NO (fallback) |
| ai-bot-v2-coinapi-rest-fallback-loop.service | CoinAPI REST | NO (fallback) |
| ai-bot-v2-kucoin-public-rest-loop.service | KuCoin price data | NO (enrichment) |
| ai-bot-v2-coinank-live-direct.service | CoinAnk live data | NO (enrichment) |
| ai-bot-v2-coinank-global-aggregator-direct.service | CoinAnk global | NO (enrichment) |
| ai-bot-v2-coinank-direct-status-publisher.service | CoinAnk status | NO |
| ai-bot-v2-lunarcrush-altdata-loop.service | LunarCrush social | NO (enrichment) |
| ai-bot-v2-nansen-altdata-loop.service | Nansen on-chain | NO (enrichment) |
| ai-bot-v2-public-intel-free-tier-loop.service | Fear/greed etc. | NO (enrichment) |
| ai-bot-v2-aicoin-whale-intel-loop.service | AICoin whale walls | NO (cred blocked) |
| ai-bot-v2-arkham-presence-loop.service | Arkham presence | NO |
| ai-bot-v2-dynamic-symbol-discovery-loop.service | Symbol discovery | NO |
| ai-bot-v2-alt-data-symbol-scoring-loop.service | Alt data scoring | NO |
| ai-bot-v2-alt-data-candidate-publisher-loop.service | Alt data publisher | NO |
| ai-bot-v2-feature-snapshot-builder.service | Feature snapshots | YES |
| ai-bot-v2-all-timeframe-prediction-signal-price-target-publisher.service | Prediction publisher | YES |
| ai-bot-v2-market-chart-payload-publisher.service | Chart payloads | NO |
| ai-bot-v2-professional-market-chart-payload-publisher.service | Pro chart payloads | NO |
| ai-bot-v2-rl-core-inference-loop.service | RL sidecar (advisory) | NO |
| ai-bot-v2-ingestors-status-publisher.service | Ingestor status | NO |
| ai-bot-v2-log-errors-status-publisher.service | Log errors status | NO |
| ai-bot-v2-technical-analysis-status-publisher.service | TA status | NO |
| ai-bot-v2-liquidation-runtime-status-publisher.service | Liq status | NO |
| ai-bot-v2-trainer-checkpoint-evidence.service | Checkpoint evidence | NO |
| ai-bot-v2-symbol-universe-publisher.service | Symbol universe | NO |
| ai-bot-v2-continuous-edge-guardian.service | A-grade execution gate | YES |
| ai-bot-v2-memory-watchdog.service | Memory alerts | NO |
| ai-bot-v2-codex-watchdog.service | Codex watchdog | NO |
| ai-bot-v2-agent-supervisor.service | Agent supervisor | NO |
| ai-bot-v2-closed-loop-claude-worker@{1,2,3}.service | Claude workers | NO |
| ai-bot-v2-closed-loop-codex-worker@{1,2,3}.service | Codex workers | NO |

---

## 20. How to Restart a Safe V2 Service

```bash
# Safe to restart: any non-critical ingestor or publisher
systemctl --user restart ai-bot-v2-kucoin-public-rest-loop.service

# Expected output after restart:
systemctl --user status ai-bot-v2-kucoin-public-rest-loop.service
# Should show: Active: active (running)

# Verify Redis key is updated after restart:
redis-cli --no-auth-warning ttl v2:features:kucoin:BTCUSDT:1h
# Should show positive TTL (key being written)
```

---

## 21. What Never to Restart

**NEVER restart:**
- `../AI BOT/**` — legacy trader/trainer processes
- Any legacy Redis consumer
- Any live exchange connection (v2_binance_live_order_transport_*) while positions are open
- `ai-bot-v2-trade-management-paper-loop.service` while positions are open (will lose position state)

**NEVER:**
- Run `redis-cli FLUSHDB` or `redis-cli FLUSHALL`
- Delete `v2:paper:*` keys
- Modify the live gate state without following the full operator checklist
- Set `order_transport_submit_enabled: true` without full sign-off

---

## 22. How to Verify Ingestors

```bash
# Check feature pipeline heartbeat age
redis-cli --no-auth-warning ttl v2:features:pipeline:heartbeat
# Expected: 100-400 seconds (fresh)

# Check a specific feature key
redis-cli --no-auth-warning ttl "v2:features:latest:BTCUSDT:1h"
# Expected: positive TTL

# Check ingestor status payload
redis-cli --no-auth-warning get v2:market:coinapi:rest:heartbeat | python3 -m json.tool | head -10
# Expected: finished_utc within last 60 minutes

# Check CoinAnk status
redis-cli --no-auth-warning get v2:altdata:aicoin:status | python3 -m json.tool | head -10
# Expected: credential_presence shows false (AICoin credentials not set)

# Check liquidation levels
redis-cli --no-auth-warning ttl v2:liq:levels:BTCUSDT
# Expected: positive TTL (levels are computed and fresh)
```

---

## 23. How to Verify Trainer

```bash
# Check trainer heartbeat
redis-cli --no-auth-warning ttl v2:trainer:hybrid_cuda:heartbeat
# Expected: 100-300 seconds remaining

# Read trainer heartbeat
redis-cli --no-auth-warning get v2:trainer:hybrid_cuda:heartbeat | python3 -c "import sys,json; d=json.load(sys.stdin); print('live_gate:', d.get('live_gate','')); print('trainer_source:', d.get('trainer_source',''))"
# Expected: live_gate=blocked_human_only, trainer_source=V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW

# Verify checkpoint is loadable
redis-cli --no-auth-warning get v2:trainer:checkpoint:evidence | python3 -c "import sys,json; d=json.load(sys.stdin); print('checkpoint_id:', d.get('selected_checkpoint_id','')); print('inventory_status:', d.get('inventory_status',''))"

# Check predictions are fresh
redis-cli --no-auth-warning ttl v2:prediction:BTCUSDT:1h
# Expected: positive TTL (< 600 seconds old)
```

---

## 24. How to Verify Paper Trading

```bash
# Check paper trader heartbeat
redis-cli --no-auth-warning ttl v2:paper:heartbeat
# Expected: 3000-3600 seconds (1-hour TTL)

# Read paper ledger
redis-cli --no-auth-warning get v2:paper:ledger | python3 -c "import sys,json; d=json.load(sys.stdin); print('closed_trade_count:', d.get('closed_trade_count',0)); print('realized_pnl:', d.get('realized_pnl_usd',0)); print('feedback_consumable:', d.get('trainer_feedback_consumable_row_count',0))"
# Current: closed=743, realized_pnl=-253.49, feedback_consumable=0 (CRITICAL)

# Verify paper is sole owner
redis-cli --no-auth-warning get v2:paper:active_runtime_owner_status | python3 -c "import sys,json; d=json.load(sys.stdin); print('status:', d.get('status','')); print('forbidden_count:', d.get('forbidden_entry_process_count',99))"
# Expected: status=PASS_ACTIVE_RUNTIME_OWNER_VALIDATION, forbidden_count=0
```

---

## 25. How to Verify Live Is Blocked

```bash
# ALWAYS run this first — verify live is blocked
redis-cli --no-auth-warning get v2:live_gate:state | python3 -c "import sys,json; d=json.load(sys.stdin); print('=== LIVE GATE VERIFICATION ==='); print('live_gate:', d['live_gate']); print('places_real_order:', d['places_real_order']); print('order_transport_submit_enabled:', d['order_transport_submit_enabled']); print('live_trading_enabled:', d['live_trading_enabled'])"
# Expected ALL of:
# live_gate: blocked_human_only
# places_real_order: False
# order_transport_submit_enabled: False
# live_trading_enabled: False

# Verify paper heartbeat also says no live
redis-cli --no-auth-warning get v2:paper:heartbeat | python3 -c "import sys,json; d=json.load(sys.stdin); print('routes_to_live:', d.get('routes_to_live',True)); print('places_real_order:', d.get('places_real_order',True))"
# Expected: routes_to_live=False, places_real_order=False
```

---

## 26. How to Verify No Real Orders

```bash
# Check exchange mutation freeze
redis-cli --no-auth-warning get v2:exchange:mutation_freeze 2>/dev/null

# Check risk gateway — no exchange action taken
redis-cli --no-auth-warning get v2:risk:gateway:heartbeat | python3 -c "import sys,json; d=json.load(sys.stdin); print('exchange_action_taken:', d.get('exchange_action_taken','?'))"
# Expected: exchange_action_taken: False

# Check paper heartbeat
redis-cli --no-auth-warning get v2:paper:heartbeat | python3 -c "import sys,json; d=json.load(sys.stdin); print('places_real_order:', d.get('places_real_order','?'))"
# Expected: places_real_order: false
```

---

## 27. How to Interpret GO/NO-GO Artifacts

The GO/NO-GO file is at: `docs/system_audit_2026_master/GO_NO_GO.md`

- `V2_REBUILD_MASTER_END_TO_END_SYSTEM_AUDIT_AND_OPERATOR_MANUAL_READY` = documentation complete
- `V2_REBUILD_MASTER_END_TO_END_SYSTEM_AUDIT_AND_OPERATOR_MANUAL_BLOCKED` = gaps remain

The **LIVE READINESS** marker is separate from the audit marker. Even if audit is READY, live trading requires its own separate gate passage.

---

## 28. How to Run Backend Tests

```bash
cd "/home/wali/Desktop/AI BOT REBUILD/v2/backend"

# Run all tests
source .venv/bin/activate
python -m pytest tests/ -v --timeout=60 2>&1 | tail -30

# Run specific subsystem
python -m pytest tests/unit/composition/ -v
python -m pytest tests/integration/cli/test_v2_trade_management_paper_loop.py -v
python -m pytest tests/contract/ -v

# Expected: ~3,493 passing (from 2026-06-27 baseline)
```

---

## 29. How to Run Frontend Tests

```bash
cd "/home/wali/Desktop/AI BOT REBUILD/v2/frontend"

# Type check
npm run typecheck

# Build check
npm run build

# Playwright E2E (requires running backend)
npx playwright test
# 48 spec files

# If backend is not running, start it first:
systemctl --user status ai-bot-v2-public-website-backend.service
```

---

## 30. How to Run Route Crawls

```bash
cd "/home/wali/Desktop/AI BOT REBUILD/v2/backend"
source .venv/bin/activate

# API route inventory
python -c "from app.main import create_app; app = create_app(); [print(r.path) for r in app.routes]"

# Or use the e2e verification
python app/cli/run_e2e_verification.py
```

---

## 31. How to Inspect Logs

```bash
# Paper trader logs
journalctl --user -u ai-bot-v2-trade-management-paper-loop.service -n 50 --no-pager

# Risk gateway logs
journalctl --user -u ai-bot-v2-risk-gateway-live-loop.service -n 50 --no-pager

# Trainer logs
journalctl --user -u ai-bot-v2-trainer-training-loop.service -n 50 --no-pager 2>/dev/null || \
journalctl --user | grep 'trainer' | tail -50

# Website backend logs
journalctl --user -u ai-bot-v2-public-website-backend.service -n 50 --no-pager

# All V2 errors
journalctl --user | grep -E 'ai-bot-v2.*ERROR|ai-bot-v2.*CRITICAL' | tail -50
```

---

## 32. How to Troubleshoot Stale Predictions

```bash
# Check prediction TTL
redis-cli --no-auth-warning ttl v2:prediction:BTCUSDT:1h
# If 0 or negative: prediction expired; trainer may have stopped

# Check trainer heartbeat
redis-cli --no-auth-warning ttl v2:trainer:hybrid_cuda:heartbeat
# If 0: trainer stopped; check logs

# Check feature pipeline
redis-cli --no-auth-warning ttl v2:features:pipeline:heartbeat
# If 0: feature pipeline stopped; trainer has no input data

# If feature pipeline stopped:
systemctl --user restart ai-bot-v2-feature-pipeline-native-loop.service
# Wait 2-3 minutes for heartbeat to refresh
```

---

## 33. How to Troubleshoot Stale Ingestors

```bash
# Check if Binance kline data is arriving
redis-cli --no-auth-warning ttl "v2:features:latest:BTCUSDT:1m"
# Should be < 120 seconds (1m candle every 60s)

# If stale:
journalctl --user -u ai-bot-v2-binance-kline-wss-loop.service -n 20 --no-pager
# Look for connection errors / reconnecting

# Restart Binance kline ingestor (safe to restart if no positions being filled)
systemctl --user restart ai-bot-v2-binance-kline-wss-loop.service

# Verify restart worked (wait 30s then check)
redis-cli --no-auth-warning ttl "v2:features:latest:BTCUSDT:1m"
```

---

## 34. How to Troubleshoot Trainer Not Learning

```bash
# Check trainer feedback quarantine (CRITICAL CURRENT ISSUE)
redis-cli --no-auth-warning get v2:paper:ledger | python3 -c "import sys,json; d=json.load(sys.stdin); print('consumable:', d.get('trainer_feedback_consumable_row_count',0)); print('quarantined:', d.get('trainer_feedback_quarantined_row_count',0))"
# If consumable=0 and quarantined>0: feedback loop is broken

# Check feedback key
redis-cli --no-auth-warning type v2:trainer:feedback:outcomes
redis-cli --no-auth-warning get v2:trainer:feedback:outcomes | python3 -m json.tool | head -20

# Look for quarantine reasons in logs
journalctl --user | grep -i 'quarantine\|feedback' | tail -20
```

---

## 35. How to Troubleshoot Paper PnL Mismatch

```bash
# Read full paper ledger
redis-cli --no-auth-warning get v2:paper:ledger | python3 -m json.tool | head -60

# Sample recent closed trade
redis-cli --no-auth-warning get v2:paper:closed_trades | python3 -c "import sys,json; d=json.load(sys.stdin); trades=d if isinstance(d,list) else []; print('count:', len(trades)); print(json.dumps(trades[0] if trades else {}, indent=2))"

# Check paper reconciliation timer
journalctl --user | grep 'equity_reconciliation\|paper_fill_position' | tail -20
```

---

## 36. How to Troubleshoot Website Stale Data

```bash
# Check if website backend is running
systemctl --user status ai-bot-v2-public-website-backend.service

# Check if API responds
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool

# Check static payload files
ls -la "/home/wali/Desktop/AI BOT REBUILD/v2/frontend/public/operator_runtime/" | head -10

# Check prediction publisher is running
systemctl --user status ai-bot-v2-all-timeframe-prediction-signal-price-target-publisher.service

# If payloads are stale, restart publisher
systemctl --user restart ai-bot-v2-all-timeframe-prediction-signal-price-target-publisher.service
```

---

## 37. How to Rotate/Restart Observers Safely

```bash
# Observers (read-only monitoring scripts) are safe to restart anytime
systemctl --user restart ai-bot-v2-readonly-decision-observatory.service
systemctl --user restart ai-bot-v2-ingestors-status-publisher.service
systemctl --user restart ai-bot-v2-log-errors-status-publisher.service
systemctl --user restart ai-bot-v2-technical-analysis-status-publisher.service

# Verify they come back up
systemctl --user status ai-bot-v2-ingestors-status-publisher.service
```

---

## 38. How to Add a New Symbol Safely

```bash
# 1. Check if symbol is in discovery universe
redis-cli --no-auth-warning get v2:altdata:symbol_score:NEWUSDT

# 2. Add symbol to config (versioned config via config-admin API)
# Use /config-admin page in website

# 3. Binance kline WSS auto-subscribes to new symbols from universe
# Feature pipeline auto-includes new symbols from universe

# 4. Wait 2-3 minutes for first features to appear
redis-cli --no-auth-warning ttl "v2:features:latest:NEWUSDT:1m"

# 5. Verify prediction is generated within 5 minutes
redis-cli --no-auth-warning ttl "v2:prediction:NEWUSDT:1m"

# SAFETY: Do not add symbols with very low liquidity or untested markets
```

---

## 39. How to Add a New Ingestor Safely

1. Write ingestor script following the V2 namespace convention (`v2:` prefix on all keys)
2. Place in `v2/backend/app/cli/`
3. Write corresponding unit test in `v2/backend/tests/`
4. Write systemd service file in `~/.config/systemd/user/`
5. Add to `file_inventory_backend.json` and `script_catalog.md`
6. Verify: `systemctl --user enable --now ai-bot-v2-{service}.service`
7. Verify no legacy Redis keys are written: `redis-cli keys "old_*" | grep -c .`

---

## 40. Emergency Stop / Incident Response

### If Real Orders Are Placed (CRITICAL)
```bash
# 1. Kill switch (if live canary is running)
python3 v2/backend/app/cli/v2_live_canary_kill_switch.py

# 2. Disarm submit
python3 v2/backend/app/cli/v2_live_submit_disarm.py

# 3. Stop paper loop
systemctl --user stop ai-bot-v2-trade-management-paper-loop.service

# 4. Verify no more orders can be placed
redis-cli --no-auth-warning get v2:live_gate:state | python3 -c "import sys,json; d=json.load(sys.stdin); print('submit_enabled:', d.get('order_transport_submit_enabled',True))"
# Must show: False
```

### If Feature Pipeline Dies
```bash
systemctl --user restart ai-bot-v2-binance-kline-wss-loop.service
systemctl --user restart ai-bot-v2-feature-pipeline-native-loop.service
systemctl --user restart ai-bot-v2-full-talib-ta-loop.service
# Wait 3 minutes, then verify
redis-cli --no-auth-warning ttl v2:features:pipeline:heartbeat
```

### If Trainer Dies
```bash
journalctl --user -u ai-bot-v2-trainer-training-loop.service -n 50 --no-pager
# Check for OOM or CUDA errors
# Restart only if no CUDA OOM
systemctl --user restart ai-bot-v2-trainer-training-loop.service 2>/dev/null
# Or restart via the correct service name
```

---

## 41. Live-Readiness Checklist

**DO NOT check this until paper trading demonstrates positive edge.**

Current status: **NOT READY**

Blockers:
- [ ] Trainer feedback loop is 100% quarantined (P0)
- [ ] Paper trading PnL is negative (-$253.49)
- [ ] Live gate state is intentionally stale
- [ ] Operator has not approved live enable
- [ ] No live symbols configured

Requirements before live enable:
- [ ] Trainer feedback consumable_row_count > 0
- [ ] Paper trading positive expectancy over 1,000+ trades
- [ ] Continuous edge guardian A-grade gate = PASS
- [ ] Full pre-live checklist completed
- [ ] Operator explicit approval

---

## 42. Known Current Blockers

| Blocker | Severity | Description |
|---------|---------|-------------|
| Trainer feedback 100% quarantined | P0 | 741/741 feedback rows quarantined; trainer not learning from paper outcomes |
| Paper PnL negative | P1 | -$253.49 realized; underlying model quality unknown |
| Risk deny_default blocks all paper | P1 | All signals denied; paper trader not generating new fills |
| AICoin credentials missing | P2 | 5 env vars absent; whale wall data unavailable |
| LunarCrush/Nansen credential status unknown | P2 | Social/on-chain features may be partial |
| Live gate state stale | P3 | Intentional; refreshed only on operator action |
| 1 failed service | P3 | ai-bot-v2-autonomous-no-manual-next-task-policy (non-critical) |

---

## 43. Glossary

| Term | Meaning |
|------|---------|
| PPO | Proximal Policy Optimization — RL algorithm |
| MASA | Multi-Agent State Abstraction — model architecture head |
| Feature snapshot | Immutable, hashed feature vector for one symbol/timeframe at one candle close |
| Lineage | Chain of hashes linking prediction → feature snapshot → tensor → candle timestamps |
| deny_default | Risk gateway response when live gate is blocked — all decisions denied |
| A-grade gate | Continuous edge guardian threshold — required before orchestrator routes signals |
| Paper fill gate | Rate/quality gate that can hold paper intents until quality threshold is met |
| Challenger v2 | The current paper policy ID (v2_cuda_exitless model) |
| decision_time | Timestamp when prediction was computed |
| available_at | Timestamp when prediction was available for trading (decision_time + latency) |
| feature_cutoff | Most recent candle timestamp used in prediction features |
| blocked_human_only | Live gate state meaning live trading is blocked until explicit human approval |
| V2 namespace | All Redis keys must use v2: prefix — never write legacy/old keys |
| Bridge exit | Completed migration from legacy trainer bridge to native V2 trainer |
| RL core sidecar | Advisory-only RL inference that does not route to paper or live |
| OOM | Out Of Memory — GPU memory exhaustion (currently 0 occurrences) |
| MFE/MAE | Maximum Favorable/Adverse Excursion — trade performance metrics |
| deny_default | Default deny for all signals when live gate is not enabled |
