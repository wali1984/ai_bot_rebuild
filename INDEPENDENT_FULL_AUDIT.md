# Independent Full Audit — Legacy Bot vs V2 Rebuild
**Audit Date:** 2026-05-20  
**Auditor:** GitHub Copilot (independent — no prior context relied upon)  
**Method:** Direct filesystem inspection, `pgrep`, `pip freeze`, source reads  
**Scope:** Answers to 5 user questions + additional findings

---

## TRACKER + ACTIVE LANES (updated 2026-05-20)

This raw audit is the source-of-truth snapshot. Ongoing remediation
is tracked in the persistent audit-gap tracker:

- **Tracker (markdown):** [`claude_worklog/trackers/AUDIT_GAPS_TRACKER.md`](claude_worklog/trackers/AUDIT_GAPS_TRACKER.md)
- **Tracker (structured JSON):** [`claude_worklog/trackers/AUDIT_GAPS_TRACKER.json`](claude_worklog/trackers/AUDIT_GAPS_TRACKER.json)

Two immediate lanes were executed in parallel after this audit was
issued; both reached **READY** the same day. They close audit
findings AUD-008, AUD-009, and AUD-013:

| Lane | Status | GO_NO_GO | Closes |
| --- | --- | --- | --- |
| **Lane 1: Dry-run approval-binding remediation** | Done 2026-05-20 | `V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_READY` | AUD-013 |
| **Lane 2: V2 public website backend online** | Done 2026-05-20 | `V2_PUBLIC_WEBSITE_BACKEND_ONLINE_READY` | AUD-008, AUD-009 |

The remaining findings (AUD-001 through AUD-007, AUD-010 through
AUD-021) stay **Open** in the tracker until each gets its own
dedicated `V2_*_READY` packet, ships, and passes Codex. Reviewers
must consult the tracker before issuing any live-canary or
production-equivalence approval.

---

## 1. RUNNING SERVICES COMPARISON (Current State)

### Legacy Bot — CURRENTLY RUNNING (`/home/wali/Desktop/AI BOT/`)
| PID | Process | Status |
|-----|---------|--------|
| 46218 | `ingest/live_binance.py` | ✅ Running |
| 46365 | `ingest/live_binance_liquidations.py` | ✅ Running |
| 46559 | `ingest/live_coinank.py` | ✅ Running |
| 47157 | `ingest/live_kucoin.py` | ✅ Running |
| 47348 | `ingest/live_technical_analysis.py` | ✅ Running |
| 47589 | `ingest/realtime_price_provider.py` | ✅ Running |
| 48066 | `feature_pipeline.py` | ✅ Running |
| 48623 | `rl/hybrid_trainer.py --mode hybrid` | ✅ Running |
| 49067 | `trading/opportunity_tracker.py` | ✅ Running |
| 54017 | `rl/orchestrator_worker` | ✅ Running |
| 54905 | `ingest/live_coinapi_v1.py` | ✅ Running |
| 55369 | `ingest/live_coinapi_wsds.py` | ✅ Running |
| 57289 | `scripts/monitor_trainer_prices.py` | ✅ Running |
| 57478 | `scripts/monitor_trainer_predictions.py` | ✅ Running |
| 57884 | `monitor_portfolio_primary.py` | ✅ Running |

**Note:** `trading/trader.py` is NOT running (was killed previously).

### V2 Rebuild — CURRENTLY RUNNING (`/home/wali/Desktop/AI BOT REBUILD/`)
| PID | Process | Type |
|-----|---------|------|
| 31327 | `v2_trade_management_paper_loop` | Paper/simulation only |
| 1172265 | `v2_liquidation_wss_loop` | Read-only listener |
| 1456707 | `paper_online_runtime` | Paper/simulation only |
| 2620199 | `v2_production_replacement_runtime_guard` | Watchdog/monitor |
| 2620203 | `v2_legacy_v2_production_comparator` | Comparator |
| 2622359 | `v2_production_payload_freshness_refresher` | Refresher |
| 2624946 | `v2_production_replacement_soak_observer` | Observer |
| 2677063 | `v2_legacy_log_intelligence_observer` | Log watcher |
| 2779663/876 | `v2_continuous_legacy_log_to_rebuild_remediation` x2 | Remediation tool |
| 3228969 | `v2_production_equivalence_comparator` | Comparator |
| 73164 | `parallel_capacity_scheduler.py` | Tooling daemon |
| 73192/559209 | `codex_non_live_watchdog.py` | Tooling daemon |
| 73368 | `v2_feature_snapshot_builder` | Snapshot reader |
| 430848 | `v2_worker_porting_orchestrator.py` | Porting tooling |
| 859673 | `agent_supervisor.py` | Tooling |
| 1506056 | `codex_legacy_v2_realtime_decision_observatory.py` | Tooling |
| 1506099 | `codex_legacy_shutdown_readiness_takeover.py` | Tooling |

