# V2 Build Impact Map (REQ_0019 consolidated)

Generated: 2026-05-06
Lane: `legacy_parity` (Lane D, read-only).
Purpose: consolidated mapping of legacy evidence to V2 build impact, drawn from the per-audit build-impact maps already committed under the three audit roots.

This file does not introduce new conclusions. It cross-references the per-audit build-impact maps and groups them by V2 MVP milestone so each milestone in the REQ_0017 sequence has a single citation row.

## Per-audit build-impact map sources

| Audit root | Build-impact map file | Marker |
|---|---|---|
| `claude_worklog/legacy_runtime_audit/` | (no dedicated build-impact file; impact distributed across `03..11` topic files) | `LEGACY_RUNTIME_AUDIT_READY` |
| `claude_worklog/legacy_readonly_audit/` | `09_V2_BUILD_IMPACT_MAP.md` | `LEGACY_READONLY_AUDIT_SENTINEL_READY` |
| `claude_worklog/historical_pnl_audit/` | `09_V2_BUILD_IMPACT_MAP.md` | `HISTORICAL_PNL_TRADE_TRAINER_AUDIT_PARTIAL_LOCAL_ONLY` |

## V2 MVP milestone → consolidated impact rows

### TRAINER_PREDICTION_OUTPUT_MVP (closed)

| Legacy evidence | V2 impact |
|---|---|
| `legacy_runtime_audit/03_TRAINER_RUNTIME_AUDIT.md` | trainer worker liveness, prediction worker health, prediction_id emission |
| `legacy_readonly_audit/06_TRAINER_RUNTIME_EVIDENCE.md` | GPU / checkpoint metadata, hybrid trainer architecture preservation |
| `historical_pnl_audit/07_LEGACY_TRAINER_DECISION_EVIDENCE.md` | confidence attribution required for downstream risk decisions |

### ORCHESTRATOR_DECISION_MVP (closed)

| Legacy evidence | V2 impact |
|---|---|
| `legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md` | decision_id, signal lineage, duplicate / stale signal handling |
| `legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` | typed signal-to-decision routing |
| `legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` | decision-record taxonomy |

### RISK_GATEWAY_DEFAULT_DENY_MVP (closed)

| Legacy evidence | V2 impact |
|---|---|
| `legacy_runtime_audit/10_RISK_AND_SAFETY_RUNTIME_AUDIT.md` | default-deny semantics, stale-data block, exposure check |
| `legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md` | bad-trade patterns to block |
| `legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` | LAB hedge-unwind class (REQ_0022) |
| `historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md` | repeated-loser patterns to deny by default |
| `historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` | risk-gate failure-pattern coverage |

### PAPER_EXECUTION_LEDGER_MVP (closed)

| Legacy evidence | V2 impact |
|---|---|
| `legacy_readonly_audit/05_REDIS_READONLY_KEY_STREAM_INVENTORY.md` | replay input discovery; no live writes |
| `historical_pnl_audit/05_30D_FEES_FUNDING_COMMISSION.md` | fees / funding accounting in paper ledger |
| `historical_pnl_audit/03_30D_REALIZED_PNL_BY_DAY.md` | per-day PnL aggregation pattern |
| `historical_pnl_audit/04_30D_PNL_BY_SYMBOL.md` | per-symbol PnL aggregation pattern |

### REPLAY_BACKTEST_RUNNER_MVP (open, 2I.A staged, dispatch held on 26_ marker)

| Legacy evidence | V2 impact |
|---|---|
| `legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind) | leading replay scenario class (REQ_0022) |
| `legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` | replay-step semantics for signal → decision → execution |
| `historical_pnl_audit/06_LARGE_WINNERS_AND_LOSERS.md` | symbol / regime selection for replay coverage |
| `historical_pnl_audit/02_BINANCE_READONLY_PULL_SUMMARY.md` | replay-data freshness / availability |

### PAPER_MODE_MVP (planned)

| Legacy evidence | V2 impact |
|---|---|
| `legacy_readonly_audit/04_SERVICE_DEPENDENCY_GRAPH.md` | paper-mode service boundary |
| `historical_pnl_audit/09_V2_BUILD_IMPACT_MAP.md` | paper-mode net-PnL accounting |

### SHADOW_MODE_READINESS (planned)

| Legacy evidence | V2 impact |
|---|---|
| `legacy_runtime_audit/04_TRADER_RUNTIME_AUDIT.md` | legacy-vs-V2 shadow comparison contract |
| `legacy_readonly_audit/07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md` | shadow decision-id / paper-trade-id lineage |
| `historical_pnl_audit/08_FAILURE_PATTERNS_AND_V2_REQUIREMENTS.md` | shadow regression checks |

## Hard safety

No row in this map authorizes any live action, any Re-d-i-s write, any service restart, any exchange action, or any deployment. Every cell points at a read-only audit anchor.

REQ_0019_BUILD_IMPACT_MAP_READY
