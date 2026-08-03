# Data Flow Master Map — AI BOT V2

> **Historical snapshot — superseded by the 2026-07-16 reconstruction.** Do not use this file alone for current behavior, operations, safety, or change-impact decisions. Start with [REVERSE_ENGINEERING_INDEX.md](REVERSE_ENGINEERING_INDEX.md).
Generated: 2026-07-01T22:56:31Z

## End-to-End Flow Narrative

```
EXCHANGE / PROVIDER
       │
       ▼
INGESTOR LAYER (websocket/REST loops)
  Binance USDM WSS → raw kline events
  Liquidation WSS → forceOrder events
  CoinAPI WSDS/REST → OHLCV multi-exchange
  KuCoin REST → price/volume cross-reference
  CoinAnk → funding rate, OI, long/short ratio, basis
  Public Intel → fear/greed, dominance, CG/CoinGlass data
  LunarCrush → social score
  Nansen → on-chain flow
  AICoin → whale walls (credential-blocked)
       │
       ▼
FEATURE PIPELINE (v2_feature_pipeline_native_loop)
  Reads: v2:market:kline:{sym}:{tf}, v2:features:kucoin:{sym}:{tf}
         v2:market:coinapi:ohlcv:{sym}:{tf}, v2:features:ta_full:{sym}:{tf}
         v2:liq:events:stream, v2:liq:levels:{sym}
         v2:altdata:coinank:{sym}, v2:altdata:public_intel:{sym}
  Writes: v2:features:latest:{symbol}:{timeframe}
  TA-Lib loop writes: v2:features:ta:{sym}:{tf}, v2:features:ta_full:{sym}:{tf}
       │
       ▼
FEATURE SNAPSHOT BUILDER (v2_feature_snapshot_builder)
  Reads: v2:features:latest:{sym}:{tf} (all symbols/timeframes)
  Writes: v2:features:snapshot:v2_fsnap_{hash}
          v2:features:snapshots (index)
  Note: 290k+ snapshots accumulated in Redis
       │
       ▼
NATIVE CUDA TRAINER (v2_native_cuda_trainer_persistent_loop)
  Reads: v2:features:snapshot:* (training rows)
         v2:trainer:feedback:outcomes (paper outcome labels)
         v2:paper:closed_trades (closed trade outcomes)
  Writes: v2:trainer:heartbeat
          v2:trainer:hybrid_cuda:heartbeat
          v2:trainer:hybrid_cuda:metrics
          v2:trainer:checkpoint:heartbeat
          v2:trainer:checkpoint:evidence
  Architecture: PPO + MASA heads; GPU (CUDA) native PyTorch
  Policy: challenger_v2_cuda_exitless_{fingerprint}
       │
       ▼
NATIVE TRAINER PREDICTION PUBLISHER (sub-service)
  Reads: trainer model in memory; v2:features:snapshot:* (inference)
  Writes: v2:prediction:{symbol}:{timeframe} (per symbol/timeframe)
          v2:trainer:hybrid_cuda:signals:paper:{symbol}
  Format: {direction, confidence, confidence_calibrated, expected_move,
           action_probabilities, price_targets, checkpoint_id, feature_snapshot_id,
           feature_vector_hash, decision_time, available_at, feature_cutoff}
       │
       ▼
RL CORE SIDECAR (v2_rl_core_inference_loop) — SIDECAR ONLY, does NOT overwrite trainer
  Reads: v2:features:snapshot:* (sidecar inference)
  Writes: v2:rl_core:inference:{symbol}:{tf} (sidecar rows only)
  Note: Does not route to paper/live; advisory signal only
       │
       ▼
ALL-TIMEFRAME PREDICTION/SIGNAL PUBLISHER (v2_all_timeframe_prediction_signal_price_target_publisher)
  Reads: v2:prediction:{sym}:{tf}
  Writes: v2:signals:all_tf:{sym}, v2:website:predictions:{sym}
  Purpose: Aggregates predictions across timeframes for website display
       │
       ▼
ORCHESTRATOR (v2_orchestrator_arbitration_loop + worker)
  Reads: v2:prediction:{sym}:{tf} (ALL predictions across symbols/tfs)
         v2:continuous_edge_guardian:a_grade_execution_gate
         v2:paper:intents_held_by_paper_fill_gate
  Processes: 393 predictions → arbitration → 130 bucket winners
  Writes: v2:orchestrator:proposals
          v2:orchestrator:decisions
          v2:orchestrator:heartbeat
          v2:signals:paper
       │
       ▼
RISK GATEWAY (v2_risk_gateway_live_loop + worker)
  Reads: v2:orchestrator:decisions, v2:features:latest:{sym}:{tf}
         v2:features:snapshot:{id}, v2:liq:levels:{sym}
  Evaluates: market-state risk, data freshness, lineage, confidence,
             spread/slippage, liquidity, drawdown, portfolio exposure
  Writes: v2:risk:gateway:decisions
          v2:risk:gateway:latest
          v2:risk:gateway:heartbeat
          v2:risk:gateway:paper_online_decisions
  Current: deny_default (live gate blocked) → 130 decisions all DENIED
       │
       ▼
PAPER TRADER (v2_trade_management_paper_loop)
  Reads: v2:orchestrator:decisions (paper intents from orchestrator)
         v2:risk:gateway:paper_online_decisions (risk-gated decisions)
         v2:market:kline:{sym}:1m (mark prices for fills)
  Processes: Paper fills at market price ± fee/slippage simulation
  Writes: v2:paper:heartbeat
          v2:paper:intents
          v2:paper:intents_held_by_paper_fill_gate
          v2:paper:ledger (positions + PnL)
          v2:paper:closed_trades
          v2:paper:outcome_labels (for trainer feedback)
          v2:paper:active_runtime_owner_status
  Policy: challenger_v2_cuda_exitless_{fingerprint}
  Owner: v2_trade_management_paper_loop (sole owner since 2026-06-27)
       │
       ▼
TRAINER FEEDBACK LOOP
  Reads: v2:paper:closed_trades, v2:paper:outcome_labels
  Writes: v2:trainer:feedback:outcomes
          v2:trainer:feedback:outcomes:quarantine (bad labels)
       │
       └──────────────────────────────► TRAINER (feedback loop)
```