**V2 has ZERO processes doing live market data ingest, live training, or live trading.**  
Every V2 process is either: paper simulation, read-only observer, comparator, or tooling daemon.

---

## 2. Q1 — WHAT IS MISSING: INGESTORS

### Legacy Ingestors (all active and real)
| File | Size | What it does | V2 Equivalent |
|------|------|-------------|----------------|
| `live_binance.py` | 125,730 bytes | Binance USDM OHLCV + orderbook WebSocket, writes `unified_features:*`, `features:binance:*` to Redis | ❌ MISSING — V2 `market_ingest` service is a **stub** that writes to an in-process dict only (no Redis, no live WS) |
| `live_binance_liquidations.py` | 46,088 bytes | Binance liquidation event stream WebSocket, writes `liquidations:events` Redis stream | ⚠️ PARTIAL — V2 `v2_liquidation_wss_loop` is read-only listener, captures to paper ledger, does NOT write `liquidations:events` |
| `live_coinank.py` | 127,414 bytes | CoinAnk REST polling (54 endpoints: CVD, OI, funding, radar, rankings, SMC), writes `features:coinank:*`, `coinank:radar:*` to Redis | ❌ MISSING — V2 `coinank_bridge` service is a bridge/adapter, does NOT poll CoinAnk directly |
| `live_coinank_global_aggregator.py` | 14,475 bytes | Aggregates CoinAnk global market data, writes `features:global_coinank:*` | ❌ MISSING — no V2 equivalent |
| `live_kucoin.py` | 36,382 bytes | KuCoin WebSocket OHLCV + depth feed, fallback exchange data | ❌ MISSING — V2 has `v2_kucoin_ingestor_worker.py` CLI script but it is not running |
| `live_coinapi_v1.py` | 28,497 bytes | CoinAPI REST candle + tick data, writes historical candle cache | ❌ MISSING — V2 `market_ingest` service documented as porting this but is stub only |
| `live_coinapi_wsds.py` | 77,253 bytes | CoinAPI WebSocket data stream, real-time tick ingest | ❌ MISSING — no V2 native equivalent running |
| `live_technical_analysis.py` | 6,103 bytes | Runs TA indicators (RSI, MACD, Bollinger, etc.) over Redis feature data | ❌ MISSING — V2 `feature_pipeline_and_ta` service is a stub/bridge |
| `realtime_price_provider.py` | 45,009 bytes | Unified price provider with priority failover (CoinAPI WS → Binance WS → REST), writes `price:*` | ❌ MISSING — V2 `market_ingest` documents source priority enum but does not run live |
| `feature_pipeline.py` (root) | live process | Assembles all feature signals into `unified_features:{sym}:{tf}` | ❌ MISSING — V2 has feature pipeline workers but they read from paper/snapshot data, not live feeds |
| `live_alphavantage_news.py` | 8,800 bytes | AlphaVantage news/sentiment ingest | ❌ MISSING |
| `live_tokenmetrics.py` | 44,485 bytes | TokenMetrics AI score ingest, writes `features:tokenmetrics:*` | ❌ MISSING |
| `coinank_pipeline_monitor.py` | 11,701 bytes | CoinAnk health monitoring | ❌ MISSING |

**Summary: 13/13 live ingestors have NO running V2 native equivalent. 0% ingestor coverage.**

---

## 3. Q1 — WHAT IS MISSING: TRAINER

