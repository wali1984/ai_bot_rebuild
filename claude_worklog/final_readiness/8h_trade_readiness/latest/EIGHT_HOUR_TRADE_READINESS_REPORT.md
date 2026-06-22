# Eight-Hour Trade Readiness Report

Generated: `2026-05-15T21:42:00Z`

GO/NO-GO: `EIGHT_HOUR_TRADE_READINESS_NO_GO_EDGE_NOT_PROVEN`

## Decision

No-go for trade readiness.

The system is safer than the pre-filter paper-loss state, but it is not evidence-backed trade-ready:

- `PAPER_EDGE_UNPROVEN` remains active.
- Expected-move review remains `KEEP_GATE_STRICT`.
- Safe threshold candidates remain `0`.
- Positive post-filter edge is not proven.
- Trainer evidence still has derived/incomplete blockers and requires paper-only operator acceptance.
- Risk/trader parity tests have explicit gaps.
- Trade permission remains unknown/fail-closed with missing credentials.

## Safety State

- live gate: `blocked_human_only`
- live symbols: `[]`
- approval tokens: `absent`
- Redis trim approval: `absent`
- old Redis writes: `absent`
- exchange actions: `absent`
- legacy shutdown approval: `false`
- live/canary approval: `false`

## Lane Outcomes

| Lane | Outcome |
| --- | --- |
| Paper edge | `EIGHT_HOUR_PAPER_EDGE_REPAIR_READY_KEEP_GATE_STRICT`; edge still unproven |
| Trainer | `TRAINER_DERIVED_EVIDENCE_PAPER_ONLY_ACCEPTANCE_REQUIRED` |
| Risk/trader | `RISK_TRADER_PARITY_TESTS_BLOCKED_EXPLICIT_GAPS`; `101 passed`, `3 skipped` |
| Signals | `SIGNAL_ORCHESTRATOR_SOURCE_LIMITED_COMPARE_BLOCKED` |
| Account | `ACCOUNT_TRADE_PERMISSION_OPERATOR_DECISION_REQUIRED` |
| Frontend truth | `FRONTEND_TRADE_READINESS_TRUTH_READY_BLOCKERS_VISIBLE` |

## Exact Blockers

- `PAPER_EDGE_UNPROVEN`
- `LEGACY_LOG_CONFIDENCE_CALIBRATION_DERIVED`
- `LEGACY_LOG_FEATURE_ATTRIBUTION_INCOMPLETE`
- `LEGACY_LOG_FEATURE_SNAPSHOT_ID_DERIVED`
- `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY`
- risk/trader explicit gaps: fee-ratio gate, churn veto, minimum hold time

This report does not approve live, canary, or legacy shutdown.
