# Requirement 0017 — Force Paper / Backtest MVP Track

## Objective

Prioritize the shortest safe path to a non-live replay/backtest and paper trading MVP.

The current goal is not more scaffolding or sideways infrastructure expansion. The current goal is to get V2 to the first useful non-live decision loop:

validated trainer prediction -> orchestrator decision -> default-deny risk decision -> paper ledger -> replay/backtest runner -> paper mode -> shadow readiness.

## Hard Roadmap Constraint

The planner must stop expanding infrastructure unless that work is directly required by the backtest/paper MVP path.

Finish only the trainer pieces required to emit validated non-live predictions, then move into orchestration, risk, paper execution ledger, and replay.

## Required Milestone Sequence

1. `TRAINER_PREDICTION_OUTPUT_MVP`
2. `ORCHESTRATOR_DECISION_MVP`
3. `RISK_GATEWAY_DEFAULT_DENY_MVP`
4. `PAPER_EXECUTION_LEDGER_MVP`
5. `REPLAY_BACKTEST_RUNNER_MVP`
6. `PAPER_MODE_MVP`
7. `SHADOW_MODE_READINESS`

## Planner Rules

- Do not continue broad trainer infrastructure expansion after the minimum validated prediction-output path exists.
- Do not add new checkpoint/GPU/metadata subdomains unless they are required to emit, validate, identify, or replay non-live predictions.
- Do not open frontend polish work unless it directly exposes the backtest/paper MVP pipeline.
- Do not open unrelated scaffold, dashboard, queue, or automation work unless it blocks the MVP path.
- Codex may autofix blockers, but the planner must not expand sideways unless required by backtest/paper MVP.
- Website work must support visibility of this pipeline, not distract from it.

## Trainer Completion Boundary

Finish only the trainer pieces required to emit validated non-live predictions:

- prediction output contract
- prediction identity
- prediction freshness
- prediction confidence / attribution summary sufficient for risk decisions
- worker/liveness health already needed for trust and observability
- enough checkpoint/version metadata to identify model output, not a broad checkpoint subsystem

## Safety Rules

- Live trading remains blocked.
- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not write Redis legacy keys.
- Do not delete Redis keys.
- Do not restart live services.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not deploy.
- Do not expose secrets.

## Goal Marker

`V2_BACKTEST_AND_PAPER_MVP_READY`

REQ_FORCE_PAPER_BACKTEST_MVP_TRACK_READY