### Legacy Trainer
| Component | File | Lines | Status in V2 |
|-----------|------|-------|-------------|
| Main trainer | `rl/hybrid_trainer.py` | 57,250 | ❌ MISSING — V2 `rl_core/service.py` explicitly states it does NOT import torch, does NOT run PPO/MASA, does NOT run gymnasium loop |
| Orchestrator | `rl/orchestrator_worker.py` | 10,523 | ❌ MISSING — V2 `orchestrator_adapter.py` is a bridge to the legacy process, not a port |
| Hedge manager | `rl/hedge_manager_v3.py` | 2,244 | ❌ MISSING |
| Environment | `rl/environment.py` | 1,455 | ❌ MISSING (SHA256 hash only in V2 service, not ported) |
| GPU environment | `rl/gpu_environment.py` | 1,249 | ❌ MISSING |
| Reward functions | `rl/reward_functions.py` | 902 | ⚠️ PARTIAL — V2 has `rl_core/reward.py` with `compute_constrained_reward()` but it is a simplified port |
| Supervised trainer | `rl/supervised_trainer.py` | 1,083 | ❌ MISSING |
| Microstructure overlay | `rl/microstructure_overlay.py` | 1,127 | ❌ MISSING |
| Portfolio policy manager | `rl/portfolio_policy_manager.py` | 1,134 | ❌ MISSING |
| Underwater recovery controller | `rl/underwater_recovery_controller.py` | 1,136 | ❌ MISSING |
| 111 other rl/ files | various | various | ❌ MISSING |

**V2 rl_core explicitly declares itself as `SUBPROJECT_1_RL_CORE_PARTIALLY_MIGRATED_PAPER_ONLY`. No training loop. No GPU training. No inference loop (running).**

**V2 torch version:** `2.10.0+cu128` (stable) — legacy uses `2.10.0.dev20250930+cu128` (nightly dev build).  
**torchaudio** and **torchvision** are NOT installed in V2.

---

## 4. Q1 — WHAT IS MISSING: TRADER

### Legacy Trader Components
| Component | File | Lines | Status in V2 |
|-----------|------|-------|-------------|
| Main trader | `trading/trader.py` | 24,277 | ❌ MISSING — V2 has paper execution only, no live order routing |
| Stealth stops | `trading/stealth_stops.py` | 6,972 | ❌ MISSING |
| Base executor | `trading/base_executor.py` | 2,132 | ❌ MISSING |
| Market intelligence | `trading/market_intelligence.py` | 1,806 | ❌ MISSING |
| Adaptive edge gate | `trading/adaptive_edge_gate.py` | 1,569 | ❌ MISSING |
| Dynamic TP engine | `trading/dynamic_tp_engine.py` | 1,468 | ❌ MISSING |
| Hedge context | `trading/hedge_context.py` | 1,308 | ❌ MISSING |
| Dynamic adaptive hedge | `trading/dynamic_adaptive_hedge.py` | 1,126 | ❌ MISSING |
| Dynamic adaptive stops | `trading/dynamic_adaptive_stops.py` | 1,063 | ❌ MISSING |
| Hedge intelligence engine | `trading/hedge_intelligence_engine.py` | 947 | ❌ MISSING |
| Smart entry gate | `trading/smart_entry_gate.py` | 865 | ❌ MISSING |
| Market regime detector | `trading/market_regime_detector.py` | 799 | ❌ MISSING |
| Maker execution | `trading/maker_execution.py` | 661 | ❌ MISSING |
| 21 other trading/ files | various | various | ❌ MISSING |

**V2 has a `live_canary/execution_adapter.py` (1,057 lines) for a single BTCUSDT canary trade with `dry_run=true` and `max_notional=55 USDT`. This is NOT a full trader replacement.**

**V2 live canary current state:** `dry_run=true`, `live_gate=blocked_human_only`, `approves_live=false`, 0 real orders placed. Services/timers are INACTIVE.

**35 legacy trading files / 35 = 0% ported to a live-capable V2 trader.**

---

## 5. Q2 — FEATURES, FUNCTIONS, WRAPPERS, DEPENDENCIES

