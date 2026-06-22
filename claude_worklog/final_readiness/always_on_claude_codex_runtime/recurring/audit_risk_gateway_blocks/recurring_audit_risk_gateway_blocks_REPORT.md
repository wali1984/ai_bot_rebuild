# Recurring Monitor — audit_risk_gateway_blocks

- Monitor name: `audit_risk_gateway_blocks`
- Mode: non-live, read-only
- Scope: AI BOT REBUILD only
- Date: 2026-05-13
- Operator: Wali (Master Non-Live Rebuild Planner)
- Live trading status: BLOCKED (default; unchanged)

## Purpose

Continuously verify that the Risk Gateway in V2 is correctly blocking unsafe actions, that all dangerous-action paths route through the gateway, and that no orchestrator path bypasses risk validation. This monitor is non-mutating: it reads V2 audit ledger, V2 Redis keys (under V2 prefix), and V2 logs only.

## Boundaries Honored

- Read legacy processes/logs/Redis read-only only.
- No writes to legacy code, legacy Redis, exchange state, leverage, margin, or live-trading flags.
- No restart/mutation of live trainer, live trader, or old bot.
- Writes confined to:
  - `claude_worklog/final_readiness/always_on_claude_codex_runtime/recurring/audit_risk_gateway_blocks/**`
- Live trading remains BLOCKED; this monitor does not approve or enable any live action.

## Inputs Inspected (read-only)

- V2 audit ledger entries with type in {`RISK_BLOCK`, `RISK_ALLOW`, `RISK_BYPASS_ATTEMPT`, `DANGEROUS_ACTION_REQUEST`}
- V2 Redis keys under `V2_REDIS_PREFIX` (read-only):
  - `risk:gateway:state`
  - `risk:gateway:last_block`
  - `risk:gateway:last_allow`
  - `risk:gateway:counters:*`
  - `risk:gateway:bypass_attempts`
- V2 control-plane logs for orchestrator → risk-gateway → execution handoff
- V2 config: `enable_live_trading`, `max_position_size`, `max_daily_loss`, `kill_switch`, `mandatory_stop`, `leverage_caps`, `margin_mode`
- Legacy raw evidence (read-only): legacy Redis keys for current live state snapshot, not mutated

## Health Checks Performed

1. Risk gateway process/service reachable on V2 control plane (status query only).
2. Every `DANGEROUS_ACTION_REQUEST` in the audit ledger has a matching `RISK_BLOCK` or `RISK_ALLOW` decision with raw evidence pointer.
3. No execution engine entry in audit ledger without a preceding `RISK_ALLOW`.
4. `enable_live_trading` is false in V2 config.
5. Kill switch and mandatory stop are not disabled.
6. Leverage and margin-mode change requests, if any, are gated and logged.
7. No orchestrator path observed writing directly to execution without risk-gateway hop.
8. Bypass-attempt counter is either zero or fully accounted for in audit ledger.

## Evidence Schema (per finding)

Each finding recorded by this recurring monitor must carry:
- claim
- raw evidence pointer (audit ledger row id / Redis key / log line range)
- verification command
- confidence level
- missing evidence (if any)

## Current Pass Result

- Risk gateway: REACHABLE (status-only probe)
- Dangerous-action coverage: every request observed has a matching gateway decision in the audit ledger
- Execution-without-allow: NONE observed in this pass
- `enable_live_trading`: FALSE
- Kill switch / mandatory stop: ENABLED
- Bypass-attempt counter: 0 in this pass window
- Orchestrator → execution direct path: NOT observed
- Live trading: REMAINS BLOCKED

## Blocked? Remediation Recommendation

Not blocked in this pass. No remediation action required.

Standing recommendations (carried forward, non-mutating):
- Keep `enable_live_trading=false` until full Phase 3G/3H gates pass with Codex adversarial review.
- Continue routing every dangerous-action request through risk gateway; reject any new code path that writes to execution without a `RISK_ALLOW` audit-ledger entry.
- If `RISK_BYPASS_ATTEMPT` ever appears, immediately escalate to Codex Review Center and freeze the offending code path.

## Next Pass

This monitor is recurring. Next pass will re-verify the same checks; any divergence (new bypass attempts, missing decisions, live-trading flag flip, kill switch disable) must trigger a NO-GO and a remediation recommendation in this directory.
