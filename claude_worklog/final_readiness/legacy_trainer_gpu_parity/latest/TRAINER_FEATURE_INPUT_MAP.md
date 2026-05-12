# Trainer Feature Input Map

Generated: 2026-05-12T06:11:36Z

## Legacy Expected Inputs

Evidence from `legacy_reference/rl/gpu_optimized_trainer.py` and `legacy_reference/rl/hybrid_trainer.py` indicates:

- Redis keys: `features:*:latest`, `latest:*`, `latest:binance:ohlcv:<symbol>:<tf>`, `features:coinank:liquidations:<symbol>:Binance:15m:series`.
- Large feature tensors: `MassiveGPUNetwork(input_size=1041, action_size=30)` in GPU optimized trainer.
- Checkpoint metadata records env `obs_dim=768`, `act_dim=7` for live enhanced PPO/MASA checkpoints.
- Symbols/timeframes are multi-symbol and multi-timeframe.
- Trainer can use price, liquidation, TA, portfolio/risk, and confidence history surfaces.

## Current V2 Paper Wrapper Inputs

From `v2/backend/app/cli/paper_online_runtime.py`:

- Binance USD-M public read-only price and 1m klines.
- Features: `return_1m`, `return_5m`, `return_15m`, `volume_last`, `volume_avg_10`, `volatility_10`.
- Current feature snapshot: `fs_paper_tick_1778566272462`.
- Source freshness: `CURRENT`.

## Parity Finding

Classification: `v2_simplified_wrapper_not_full_parity`.

The V2 wrapper is valid for current paper-online evidence but does not prove the legacy 768/1041-dimensional feature vector, PPO/MASA agreement, Redis feature surfaces, or calibration inputs are preserved.