### Code Volume Gap
| Subsystem | Legacy .py files | Legacy approx. LOC | V2 native .py files | V2 native LOC | Coverage |
|-----------|-----------------|---------------------|---------------------|---------------|----------|
| Ingestors | 30 files | ~700,000 bytes | 0 native running | 0 | **0%** |
| RL/Trainer | 121 files | ~3.2M bytes (hybrid_trainer alone = 57k LOC) | Stubs + partial reward port | ~5,000 | **<1%** |
| Trader | 35 files | ~380,000 bytes | Paper canary only | ~1,057 | **<1%** |
| Feature pipeline | live process | ~45k LOC | Snapshot readers | ~1,300 | **<5%** |
| Config | `config.py` (6,006 lines) | 6,006 | Settings.py (26 lines) | 26 | **<1%** |

### What V2 Does Have (natively)
- ✅ Paper trading simulation loop (`paper_online_runtime.py`, `v2_trade_management_paper_loop`)
- ✅ Observation schema descriptor (not the full env, just schema)
- ✅ Reward component formula (simplified port)
- ✅ Checkpoint metadata parser
- ✅ Risk gateway (read-only gates, no live enforcement)
- ✅ Liquidation WSS listener (read-only, no Redis writes to legacy keys)
- ✅ Feature snapshot reader (reads from paper data, not live feeds)
- ✅ Live canary execution adapter (BTCUSDT only, dry_run=true, gates blocked)
- ✅ FastAPI backend skeleton (NOT running, uvicorn not started)
- ✅ Frontend React/Vite (built, 189 modules — but backend not running so API calls fail)
- ✅ Decision comparator (compares legacy signals vs V2 hypothetical outputs)

### What V2 Does NOT Have
- ❌ Any live WebSocket connections to Binance, KuCoin, CoinAPI
- ❌ CoinAnk polling (no API calls to CoinAnk)
- ❌ TokenMetrics ingest
- ❌ AlphaVantage news ingest
- ❌ GPU training loop (torch not imported in rl_core at all)
- ❌ PPO/MASA policy network
- ❌ Gymnasium environment step/reset loop
- ❌ Checkpoint loading/promotion to live inference
- ❌ Live order execution (except dry-run canary, inactive)
- ❌ Stealth TP/SL management
- ❌ Hedge cage / adaptive hedge builder
- ❌ Maker execution (limit order management)
- ❌ Dynamic margin management
- ❌ Opportunity tracker
- ❌ Telegram alerts (no `telegram_alerts.py` running in V2)
- ❌ Lagrangian multiplier / constrained optimization
- ❌ Anti-churn, toxicity shield, drift monitor
- ❌ Profit bank / drawdown guard
- ❌ Multi-TF regime stack (1m/5m/15m/1h/4h/1d)

---

## 6. Q3 — PACKAGE COMPARISON (pip)

