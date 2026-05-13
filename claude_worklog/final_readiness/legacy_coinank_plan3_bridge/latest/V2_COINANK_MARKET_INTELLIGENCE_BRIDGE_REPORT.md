# V2 CoinAnk Market Intelligence Bridge Report

The bridge reads legacy CoinAnk Redis/file/process evidence and writes only V2-owned payloads. Optional CoinAnk surfaces remain `MISSING_EVIDENCE` unless observed in Redis.

| Item | Value |
|---|---|
| payload | `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json` |
| source | `LIVE_COINANK_READONLY` |
| endpoint manifest version | `MISSING_EVIDENCE` |
| active symbol count | `10` |
| CVD available | `True` |
| SMC available | `False` |
| weighted funding available | `False` |
| liquidation orders available | `True` |
| live gate | `blocked_human_only` |

## Data Truth Rule

CoinAnk-derived data is shown only when this LIVE_COINANK_READONLY payload provides current read-only evidence; missing optional endpoints remain MISSING_EVIDENCE.
