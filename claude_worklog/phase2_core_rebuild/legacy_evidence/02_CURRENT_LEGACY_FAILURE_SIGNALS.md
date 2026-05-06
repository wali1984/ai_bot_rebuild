# Current Legacy Failure Signals (REQ_0019 consolidated)

Generated: 2026-05-06
Lane: `legacy_parity` (Lane D, read-only).
Purpose: consolidated pointer list to the failure signals already documented in the three audit roots, grouped by failure class so V2 milestones cite the correct legacy_failure_addressed.

This file does not introduce new failure analysis. Every row points at a section already committed in an audit root.

## Source registers

- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`
- `claude_worklog/historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md`

## Failure class → pointer

| Failure class | Audit anchor | V2 milestone that addresses it |
|---|---|---|
| Trainer process alive but prediction worker dead | `legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md`; `legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md` | TRAINER_PREDICTION_OUTPUT_MVP (closed); trainer liveness / worker health |
| Missing `prediction_id` / `feature_snapshot_id` in legacy emissions | `legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md`; `legacy_runtime_audit/08_FEATURE_FLOW_RUNTIME_AUDIT.md` | TRAINER_PREDICTION_OUTPUT_MVP (closed) |
| Missing confidence attribution / unreliable confidence | `legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md`; `historical_pnl_audit/07_LEGACY_TRAINER_DECISION_EVIDENCE.md` | TRAINER_PREDICTION_OUTPUT_MVP (closed) |
| Stale-feature-aware decisions not blocked | `legacy_runtime_audit/08_FEATURE_FLOW_RUNTIME_AUDIT.md`; `legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` | RISK_GATEWAY_DEFAULT_DENY_MVP (closed) |
| Duplicate / stale signal not deduped | `legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md`; `legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` | ORCHESTRATOR_DECISION_MVP (closed) |
| Unsafe hedge unwind leaves naked directional exposure (LAB-class) | `legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`; `historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` | RISK_GATEWAY_DEFAULT_DENY_MVP (closed); REPLAY_BACKTEST_RUNNER_MVP (2I.A open) |
| External / manual position quarantine missing | `legacy_runtime_audit/04_TRADER_RUNTIME_AUDIT.md`; `legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` | RISK_GATEWAY_DEFAULT_DENY_MVP follow-up; REQ_0013 phase-1 quarantine |
| Repeated-loser symbol patterns not vetoed | `historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md`; `historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md` | RISK_GATEWAY_DEFAULT_DENY_MVP (closed) |
| Fee / funding drag eroding net PnL | `historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md` | PAPER_EXECUTION_LEDGER_MVP (closed) |
| Replay / backtest tooling lacked typed lineage value objects | `legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`; `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/01_PHASE_2I_LEGACY_EVIDENCE_REVIEW.md` | REPLAY_BACKTEST_RUNNER_MVP (2I.A staged) |
| Symbol-universe USD-M / COIN-M / spot collapse risk | `legacy_runtime_audit/07_SYMBOL_UNIVERSE_RUNTIME_AUDIT.md`; `claude_worklog/phase2_core_rebuild/symbol_universe/12_CODEX_GO_NO_GO_USDM_CORRECTION.md` | symbol-universe USD-M correction (closed) |
| Ingestor freshness / source-status not gated | `legacy_runtime_audit/06_INGESTOR_RUNTIME_AUDIT.md`; `legacy_runtime_audit/08_FEATURE_FLOW_RUNTIME_AUDIT.md` | ingestor preservation (closed); feature_snapshot_id (closed) |
| Re-d-i-s key / stream evidence missing for replay | `legacy_runtime_audit/02_REDIS_READ_ONLY_KEYSPACE_HEALTH.md`; `legacy_readonly_audit/05_REDIS_READONLY_KEY_STREAM_INVENTORY.md` | REPLAY_BACKTEST_RUNNER_MVP (2I.A staged) |
| 30-day historical PnL evidence partial / Binance API not yet pulled | `historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md`; `historical_pnl_audit/10_GO_NO_GO.md` | follow-up Binance read-only pull task (Lane D) |

## Hard safety

This file does not authorize any action against any failure class. Mitigation responsibility remains with the corresponding V2 MVP milestone in the build-impact map (`01_BUILD_IMPACT_MAP.md`).

REQ_0019_CURRENT_LEGACY_FAILURE_SIGNALS_READY