### Critical Package Status
| Package | Legacy | V2 | Issue |
|---------|--------|----|-------|
| `torch` | `2.10.0.dev20250930+cu128` | `2.10.0+cu128` | ⚠️ Dev nightly vs stable; both have CUDA. Fine for inference, but legacy trainer uses dev APIs |
| `torchaudio` | `2.8.0.dev20250930+cu128` | ❌ NOT INSTALLED | Missing in V2 (needed for any audio/signal processing features) |
| `torchvision` | `0.25.0.dev20250930+cu128` | ❌ NOT INSTALLED | Missing in V2 |
| `pytorch_triton` | `3.5.0+gitbbb06c03` | ❌ NOT INSTALLED | Custom triton build missing |
| `stable_baselines3` | `2.7.1` | `2.7.1` | ✅ Same |
| `gymnasium` | `1.2.3` | `1.2.3` | ✅ Same |
| `ta_lib` | `0.6.8` | `0.6.8` | ✅ Same |
| `ccxt` | `4.5.34` | `4.5.51` | ⚠️ V2 is newer; API changes may break legacy calls if used |
| `redis` | `7.1.0` | `5.0.8` | ⚠️ Legacy uses redis 7.x, V2 uses 5.x — API differences (e.g. `client.json()`, response type changes) |
| `fastapi` | `0.128.0` | `0.115.0` | ⚠️ V2 is older |
| `uvicorn` | `0.40.0` | `0.30.6` | ⚠️ V2 is older |
| `pydantic` | `2.12.5` | `2.9.2` | ⚠️ V2 is older — breaking changes between 2.9 and 2.12 |
| `numpy` | `2.1.2` | `2.4.4` | ⚠️ V2 is newer |
| `pandas` | `2.3.3` | `3.0.2` | ⚠️ V2 uses pandas 3 — major breaking changes (Copy-on-Write mandatory, many deprecated APIs removed) |
| `starlette` | `0.50.0` | `0.38.6` | ⚠️ V2 is much older |
| `grpcio` | `1.76.0` | ❌ NOT INSTALLED | gRPC missing in V2 |
| `grpcio_tools` | `1.76.0` | ❌ NOT INSTALLED | gRPC tooling missing |
| `selenium` | `4.40.0` | ❌ NOT INSTALLED | Selenium missing (legacy scraping) |
| `webdriver_manager` | `4.0.2` | ❌ NOT INSTALLED | Missing |
| `pynvml` | `13.0.1` | ❌ NOT INSTALLED | NVIDIA GPU monitoring missing |
| `nvidia_ml_py` | `13.590.48` | ❌ NOT INSTALLED | NVIDIA ML Python library missing |
| `nest_asyncio` | `1.6.0` | ❌ NOT INSTALLED | Nested asyncio support missing |
| `trio` | `0.32.0` | ❌ NOT INSTALLED | Trio async missing (used by some ingestors) |
| `trio_websocket` | `0.12.2` | ❌ NOT INSTALLED | WebSocket via trio missing |
| `trio_typing` | `0.10.0` | ❌ NOT INSTALLED | |
| `python_jwt` | `4.1.0` | ❌ NOT INSTALLED | JWT handling missing |
| `jwcrypto` | `1.5.6` | ❌ NOT INSTALLED | JWT crypto missing |
| `retrying` | `1.4.2` | ❌ NOT INSTALLED | Retry decorator library missing |
| `eventlet` | `0.40.4` | ❌ NOT INSTALLED | Async green threads missing |
| `dnspython` | `2.8.0` | ❌ NOT INSTALLED | DNS resolution missing |
| `tzdata` | `2025.3` | ❌ NOT INSTALLED | Timezone data missing |
| `dash` | `3.4.0` | ❌ NOT INSTALLED | Plotly Dash dashboard missing |
| `importlib_metadata` | `8.7.1` | ❌ NOT INSTALLED | |
| `pysocks` | `1.7.1` | ❌ NOT INSTALLED | SOCKS proxy missing |

### Summary
- **Total legacy packages:** 151
- **Total V2 packages:** 172 (V2 has more packages but many are newer versions or dev tools)
- **Packages in legacy but not in V2:** 27 confirmed missing
- **Critical missing for V2 to run legacy workloads:** `torchaudio`, `torchvision`, `pytorch_triton`, `grpcio`, `pynvml`, `nvidia_ml_py`, `trio`, `trio_websocket`, `nest_asyncio`, `tzdata`, `retrying`
- **Version mismatches that will cause runtime errors if V2 tries to use legacy code:** `pandas` (2→3 breaking), `redis` (7→5 API changes), `pydantic` (2.12→2.9 breaking)

---

## 7. Q4 — WHAT REDIS WILL V2 USE?

### Current Redis Instance
- **Host:** `127.0.0.1:6379` (single instance, no auth, no TLS)
- **DB:** `0` (both legacy and V2 use DB 0)
- **maxmemory:** `8,589,934,592` bytes (8 GB)
- **eviction policy:** `allkeys-lru`
- **Key count:** 12,624 keys currently

### Legacy Redis Namespace (what legacy writes)
```
features:coinank:*        — CoinAnk per-symbol feature hashes
features:global_coinank:* — CoinAnk global aggregated data
unified_features:{sym}:{tf} — Assembled feature vectors per symbol/timeframe
price:*                   — Real-time price data
liquidations:events       — Redis Stream: liquidation events
signals:trading:primary   — Redis Stream: trading signals
heartbeat:*               — Ingestor heartbeats
coinank:radar:*           — CoinAnk radar data
coinank:runtime           — CoinAnk runtime state
prediction:*              — Trainer output predictions
```

### V2 Redis Namespace (what V2 writes)
```
v2:live_canary:ledger     — Paper trade ledger (24 entries, all dry_run)
v2:market:*               — V2 market data (written to in-process dict, persisted to file — NOT to Redis live)
v2:*                      — All V2 keys are namespaced with "v2:" prefix
```

