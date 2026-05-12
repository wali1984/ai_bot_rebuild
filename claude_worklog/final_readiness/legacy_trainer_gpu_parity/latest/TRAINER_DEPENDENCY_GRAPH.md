# Trainer Dependency Graph

Generated: 2026-05-12T06:11:36Z

## Legacy Core Graph

```text
legacy_reference/start_hybrid_trainer_live.sh
  -> python3 -m rl.hybrid_trainer --mode hybrid --training-mode live --enhanced-features
  -> legacy_reference/rl/hybrid_trainer.py
  -> stable_baselines3.PPO / torch / torch.amp / CUDA
  -> legacy_reference/rl/agents/masa_agent.py
  -> legacy_reference/rl/calibrated_confidence.py
  -> legacy_reference/rl/temperature_calibration.py
  -> legacy_reference/rl/confidence_gates.py
  -> feature inputs from Redis/log/live ingestors
  -> PPO/MASA checkpoints under legacy_reference/.models/checkpoints
  -> prediction hashes, proposal streams, signal streams, debug streams in legacy Redis
  -> orchestrator/trader consumers
```

## V2 Paper Wrapper Graph

```text
python3 -m v2.backend.app.cli.paper_online_runtime --loop --interval 30
  -> Binance USD-M public GET price/klines only
  -> build_feature_snapshot(return_1m, return_5m, return_15m, volume_last, volume_avg_10, volatility_10)
  -> build_trainer_prediction(model_checkpoint=v2_paper_readonly_momentum_wrapper_v1)
  -> build_signal_lineage
  -> risk gateway final decision
  -> paper ledger local V2 artifacts only
  -> v2/frontend/public/operator_runtime/paper_online/latest/*.json
```

## Key Finding

The V2 graph is operational for paper mode, but it is a simplified read-only momentum wrapper. It is not evidence that the legacy PPO/MASA CUDA checkpoint path is running or faithfully reproduced.
