# V2 Legacy Production Service Parity Repair Report

Gate: `V2_LEGACY_PRODUCTION_SERVICE_PARITY_REPAIR_READY`
Generated EST: `2026-06-04T22:08:00-04:00`
Legacy roles checked: `24`
Repaired/covered roles: `20`
Real-reason non-active roles: `4`
Blocking required read-only roles: `0`
Features latest grid: `505`
Technical analysis grid: `505`
Full TA grid: `505`
Liquidation levels grid: `505`
Ingestors: `INGESTORS_OK` active_count=`15`
System observability: `V2_SYSTEM_OBSERVABILITY_OK`

Live/canary remain blocked. Multi-account live trader/portfolio roles are not activated because the live gate and audit contracts remain human/operator-gated.

- live_gate: `blocked_human_only`
- live_symbols: `[]`
- execution_live_symbols: `[]`

Safety: no live/canary enable, no order/test-order/cancel/modify, no leverage/margin mutation, no old Redis write, no Redis trim, no legacy restart, no VPN reconnect, no Telegram send.