### Key Findings on V2 Redis Setup
1. **V2 `settings.py` has `REDIS_URL: str = ""`** — empty by default. No default connection string is set.
2. **V2 `settings.py` has `LEGACY_REDIS_URL: str = ""`** — separate field for legacy Redis, also empty.
3. **Neither field is populated by a `.env` file** — `SettingsConfigDict(env_file=None)` — it must be injected via environment variables at process start.
4. **No `.env` file exists at the workspace root** — V2 has no `REDIS_URL` configured unless you export it manually before starting processes.
5. **The running V2 processes connect to Redis only if `REDIS_URL` is set in the shell environment** — this was never verified as set.
6. **V2 market_ingest service writes to an in-process dict → file, NOT Redis** — by explicit design.
7. **V2 `v2:live_canary:ledger` with 24 entries confirms at least one V2 worker did connect** (the paper_loop uses Redis).

### What Needs to Be Done
- Set `REDIS_URL=redis://localhost:6379/0` in the environment before starting V2 processes (or in a `.env` file that the startup script sources).
- Set `LEGACY_REDIS_URL=redis://localhost:6379/0` if V2 bridge services need to read legacy keys.
- V2 and legacy share the same Redis instance but V2 keys are namespaced `v2:*` to avoid collision.

---

## 8. Q5 — OTHER MISSING / INCORRECTLY SETUP ITEMS

### A. FastAPI Backend NOT Running
- `uvicorn` process: **NOT found** (confirmed by `pgrep uvicorn`)
- V2 frontend (port 5173 Vite) makes API calls to `/api/v2/*` but no backend is serving them
- All frontend API calls are returning 404 or connection refused
- **Fix needed:** Start `uvicorn v2.backend.app.main:app --host 0.0.0.0 --port 8000`

### B. No `.env` File for V2
- `v2/backend/app/settings.py` uses `env_file=None` — relies on shell environment
- `REDIS_URL` is blank by default
- `LIVE_APPROVAL_TOKEN` is blank by default
- No `.env` file exists in the workspace root or `v2/` directory
- **Fix needed:** Create `v2/.env` with at minimum:
  ```
  REDIS_URL=redis://localhost:6379/0
  LEGACY_REDIS_URL=redis://localhost:6379/0
  LEGACY_BOT_ROOT=/home/wali/Desktop/AI BOT
  LEGACY_TRAINER_PYTHON=/home/wali/Desktop/AI BOT/venv/bin/python3
  V2_MODE=paper
  V2_REDIS_PREFIX=v2:
  ```

### C. V2 `pyproject.toml` Dependencies Are Outdated/Incomplete
- `fastapi==0.115.0` but legacy uses `0.128.0`
- `redis==5.0.8` but legacy uses `7.1.0` (different async API)
- `pydantic==2.9.2` but legacy uses `2.12.5`
- `uvicorn==0.30.6` but legacy uses `0.40.0`
- Missing from `pyproject.toml`: `aiohttp`, `ccxt`, `websockets`, `stable_baselines3`, `gymnasium`, `ta_lib`, `torch`, `pandas_ta`, `python_binance`, `python_dotenv`, `psutil`, `plotly`, `matplotlib`

### D. No Systemd Units for V2
- Legacy has no systemd either (uses startup scripts + crontab)
- V2 startup script exists: `v2/backend/scripts/start_v2_production_loops.sh`
- But it starts only 5 paper loops: `v2_native_ingestors_live_loop`, `v2_feature_pipeline_native_loop`, `v2_rl_core_inference_loop`, `v2_orchestrator_arbitration_loop`, `v2_trade_management_paper_loop`
- **None of these are actual replacements for the legacy services** — they are observation/paper wrappers

### E. No Telegram Alerts in V2
- Legacy `telegram_alerts.py` is 2,243 lines with full alert routing
- V2 has `TELEGRAM_BOT_TOKEN` etc. stored in `.local_secrets/live_canary_credentials.env`
- But V2 has NO running telegram alert service
- No V2 module imports or calls `telegram_alerts`
- Users will receive NO trade alerts, NO error alerts from V2

