# Trainer / Trader Parity Requirements

## Objective
V2 trainer and trader must be built from the existing 9-10 months of system logic, not as basic placeholder services.

## Trainer requirements
V2 trainer must preserve or intentionally improve:
- current hybrid trainer architecture
- PPO/MASS concepts
- feature-state mass logic
- reward paths
- confidence paths
- checkpoint behavior
- prediction loop behavior
- proposal/signal publication behavior
- deconflict behavior
- feature freshness handling
- existing symbol/timeframe context
- current model/checkpoint compatibility lessons

V2 trainer must fix:
- prediction worker death while process remains alive
- stdout/broken-pipe vulnerability
- missing feature_snapshot_id
- missing prediction_id
- missing confidence attribution
- weak worker liveness monitoring
- missing explainability
- missing stale/missing/unused feature flags

V2 trainer must emit:
- feature_snapshot_id
- prediction_id
- model_version
- checkpoint_id
- confidence_raw
- confidence_calibrated
- confidence_explainability
- top positive/negative feature contributors
- source key/pattern references
- freshness metadata
- stale/missing/unused flags

## Trader requirements
V2 trader must preserve or intentionally improve:
- current execution/risk lessons
- protective stop/take-profit behavior
- reduce-only/close-position semantics
- duplicate prevention
- stale signal prevention
- portfolio/position feedback
- multi-account/multi-trader future support
- exchange error handling

V2 trader must not be final authority.
Risk Gateway is final authority.

Required flow:
trainer -> signal -> orchestrator -> risk gateway -> execution intent -> trader fleet

## Required parity gates
Before V2 trainer/trader is accepted:
- legacy behavior inventory completed
- feature/signals parity test exists
- replay test exists
- paper test exists
- Codex review passes
- Claude operational review passes
- human approval before live

TRAINER_TRADER_PARITY_REQUIREMENTS_READY
