# V2 Permanent Objective Router Status

Generated: `2026-05-15T19:52:28+00:00`
Live gate: `blocked_human_only`
Live symbols: `[]`
Final approval token: `absent`

## Selected highest-priority blocker

- id: `PAPER_EDGE_UNPROVEN`
- category: `P0_SHUTDOWN_BLOCKER`
- source: `codex_shutdown_readiness_takeover`
- remediation task id: `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`
- evidence: `paper_runtime: current_paper_intent_blocked_or_unfilled`

## Routing summary

- P0 blockers remaining: `8`
- P1 blockers remaining: `0`
- P2 blockers (always blocked until P0/P1 clear): `3`
- Safety guard: `ok` (safe=True)
- UI-only routing allowed: `False`
- Live/canary routing allowed: `False`

## All blockers

- `LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED` (OPERATOR_DECISION_REQUIRED) from `codex_shutdown_readiness_takeover` -> task `claude_v2_trainer_derived_evidence_acceptance_or_native_parity_packet`
- `LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE` (OPERATOR_DECISION_REQUIRED) from `codex_shutdown_readiness_takeover` -> task `claude_v2_trainer_derived_evidence_acceptance_or_native_parity_packet`
- `LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED` (OPERATOR_DECISION_REQUIRED) from `codex_shutdown_readiness_takeover` -> task `claude_v2_trainer_derived_evidence_acceptance_or_native_parity_packet`
- `PAPER_PNL_NEGATIVE_BLOCKS_CANARY` (P2_LIVE_ONLY_BLOCKED) from `codex_shutdown_readiness_takeover` -> task `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`
- `PAPER_EDGE_UNPROVEN` (P0_SHUTDOWN_BLOCKER) from `codex_shutdown_readiness_takeover` -> task `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`
- `OBSERVATORY_LEGACY_SIGNALS_STALE_SOURCE_LIMITED` (INFO_ONLY) from `codex_shutdown_readiness_takeover` -> task `None`
- `OBSERVATORY_DECISION_QUALITY_INSUFFICIENT_SAMPLE` (INFO_ONLY) from `codex_shutdown_readiness_takeover` -> task `None`
- `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY` (OPERATOR_DECISION_REQUIRED) from `codex_shutdown_readiness_takeover` -> task `claude_remediate_account_position_monitor_shutdown_parity`
- `EXPECTED_MOVE_MODEL_REVIEW_INCOMPLETE` (P0_SHUTDOWN_BLOCKER) from `expected_move_model_review` -> task `claude_v2_expected_move_model_review_and_false_block_calibration`
- `TRAINER_PARITY_INCOMPLETE` (P0_SHUTDOWN_BLOCKER) from `v2_trainer_bridge` -> task `claude_port_v2_trainer_bridge_full_legacy_parity`
- `PARITY_MATRIX_NO_FULLY_MIGRATED` (P0_SHUTDOWN_BLOCKER) from `legacy_rl_risk_trainer_trader_closure` -> task `claude_resolve_parity_matrix_gaps`

This router does not approve live, canary, legacy shutdown, or Redis trim.
