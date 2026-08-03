# V2 Trainer Instructions

Status: active V2 trainer/runtime operating contract.

## Native CUDA Trainer Source

The primary trainer is the local V2 native CUDA trainer under
`v2/backend/app/services/native_trainer/hybrid_cuda_trainer/`. It owns the
primary all-symbol/all-timeframe prediction grid. Legacy trainer code is a
reference for parity only and must not be restarted or used as a live bridge.

## Persistent Trainer Service

The runtime must use the persistent V2 trainer service or its approved one-shot
V2 CLI path. The website must treat stale trainer status as stale. A fresh JSON
file is not sufficient if its content says the model has not produced current
predictions for the full symbol/timeframe grid.

## All-Timeframe Prediction Grid

The trainer/publisher contract is the current CUDA grid across every dynamic
symbol selected by the system and every required timeframe: `1m`, `5m`, `15m`,
`1h`, and `4h`. Paper routing must read the current primary CUDA grid and must
not fall back to a single-symbol dashboard payload.

## Durable Checkpoint Weight Blob Requirement

A checkpoint manifest alone is not learned model state. A valid checkpoint must
include a loadable local weight blob in a safe format such as `.npz` or
`safetensors`. The trainer must load the latest approved V2 checkpoint before a
training cycle and save learned weights after training.

## Closed-Candle Finality Requirement

Training, prediction, replay, and paper candidate generation must use only
closed candles. Open/current candles and unknown-finality candles cannot be
trusted as feature inputs. Higher timeframes must be final before they enter an
MTF snapshot.

## Market-State Integrity Requirement

Every trainable or publishable decision needs point-in-time integrity evidence:
`event_time`, `ingested_at`, `available_at`, `generated_at`, `feature_cutoff`,
`decision_time`, and source finality must not be conflated. A feature is valid
only when `available_at <= decision_time`.

## Adaptive Allocator Relationship

The adaptive allocator is the sizing authority for paper and live pre-submit
readiness. It must consider confidence, edge after cost, volatility, liquidity,
drawdown, exposure, and exchange filters. Fixed runtime sizing is not allowed.

## Paper Lifecycle Relationship

Paper entries, reductions, closes, stops, take-profits, trailing exits, and time
exits must pass through the paper lifecycle guard. Opposite-side same-symbol
fills must net/reduce/close before reverse exposure unless an explicit hedge
intent exists.

## Strategy, Hedge, And Exit Feedback Relationship

Closed paper trades must write realized PnL and outcome labels that include
strategy, hedge, regime, liquidity, microstructure, OI/funding, public-intel,
entry reason, exit reason, and future-label source context when available. The
trainer must learn from closed-trade outcomes, not only prediction counts.

## RL-Core Sidecar-Only Rule

RL-core outputs may exist as sidecar diagnostics. RL-core must not overwrite
primary native CUDA predictions, prediction ids, feature cutoffs, or paper
routing decisions.

## Paper-Only Breakout/Squeeze Detector Rule

The major-move breakout/squeeze detector is paper-only. It uses closed
point-in-time candles and supporting context to produce monitored paper
candidates. It cannot lower live thresholds, submit live orders, or change
leverage/margin behavior.

## Major-Move Replay Rule

Missed major moves must be replayed from decision-time evidence and labeled
with future windows from closed candles or approved historical snapshots. Future
windows are labels only; they must never be decision features.

## 10k/Month Feasibility Rule

The 10,000 USDT/month target is an evidence objective, not a promise. Any
feasibility calculation must be net of fees, slippage, funding, spread,
drawdown, risk caps, exposure, and capital constraints.

## Live Boundary Rule

Live remains held unless margin is sufficient and all pre-submit gates pass.
Trainer, replay, paper, and website remediation cannot submit real orders,
call test-order, cancel/modify orders, or mutate leverage/margin mode.

## Do Not

- Do not use stale dashboard payloads as trainer truth.
- Do not treat a JSON manifest-only checkpoint as learned weights.
- Do not let RL-core overwrite primary CUDA predictions.
- Do not claim 10k/month without net evidence.
- Do not use open candles or future-leaked features.
- Do not mutate live leverage, margin, order, cancel, modify, or test-order paths.
- Do not write old Redis keys from V2 runtime paths.
- Do not reintroduce fixed runtime sizing.