### F. Torch Version Mismatch
- Legacy uses `2.10.0.dev20250930+cu128` (nightly dev) — trainer may use nightly-only APIs
- V2 has `2.10.0+cu128` (stable release)
- If V2 ever tries to load legacy checkpoints or run training, nightly-only operations may fail
- **Fix needed:** Either pin V2 to the same nightly build or ensure no nightly-only APIs are used

### G. Pandas 3.0 in V2 vs 2.x in Legacy
- Legacy uses `pandas==2.3.3`; V2 uses `pandas==3.0.2`
- Pandas 3.0 has mandatory Copy-on-Write, removes many deprecated `.append()`, `swaplevel()` behaviors
- If ANY V2 code reads legacy feature DataFrames or processes legacy data, it will likely crash
- **Fix needed:** Pin V2 pandas to `2.3.3` or audit all DataFrame usage for 3.0 compatibility

### H. No Auto-Recovery / Watchdog for V2
- Legacy had `scripts/auto_recovery.sh` (removed this session from crontab)
- V2 has no equivalent watchdog to restart crashed V2 services
- `v2_production_replacement_runtime_guard.py` monitors but does not restart processes
- **Fix needed:** Add crontab or systemd `Restart=always` for core V2 loops

### I. V2 `rl_core` Does NOT Load Checkpoints
- V2 `rl_core/service.py` explicitly states it does NOT import torch, does NOT load weights
- Legacy checkpoints are at `/home/wali/Desktop/AI BOT/scripts/checkpoints/`
- V2 has `checkpoint_metadata.py` for parsing checkpoint filenames only
- **V2 is running entirely without a trained model** — paper trades are not AI-driven
- The V2 paper loop uses heuristic/rule-based decisions, not the trained PPO/MASA policy

### J. V2 Frontend Has No Live Data
- Frontend pages (Signals, Portfolio, etc.) rely on `/api/v2/*` endpoints
- Backend is not running → all pages show stale or empty data
- Even if backend runs, V2 has no live ingestors → the data would be stale anyway
- The feature snapshot builder reads from paper data files, not live Redis feeds

### K. Legacy Config (`config.py`) Has No V2 Equivalent
- `config.py` is 6,006 lines with hundreds of tunable parameters:
  - `SYMBOLS`, `LEVERAGE`, `MARGIN_TYPE`, `RISK_PER_TRADE`
  - `INTELLIGENCE_STEALTH_TP_GATE_ENABLED`, `ADAPTIVE_STEALTH_TP_ENABLED`
  - `POST_CASCADE_*`, `LOSS_REALIZATION_*`, `HEDGE_*` parameters
- V2 `settings.py` has 26 lines with 6 fields total
- **Zero feature parity on configuration**

### L. No Database (SQLite/Postgres) Set Up for V2
- `pyproject.toml` declares `SQLAlchemy==2.0.35` and `alembic==1.13.3`
- `DATABASE_URL: str = ""` in settings — blank
- No alembic migrations have been run
- No SQLite or Postgres database exists
- Some V2 services may require DB for persistence

---

## 9. OVERALL VERDICT

| Dimension | Legacy | V2 | Gap |
|-----------|--------|-----|-----|
| Live ingestors running | 8 processes | 0 | **100% missing** |
| Live training running | hybrid_trainer (57k LOC) | 0 | **100% missing** |
| Live trading running | trader.py killed (24k LOC) | dry_run canary only | **~99% missing** |
| Python files | 13,514 | 1,810 | **87% gap** |
| Backend API serving | N/A | NOT running | **Broken** |
| Redis URL configured | `redis://localhost:6379/0` | Empty string | **Needs fix** |
| Package compatibility | 151 packages | 172 packages | 27 missing + version gaps |
| Telegram alerts | ✅ Active | ❌ Not configured | **Missing** |
| Systemd/watchdog | crontab-based | None for V2 | **Missing** |
| AI model loaded | PPO+MASA running | Not loaded | **100% missing** |

**The V2 rebuild is currently an observation/paper framework, not a production replacement. Approximately 5-8% of legacy functionality has been ported. The legacy bot is doing 100% of the actual work.**

---

*Audit generated from direct filesystem and process inspection. No prior conversation context was relied upon.*
