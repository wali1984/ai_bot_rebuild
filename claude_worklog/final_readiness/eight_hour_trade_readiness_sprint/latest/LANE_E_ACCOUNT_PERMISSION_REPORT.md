# Lane E — Account Permission Refresh (8h Sprint)

Generated: 2026-05-15
Lane: E
Live gate: `blocked_human_only`. Live symbols: `[]`.

## Inputs (read-only)

- `v2/frontend/public/operator_runtime/v2_account_position_monitor/latest/v2_account_position_monitor_status.json`
  (age ~22 minutes — FRESH)

## Honest classification

| Field | Value |
|-------|-------|
| `trade_permission_status` | `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY` |
| `credentials_status` | `MISSING` |
| `account_state_one_of_FRESH_STALE_MISSING` | `MISSING` |
| `fail_closed` | `true` |
| `fail_closed_reason` | `MISSING_CREDENTIALS` |
| `exchange_mutation_performed` | `false` |
| `exchange_call_invariant` | `READONLY_ACCOUNT_AND_POSITION_ENDPOINTS_ONLY` |
| `gate_always_blocked_invariant` | `true` |
| `live_blocked` | `true` |
| `live_gate` | `blocked_human_only` |
| `live_symbols` | `[]` |
| `canary_ready` | `false` |
| `canary_blockers` | `["MISSING_CREDENTIALS", "ISOLATED_MARGIN_EVIDENCE_MISSING", "LEVERAGE_CAP_EVIDENCE_MISSING", "CANARY_BLOCKED_BY_ACCOUNT_..."]` |
| `old_redis_write_performed` | `false` |

## Permission classification

Per the migration completion contract, the account position monitor is correctly
classified as:

- `READONLY_BRIDGED` (it bridges read-only account/position endpoints only)
- `FAIL_CLOSED_STUB` for credentials (no credentials present → fail closed)
- `BLOCKED_BY_PERMISSION` for canary advancement (canary_blockers list is
  non-empty)

The router will continue to surface `TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY`
as `OPERATOR_DECISION_REQUIRED` until credentials and isolated-margin /
leverage-cap evidence are provided.

## Invariants verified

- The monitor calls only read-only account and position endpoints.
- No exchange mutation has been performed.
- The gate-always-blocked invariant is true.
- No old Redis writes appear in the payload.
- No approval token has been created.

## What this lane does NOT do

- Does not add credentials.
- Does not call any mutating endpoint.
- Does not authorize canary or live trading.
- Does not change leverage or margin mode.
- Does not produce any approval token.
- Does not invent permission evidence.

## GO/NO-GO for Lane E

`LANE_E_ACCOUNT_PERMISSION_HONESTLY_CLASSIFIED_BLOCKED_BY_PERMISSION`

Live remains `blocked_human_only`.
