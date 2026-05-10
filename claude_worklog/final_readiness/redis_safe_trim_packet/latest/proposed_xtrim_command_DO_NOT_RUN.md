# Proposed Redis Trim Command - DO NOT RUN

Status: documentation only

The Phase 3G task did not execute this command. It is included only for
operator review and requires a separate explicit approval file before any
future execution phase.

```bash
redis-cli XTRIM liquidations:events MINID ~ 1777222885206-0
```

Approval file required before any future execution:

```text
claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md
```

Approval file content must be exactly:

```text
APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY
```

Policy: retain stream IDs greater than or equal to `1777222885206-0`. This keeps a
recent window anchored approximately 14 days before the Phase 3F
export anchor `1778432485206-24` and never removes entries newer than the
verified export anchor.

Mutation status: NOT RUN.
