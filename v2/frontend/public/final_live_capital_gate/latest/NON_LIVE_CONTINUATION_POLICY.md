
# Non-Live Continuation Policy

Generated: 2026-05-13T03:59:24.783907+00:00

The final live/capital approval gate stops live actions only. Claude/Codex must not go idle while approval is absent.

Allowed non-live continuation:
- trainer parity and safe bridge work
- risk gateway expansion follow-up
- paper/shadow performance review
- V2 data-plane hardening
- script migration backlog
- documentation governance
- public hosting telemetry refinement
- website support only if route/data-truth regression appears

Forbidden without separate approval:
- live activation
- exchange orders
- leverage or margin changes
- old Redis writes
- Redis trim approval

If approval is absent, the always-on runner should select a non-live continuation task instead of dispatching `FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED`.
