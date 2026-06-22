# Safe Rebuild Go-Live Start Report - 2026-06-03

Generated UTC: 2026-06-04T00:55:14Z

## Verdict

SAFE rebuild runtime is started for real-time market data, features, trainer inference/training, orchestrator, risk controller, paper trade management, observers, and website backend.

This is not live exchange execution. `live_gate=blocked_human_only`, `live_symbols=[]`, canary is inactive, and trader/exchange mutation remains disabled.

## Start Result

- Safe units started or already active: 37
- Running `ai-bot-v2*` services after start: 40
- Failed user services: 0
- Old `/home/wali/Desktop/AI BOT/` legacy root processes: 0
- Canary/live-path service: inactive

## Core Heartbeats

- Trainer inference: `V2_NATIVE_RL_CORE_PRODUCTION_INFERENCE_OK`, predictions=27, trader_execution_enabled=False, writes_legacy_redis=False
- Trainer training: `V2_TRAINER_TRAINING_LIVE_OK`, rows=19562, train_rows=285, validation_rows=78, trader_execution_enabled=False, exchange_action_taken=False
- Orchestrator: `V2_ORCHESTRATOR_PRODUCTION_OK`, predictions_seen=52, proposals_arbitrated=2
- Risk gateway: `V2_RISK_GATEWAY_LIVE_OK`, decisions=2, latest=allow/allow_proceed_long, places_real_order=False, exchange_action_taken=False
- Paper signals: 2

## Redis Evidence

| Pattern | Total | Fresh TTL>0 | No TTL |
|---|---:|---:|---:|
| `v2:market:prices:*` | 27 | 27 | 0 |
| `v2:market:ohlcv:*` | 48 | 17 | 31 |
| `v2:market:orderbook:*` | 37 | 25 | 12 |
| `v2:features:latest:*` | 38 | 27 | 11 |
| `v2:features:kucoin:*` | 117 | 117 | 0 |
| `v2:market:kucoin:*` | 109 | 109 | 0 |
| `v2:latest:coinapi:ohlcv:*` | 6 | 6 | 0 |
| `v2:normalized:ohlcv:*` | 6 | 6 | 0 |
| `v2:market:coinapi:rest:*` | 53 | 53 | 0 |
| `v2:features:coinapi_rest:*` | 25 | 25 | 0 |
| `v2:coinank:global:*` | 12 | 12 | 0 |
| `v2:features:global_coinank:*` | 11 | 11 | 0 |
| `v2:liquidations:*` | 1 | 0 | 1 |
| `v2:prediction:*` | 52 | 27 | 25 |
| `v2:trainer:*` | 8 | 6 | 2 |
| `v2:orchestrator:*` | 3 | 3 | 0 |
| `v2:risk:gateway:*` | 3 | 3 | 0 |
| `v2:signals:paper` | 1 | 1 | 0 |

## BTC / ETH / SOL Check

| Symbol | Feature TTL | Feature count | Real | Missing | Freshness | Prediction TTL | Trainer source | Gate | Trader enabled |
|---|---:|---:|---:|---:|---|---:|---|---|---|
| `BTCUSDT` | 575 | 25 | 25 | 0 | `CURRENT` | 545 | `V2_NATIVE_RL_CORE` | `TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN` | False |
| `ETHUSDT` | 575 | 25 | 25 | 0 | `CURRENT` | 545 | `V2_NATIVE_RL_CORE` | `TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN` | False |
| `SOLUSDT` | 575 | 25 | 25 | 0 | `CURRENT` | 545 | `V2_NATIVE_RL_CORE` | `BLOCKED_BY_TRAINER_OUTPUT_MALFORMED` | False |

## Services Running

