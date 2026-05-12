# Canary Preflight Packet

Generated at: 2026-05-12T20:05:32Z

Activation status: `BLOCKED_HUMAN_APPROVAL_REQUIRED`

Required before any canary:

- Explicit human approval packet
- Read-only account verification
- Isolated margin verification
- 1x leverage cap verification
- Tiny notional cap
- BTCUSDT-only whitelist
- Kill switch verified
- Mandatory stop policy verified
- Dashboard route: `/admin/live-readiness?role=admin`
- Audit route: `/admin/audit-ledger?role=admin`

Expected first canary command path is intentionally not executable here. No live keys were used and no exchange action was sent.
