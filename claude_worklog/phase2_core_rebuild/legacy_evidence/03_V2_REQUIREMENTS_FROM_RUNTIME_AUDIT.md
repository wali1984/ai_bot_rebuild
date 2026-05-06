# V2 Requirements From Runtime Audit (REQ_0019 consolidated)

Generated: 2026-05-06
Lane: `legacy_parity` (Lane D, read-only).
Purpose: list each V2 requirement that was directly forced by a runtime-audit observation, with a pointer to the audit anchor and the requirement file in the inbox.

This file does not introduce new V2 requirements. It maps already-filed requirements to their runtime-audit origin.

## Mapping

| V2 requirement | Origin runtime-audit anchor | MVP lane |
|---|---|---|
| REQ_0001 Binance USD-M primary | `legacy_runtime_audit/07_SYMBOL_UNIVERSE_RUNTIME_AUDIT.md` | legacy_parity (closed) |
| REQ_0002 CoinAnk uploaded symbol list as discovery only | `legacy_runtime_audit/06_INGESTOR_RUNTIME_AUDIT.md` | legacy_parity (closed) |
| REQ_0003 `live_coinank.py` copy-as-is | `legacy_runtime_audit/06_INGESTOR_RUNTIME_AUDIT.md`; `claude_worklog/legacy_preservation/` | legacy_parity (closed) |
| REQ_0004 trainer GPU parity | `legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md`; `legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md` | paper_backtest_mvp (closed) |
| REQ_0005 startup script as runtime source of truth | `legacy_readonly_audit/02_STARTUP_SCRIPT_MAP.md`; `legacy_runtime_audit/01_PROCESS_AND_SERVICE_INVENTORY.md` | legacy_parity (closed) |
| REQ_0006 trainer parity service implementation | `legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md` | paper_backtest_mvp (active) |
| REQ_0013 SMC / liquidity shadow features | `legacy_runtime_audit/08_FEATURE_FLOW_RUNTIME_AUDIT.md`; `legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` | paper_backtest_mvp (deferred) |
| REQ_0017 force paper / backtest MVP track | `legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`; `legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md` | paper_backtest_mvp (active) |
| REQ_0019 use legacy monitor / audit evidence in V2 build | `legacy_runtime_audit/12_LEGACY_AUDIT_GO_NO_GO.md` | legacy_parity (this turn) |
| REQ_0022 LAB hedge-unwind / squeeze risk | `legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`; `historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` | paper_backtest_mvp (LAB replay scenario in 2I.A) |
| REQ_0023 full legacy read-only audit sentinel | `legacy_readonly_audit/10_GO_NO_GO.md` | legacy_parity (closed) |
| REQ_0024 historical PnL / trade / trainer audit | `historical_pnl_audit/10_GO_NO_GO.md` (partial-local-only) | legacy_parity (partial; Binance read-only pull pending) |

## Open follow-ups derived from runtime audit

| Follow-up | Origin | Suggested lane | Status |
|---|---|---|---|
| Binance read-only 30-day pull (REQ_0024) | `historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md` | legacy_parity | partial-local-only; full pull deferred to a future Lane D task |
| External / manual position quarantine | `legacy_runtime_audit/04_TRADER_RUNTIME_AUDIT.md`; `legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` | paper_backtest_mvp | deferred to post-2I |
| LAB hedge-unwind replay scenario | `legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` | paper_backtest_mvp | scoped into 2I.A test plan (`claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/03_…TEST_PLAN.md`) |
| SMC / liquidity shadow phase order | REQ_0013 sub-phases | paper_backtest_mvp | deferred until after `V2_BACKTEST_AND_PAPER_MVP_READY` |

## Hard safety

No follow-up in this file authorizes a live action, a Re-d-i-s write, a service restart, an exchange action, a leverage change, or a deployment. Every follow-up remains read-only or routes through the standard MVP-milestone gate sequence.

REQ_0019_V2_REQUIREMENTS_FROM_RUNTIME_AUDIT_READY
