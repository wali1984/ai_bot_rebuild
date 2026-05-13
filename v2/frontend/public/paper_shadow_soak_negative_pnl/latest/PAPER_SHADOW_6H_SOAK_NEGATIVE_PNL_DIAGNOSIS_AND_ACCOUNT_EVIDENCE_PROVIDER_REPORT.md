# Paper Shadow 6h Soak Negative PnL Diagnosis And Account Evidence Provider Report

Status: `PAPER_SHADOW_6H_SOAK_NEGATIVE_PNL_DIAGNOSIS_AND_ACCOUNT_EVIDENCE_PROVIDER_READY`

The 1h window is complete, but the paper PnL is negative and the 6h/24h windows remain pending. The current engine shows fee-only realized PnL on frequent paper fills, so this is not profitability proof and it blocks canary consideration.

| Item | Status |
| --- | --- |
| 1h soak | PAPER_SHADOW_1H_COMPLETE |
| 6h soak | PAPER_SHADOW_6H_COMPLETE |
| 24h soak | PAPER_SHADOW_24H_PENDING |
| paper pnl | -38.09 |
| diagnosis | PAPER_PNL_DIAGNOSIS_BLOCKS_CANARY, PAPER_PNL_DIAGNOSIS_INSUFFICIENT_WINDOW, PAPER_PNL_NEGATIVE_EARLY_WINDOW, PAPER_PNL_NEGATIVE_FEES_SLIPPAGE_DRAG, PAPER_PNL_NEGATIVE_OVERTRADING, PAPER_PNL_NEGATIVE_PAPER_ENGINE_ASSUMPTION, PAPER_PNL_NEGATIVE_SIGNAL_EDGE_WEAK |
| fill quality | CHURN_RISK_OBSERVED, FEE_BLEED_OBSERVED, FILL_RATE_TOO_HIGH, LOW_CONFIDENCE_FILL_RISK, OVERTRADING_RISK_OBSERVED |
| account evidence | READONLY_ACCOUNT_EVIDENCE_STALE |
| trade permission | TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY |
| margin/leverage | ISOLATED_MARGIN_EVIDENCE_MISSING, LEGACY_CROSS_MARGIN_OBSERVED_READONLY, LEVERAGE_CAP_EVIDENCE_PRESENT, LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY, V2_CROSS_MARGIN_BLOCK_PROVEN, V2_LEVERAGE_CAP_BLOCK_PROVEN |
| canary ready | False |
| live gate | blocked_human_only |

## Remaining Blockers

- ISOLATED_MARGIN_EVIDENCE_MISSING
- PAPER_PNL_NEGATIVE_OR_INSUFFICIENT_DIAGNOSIS_BLOCKS_CANARY
- PAPER_SHADOW_24H_PENDING
- READONLY_ACCOUNT_EVIDENCE_STALE
- TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY

No final live approval token was created. No old Redis write, exchange action, leverage change, or margin mode change was performed.
