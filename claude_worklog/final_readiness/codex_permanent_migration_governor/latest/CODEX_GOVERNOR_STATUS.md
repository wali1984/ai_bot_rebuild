# Codex Permanent Migration Governor Status

Generated: `2026-05-15T17:51:27Z`

GO/NO-GO: `CODEX_PERMANENT_SHUTDOWN_AND_MIGRATION_GOVERNOR_READY`

Mode: no new script/service was created because the operator explicitly requested this be run here. This packet binds the active existing Codex takeover and observatory services into the governor state.

## Simple Status

- Are we live? **No.** `live_gate=blocked_human_only`, `live_symbols=[]`.
- Are we paper/shadow? **Yes**, V2 paper/shadow only with a strict expected-edge gate.
- Can legacy be shut down? **No.** Current recommendation: `BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`.
- Main P0 blocker: `PAPER_EDGE_UNPROVEN`.
- Expected-move review: `V2_EXPECTED_MOVE_MODEL_REVIEW_READY_KEEP_GATE_STRICT` with action `KEEP_GATE_STRICT`.
- Next action: `{'blocker_id': 'PAPER_EDGE_UNPROVEN', 'follow_up': 'continue observing blocked paper intents over 5m/15m/30m/1h horizons; do not loosen fill gate or claim positive edge without completed after-cost evidence', 'kind': 'monitor_shadow_outcome_observer', 'task_id': 'paper_shadow_outcome_observer'}`.

## Active Blockers

- `LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED` (OPERATOR_DECISION_REQUIRED): trainer_bridge: legacy_log_confidence_calibration_derived; native trainer evidence was not found and TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET requires explicit operator acceptance for V2 paper-only shutdown evaluation; live/canary remain blocked
- `LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE` (OPERATOR_DECISION_REQUIRED): trainer_bridge: legacy_log_feature_attribution_incomplete; native trainer evidence was not found and TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET requires explicit operator acceptance for V2 paper-only shutdown evaluation; live/canary remain blocked
- `LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED` (OPERATOR_DECISION_REQUIRED): trainer_bridge: legacy_log_feature_snapshot_id_derived; native trainer evidence was not found and TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_PACKET requires explicit operator acceptance for V2 paper-only shutdown evaluation; live/canary remain blocked
- `PAPER_PNL_NEGATIVE_BLOCKS_CANARY` (P2_LIVE_ONLY_BLOCKED): paper_runtime: paper_realized_pnl_negative; negative cumulative PnL blocks live/canary, while paper-only shutdown remains blocked separately by PAPER_EDGE_UNPROVEN until post-filter outcomes prove positive edge; post_filter_pnl_delta=-0.225535
- `PAPER_EDGE_UNPROVEN` (P0_SHUTDOWN_BLOCKER): paper_runtime: current_paper_intent_blocked_or_unfilled
- `OBSERVATORY_LEGACY_SIGNALS_STALE_SOURCE_LIMITED` (INFO_ONLY): observatory: legacy signals are stale; classify comparison as MISSING_EVIDENCE_CANNOT_COMPARE and do not invent outcomes
- `OBSERVATORY_DECISION_QUALITY_INSUFFICIENT_SAMPLE` (INFO_ONLY): observatory: insufficient acted-trade sample; keep no-trade/outcome observation active and do not claim 99% correctness
- `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY` (OPERATOR_DECISION_REQUIRED): trade_permission: trade_permission_readonly_unknown; account monitor is fail-closed/read-only with no exchange mutation, so this blocks live/canary and requires explicit operator decision for paper-only shutdown

## Frontend Review

The governor payload now exposes simple-English answers for operator UI. Full frontend approval is still blocked until route smoke/product review verifies pages are not blank, do not show raw JSON only, do not hide blockers, and do not enable live controls.

## Safety

- No live approval was created.
- No Redis trim approval was created.
- Old Redis write status remains absent.
- Exchange action status remains absent.
- Legacy is read-only reference only.