- `ai-bot-v2-agent-supervisor.service                     loaded active running AI Bot V2 agent supervisor`
- `ai-bot-v2-closed-loop-claude-worker@1.service          loaded active running AI BOT V2 Closed-Loop Persistent Claude Worker (1)`
- `ai-bot-v2-closed-loop-claude-worker@2.service          loaded active running AI BOT V2 Closed-Loop Persistent Claude Worker (2)`
- `ai-bot-v2-closed-loop-claude-worker@3.service          loaded active running AI BOT V2 Closed-Loop Persistent Claude Worker (3)`
- `ai-bot-v2-closed-loop-codex-worker@1.service           loaded active running AI BOT V2 Closed-Loop Persistent Codex Worker (1)`
- `ai-bot-v2-closed-loop-codex-worker@2.service           loaded active running AI BOT V2 Closed-Loop Persistent Codex Worker (2)`
- `ai-bot-v2-closed-loop-codex-worker@3.service           loaded active running AI BOT V2 Closed-Loop Persistent Codex Worker (3)`
- `ai-bot-v2-codex-shutdown-readiness-takeover.service    loaded active running AI Bot V2 Codex shutdown-readiness takeover`
- `ai-bot-v2-codex-watchdog.service                       loaded active running AI Bot V2 Codex non-live watchdog`
- `ai-bot-v2-coinank-global-bridge-loop.service           loaded active running AI BOT V2 CoinAnk global bridge loop (paper-only, V2 namespace only)`
- `ai-bot-v2-coinapi-rest-fallback-loop.service           loaded active running AI BOT V2 CoinAPI REST fallback loop (paper-only, V2 namespace only)`
- `ai-bot-v2-continuous-legacy-log-remediation.service    loaded active running AI BOT V2 continuous legacy-log -> rebuild remediation loop (read-only)`
- `ai-bot-v2-feature-pipeline-native-loop.service         loaded active running AI BOT V2 feature pipeline native loop (paper-only)`
- `ai-bot-v2-feature-snapshot-builder.service             loaded active running AI Bot V2 feature snapshot builder`
- `ai-bot-v2-kucoin-public-rest-loop.service              loaded active running AI BOT V2 KuCoin public REST loop (paper-only, V2 namespace only)`
- `ai-bot-v2-legacy-coinapi-v1-ingestor.service           loaded active running AI BOT V2 legacy CoinAPI v1 WSS ingestor (legacy reuse via v2: prefix proxy, paper/shadow, V2 namespace only)`
- `ai-bot-v2-legacy-kucoin-ingestor.service               loaded active running AI BOT V2 legacy KuCoin ingestor (legacy reuse via v2: prefix proxy, paper/shadow, V2 namespace only)`
- `ai-bot-v2-legacy-log-intelligence-observer.service     loaded active running AI BOT V2 legacy log intelligence observer (read-only)`
- `ai-bot-v2-legacy-v2-production-comparator.service      loaded active running AI BOT V2 legacy vs V2 production comparator (read-only)`
- `ai-bot-v2-liquidation-bridge.service                   loaded active running AI BOT V2 copied liquidation bridge (paper-only, V2 Redis namespace)`
- `ai-bot-v2-liquidation-levels-engine.service            loaded active running AI BOT V2 copied liquidation levels engine (paper-only, V2 Redis namespace)`
- `ai-bot-v2-liquidation-wss-paper-shadow.service         loaded active running AI BOT V2 liquidation WSS client (paper/shadow only; public Binance Futures forceOrder stream)`
- `ai-bot-v2-native-ingestors-live-loop.service           loaded active running AI BOT V2 native ingestors live loop (paper-only)`
- `ai-bot-v2-orchestrator-arbitration-loop.service        loaded active running AI BOT V2 orchestrator arbitration loop (paper-only)`
- `ai-bot-v2-paper-online-runtime.service                 loaded active running AI Bot V2 paper online runtime`
- `ai-bot-v2-paper-shadow-observation.service             loaded active running AI Bot V2 paper shadow observation publisher`
- `ai-bot-v2-parallel-scheduler.service                   loaded active running AI Bot V2 parallel capacity scheduler`
- `ai-bot-v2-parallel-spark-automation.service            loaded active running AI Bot V2 parallel Spark automation runner`
- `ai-bot-v2-position-history-persistent-tracker.service  loaded active running AI BOT V2 paper position-history persistent tracker (paper/shadow only; V2-only Redis writes)`
- `ai-bot-v2-production-replacement-runtime-guard.service loaded active running AI BOT V2 production replacement runtime guard`
- `ai-bot-v2-public-website-backend.service               loaded active running AI BOT V2 public website backend (uvicorn + FastAPI; read-only payload server; NEVER enables live trading; LIVE_GATE=blocked_human_only)`
- `ai-bot-v2-readonly-decision-observatory.service        loaded active running AI Bot V2 read-only realtime decision observatory`
- `ai-bot-v2-risk-gateway-live-loop.service               loaded active running AI BOT V2 risk gateway live loop (controller only, no trader/exchange mutation)`
- `ai-bot-v2-rl-core-inference-loop.service               loaded active running AI BOT V2 RL core inference loop (paper-only)`
- `ai-bot-v2-symbol-universe-publisher.service            loaded active running AI Bot V2 symbol universe public payload publisher`
- `ai-bot-v2-trade-management-paper-loop.service          loaded active running AI BOT V2 trade management paper loop (paper-only, no exchange mutation)`
- `ai-bot-v2-trainer-bridge.service                       loaded active running AI Bot V2 trainer bridge evidence publisher`
- `ai-bot-v2-trainer-checkpoint-evidence.service          loaded active running AI BOT V2 trainer checkpoint evidence publisher (metadata-only, V2 namespace)`
- `ai-bot-v2-trainer-training-live-loop.service           loaded active running AI BOT V2 trainer training live loop (signal-only, V2 namespace)`
- `ai-bot-v2-worker-porting-orchestrator.service          loaded active running AI Bot V2 worker-porting orchestrator`

## Intentionally Skipped

- `ai-bot-v2-live-canary-dry-run.service`: canary/live-path service intentionally inactive
- `old legacy root /home/wali/Desktop/AI BOT`: old live bot/trader/trainer not started
- `legacy trading/exchange mutation scripts`: would place/manage exchange orders or mutate margin/leverage/old Redis
- `legacy rl/hybrid_trainer.py and gpu_forced_ppo.py direct start`: old trainer runtime not direct-started; V2 trainer inference and training loops are active

## Safety Pins

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `trader_execution_enabled=false`
- `exchange_action_taken=false`
- `old_legacy_root_started=false`

## Artifacts

- Status JSON: `claude_worklog/final_readiness/safe_rebuild_go_live_start_20260603/latest/STATUS.json`
- Public mirror: `v2/frontend/public/safe_rebuild_go_live_start_20260603/latest`
