# Readonly Account Trade Permission And 6h Paper Shadow Soak Report

Status: `READONLY_ACCOUNT_TRADE_PERMISSION_AND_6H_PAPER_SHADOW_SOAK_READY`

This sprint continued the primary go-live blocker burn-down without live enablement. The paper-shadow monitor is running, 1h soak is complete, 6h/24h remain pending, and account/trade/margin evidence remains a canary blocker.

| Item | Status |
| --- | --- |
| 1h paper-shadow | PAPER_SHADOW_1H_COMPLETE |
| 6h paper-shadow | PAPER_SHADOW_6H_PENDING |
| 24h paper-shadow | PAPER_SHADOW_24H_PENDING |
| paper events | 625 |
| simulated fills | 548 |
| paper PnL | -31.89 |
| read-only account | READONLY_ACCOUNT_EVIDENCE_STALE |
| trade permission | TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY |
| margin/leverage | ISOLATED_MARGIN_EVIDENCE_MISSING, LEGACY_CROSS_MARGIN_OBSERVED_READONLY, LEVERAGE_CAP_RUNTIME_PROVEN, LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY, V2_CROSS_MARGIN_BLOCK_PROVEN |
| canary ready | False |
| live gate | blocked_human_only |

## Remaining Blockers

- MARGIN_LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY
- PAPER_SHADOW_24H_PENDING
- PAPER_SHADOW_6H_PENDING
- READONLY_ACCOUNT_EVIDENCE_STALE
- TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY

No final live approval token was created. No exchange action, old Redis write, leverage change, or margin change was performed.
