# Continuous Paper Loop Status

Status: V2_PAPER_ONLINE_LOOP_RUNNING

The non-live V2 paper runtime loop is running detached and writes only ignored local V2 runtime payloads:

- `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
- `v2/frontend/public/operator_runtime/paper_online/latest/paper_positions.json`
- `v2/runtime/paper_online/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/paper_positions.json`

Safety state:

- Live trading: blocked_human_only
- Exchange orders: false
- Legacy Redis writes: false
- Leverage changes: false
- Margin mode changes: false
- Redis trim approval created: false

The loop intentionally emits `NO_PAPER_ORDER_EMITTED` while current trainer/signal/risk lineage is missing. It is continuous runtime visibility, not live readiness.
