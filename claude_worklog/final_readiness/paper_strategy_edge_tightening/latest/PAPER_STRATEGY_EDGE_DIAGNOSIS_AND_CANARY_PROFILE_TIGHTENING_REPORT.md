# Paper Strategy Edge Diagnosis And Canary Profile Tightening Report

Status: `PAPER_STRATEGY_EDGE_DIAGNOSIS_AND_CANARY_PROFILE_TIGHTENING_READY`

The 6h paper-shadow result remains negative, so canary remains blocked. A V2-only tightened profile was added and evaluated without enabling live or weakening risk hard gates.

| Item | Result |
| --- | --- |
| 6h status | PAPER_SHADOW_6H_COMPLETE |
| 24h status | PAPER_SHADOW_24H_PENDING |
| 6h pnl | -6.1 |
| root cause | CANARY_BLOCKED_BY_NEGATIVE_PNL, FEE_SLIPPAGE_DRAG_DOMINANT, LOW_CONFIDENCE_FILL_RISK_DOMINANT, MARKET_REGIME_UNFAVORABLE, NEGATIVE_EDGE_CONFIRMED_6H, NEGATIVE_EDGE_INSUFFICIENT_WINDOW, OVERTRADING_DOMINANT, PAPER_ENGINE_ASSUMPTION_RISK, SIGNAL_EDGE_WEAK_OR_UNPROVEN |
| tightened profile | TIGHTENED_PROFILE_INSUFFICIENT_EVIDENCE, TIGHTENED_PROFILE_OVER_BLOCKS, TIGHTENED_PROFILE_READY_FOR_24H_PAPER_TEST |
| baseline fills | 1192 |
| tightened allowed fills | 0 |
| account/trade/margin blockers | ISOLATED_MARGIN_EVIDENCE_MISSING, LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY, READONLY_ACCOUNT_EVIDENCE_STALE, TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY |
| canary ready | False |
| live gate | blocked_human_only |

## Remaining Blockers

- CANARY_BLOCKED_BY_NEGATIVE_PNL
- ISOLATED_MARGIN_EVIDENCE_MISSING
- LEVERAGE_EVIDENCE_MISSING_BLOCKS_CANARY
- PAPER_SHADOW_24H_PENDING
- READONLY_ACCOUNT_EVIDENCE_STALE
- TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY

No final live approval token was created. No old Redis write, exchange action, leverage change, or margin mode change was performed.
