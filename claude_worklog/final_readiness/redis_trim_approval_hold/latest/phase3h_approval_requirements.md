# Phase 3H Approval Requirements

Phase 3H remains on hold.

Approval file required:

```text
claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md
```

Required exact content:

```text
APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY
```

The approval would authorize only this command:

```bash
redis-cli XTRIM liquidations:events MINID ~ 1777222885206-0
```

No other Redis mutation is approved. This does not approve `DEL`, `XDEL`,
another `XTRIM`, `SET`, `HSET`, `XADD`, `FLUSHALL`, `FLUSHDB`, `CONFIG SET`,
`BGSAVE`, service restart, exchange action, leverage/margin change, or live
trading.