## Key Redis Namespaces

| Namespace Pattern | Producer | Consumer | Critical For |
|-------------------|---------|---------|--------------|
| v2:market:kline:{sym}:{tf} | Binance WSS | Feature Pipeline | training, paper |
| v2:features:latest:{sym}:{tf} | Feature Pipeline | Trainer, Snapshot Builder | training, prediction |
| v2:features:ta:{sym}:{tf} | TA-Lib loop | Feature Pipeline | training |
| v2:features:ta_full:{sym}:{tf} | Full TA loop | Feature Pipeline | training |
| v2:features:kucoin:{sym}:{tf} | KuCoin ingestor | Feature Pipeline | training |
| v2:features:snapshot:v2_fsnap_{hash} | Snapshot Builder | Trainer | training |
| v2:features:snapshots | Snapshot Builder | Trainer index | training |
| v2:features:pipeline:heartbeat | Feature Pipeline | Monitor | observability |
| v2:liq:events:stream | Liquidation WSS | Feature Pipeline | training, risk |
| v2:liq:levels:{sym} | Liq Levels Engine | Risk Gateway | risk |
| v2:altdata:coinank:{sym} | CoinAnk | Feature Pipeline | training |
| v2:altdata:public_intel:{sym} | Public Intel | Feature Pipeline | training |
| v2:altdata:symbol_score:{sym} | Symbol Discovery | Website | website |
| v2:altdata:aicoin:symbol:{sym} | AICoin loop | Feature Pipeline | partial |
| v2:prediction:{sym}:{tf} | Native Trainer Publisher | Orchestrator | prediction |
| v2:trainer:hybrid_cuda:signals:paper:{sym} | Trainer | Orchestrator | prediction |
| v2:trainer:heartbeat | Trainer | Monitor | observability |
| v2:trainer:hybrid_cuda:heartbeat | Trainer | Monitor, Website | observability |
| v2:trainer:checkpoint:evidence | Checkpoint Publisher | Website | observability |
| v2:trainer:feedback:outcomes | Feedback Loop | Trainer | training |
| v2:orchestrator:decisions | Orchestrator | Risk Gateway, Paper | paper |
| v2:orchestrator:proposals | Orchestrator | Website | website |
| v2:orchestrator:heartbeat | Orchestrator | Monitor | observability |
| v2:signals:paper | Orchestrator | Paper Trader | paper |
| v2:risk:gateway:decisions | Risk Gateway | Paper Trader | paper |
| v2:risk:gateway:latest | Risk Gateway | Website, Monitor | website |
| v2:risk:gateway:heartbeat | Risk Gateway | Monitor | observability |
| v2:risk:gateway:paper_online_decisions | Risk Gateway | Paper Trader | paper |
| v2:paper:heartbeat | Paper Trader | Monitor | observability |
| v2:paper:intents | Paper Trader | Website | paper, website |
| v2:paper:ledger | Paper Trader | Website, Portfolio | paper, website |
| v2:paper:closed_trades | Paper Trader | Trainer Feedback | training |
| v2:paper:outcome_labels | Paper Trader | Trainer Feedback | training |
| v2:paper:outcome_memory:{sym}:{tf} | Paper Trader | Trainer | training |
| v2:backtest:index | Backtest runner | Website | website |
| v2:backtest:results:{sym}:{tf}:{id} | Backtest runner | Website | website |
| v2:continuous_edge_guardian:{...} | Edge Guardian | Orchestrator | safety |
| v2:altdata:provider_status | Alt data loop | Website | observability |
| v2:market:coinapi:ohlcv:heartbeat | CoinAPI WSDS | Monitor | observability |
| v2:live_gate:state | Live Gate (not active) | Orchestrator, Risk | safety |
