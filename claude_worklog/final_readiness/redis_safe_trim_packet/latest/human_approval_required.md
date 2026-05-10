# Human Approval Required

Phase 3G prepared the trim packet only. It did not trim, delete, write Redis,
restart services, or touch exchange state.

To approve a later execution phase, create:

```text
claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md
```

with exactly:

```text
APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY
```

That approval must be interpreted as permission to run only this command:

```bash
redis-cli XTRIM liquidations:events MINID ~ 1777222885206-0
```

It does not approve any other Redis command, service restart, exchange action,
or live-trading action.
