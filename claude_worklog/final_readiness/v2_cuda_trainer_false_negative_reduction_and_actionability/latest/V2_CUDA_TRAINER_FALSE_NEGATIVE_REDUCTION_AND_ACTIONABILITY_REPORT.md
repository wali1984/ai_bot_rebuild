# V2 CUDA Trainer False-Negative Reduction And Actionability Report

Gate: `V2_CUDA_TRAINER_FALSE_NEGATIVE_REDUCTION_AND_ACTIONABILITY_READY`
Generated EST: `2026-06-04T17:43:54-04:00`
False negatives attributed: `43`
Root causes: `{'CONFIDENCE_TOO_LOW': 43, 'DATA_COVERAGE_LOW': 43, 'INSUFFICIENT_HISTORY': 43, 'ORCHESTRATOR_HOLD': 43, 'RISK_GATE_BLOCKED': 43, 'TRAINER_ACTION_TOO_CONSERVATIVE': 43}`
Threshold simulations: `7`
Paper overlay candidates: `15`
Before overlay expectancy bps: `-7.039571167326742`
Before overlay CI lower bps: `-15.222695156211167`
Simulated overlay recovered false negatives: `15`
Simulated overlay candidate expectancy bps: `55.738822117525835`

Live/canary remain blocked. Thresholds are simulated only and not auto-accepted.

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- execution_live_symbols: `[]`
- risk_bypass: `False`
- runtime_config_changed: `False`
- recommendation: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN`
- blockers: `BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN, BLOCK_LIVE_MODEL_SIGNAL_QUALITY_NOT_READY, BLOCK_LIVE_RISK_CAPS_OPERATOR_REQUIRED`

Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no legacy restart, no Redis trim.
