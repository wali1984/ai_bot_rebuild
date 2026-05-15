# Observatory To Action Controller Patch

Generated: `2026-05-15T05:07:08Z`

This patch makes observatory findings actionable. It does not approve live trading, canary trading, or legacy shutdown.

## Current Findings

- observatory: `CODEX_LEGACY_V2_REALTIME_DECISION_OBSERVATORY_READY`
- legacy trainer: `RUNNING_READONLY_OBSERVED`
- legacy signals: `STALE`
- signal comparison classification: `MISSING_EVIDENCE_CANNOT_COMPARE`
- V2 decision quality: `EDGE_PENDING_INSUFFICIENT_SAMPLE`
- paper edge: `EDGE_PENDING`
- post-filter interpretation: `POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING`
- trainer parity: `BLOCKS_LEGACY_SHUTDOWN`
- trainer gaps: `['LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED', 'LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE', 'LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED']`

## Action Routing

- next action: `dispatch_claude_remediation`
- next task: `claude_v2_paper_edge_recovery_and_cost_aware_trade_selection`
- paper edge recovery status: `pending`
- trainer full parity status: `human_attention_required`
- trainer derived/native packet status: `superseded_by_evidence`

Rules now enforced:

- `EDGE_PENDING` or `EDGE_PENDING_INSUFFICIENT_SAMPLE` dispatches/unsticks paper edge recovery.
- trainer parity not equal to `FULL_LEGACY_PARITY_READY` keeps full parity or derived/native acceptance work queued.
- stale legacy signals are source-limited and classified as `MISSING_EVIDENCE_CANNOT_COMPARE`.
- zero post-filter fills remain `POST_FILTER_NO_UNSAFE_FILLS_EDGE_PENDING`, not positive edge.
- insufficient sample never claims 99% correctness.

## Safety

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- final approval token: `absent`
- Redis trim approval: `absent`
- old Redis write status: `absent`
- exchange action status: `absent`
