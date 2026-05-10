# Post-Trim Validation Plan

Only run this plan after a separate approved trim execution phase.

Read-only validation commands:

```bash
redis-cli INFO memory
redis-cli TYPE liquidations:events
redis-cli XLEN liquidations:events
redis-cli MEMORY USAGE liquidations:events
redis-cli XINFO STREAM liquidations:events
redis-cli XINFO GROUPS liquidations:events
redis-cli XPENDING liquidations:events liq_levels
redis-cli XRANGE liquidations:events - + COUNT 5
redis-cli XREVRANGE liquidations:events + - COUNT 5
```

Expected checks:

- Redis used memory drops materially from 12.55G.
- `liquidations:events` still exists and remains type `stream`.
- Stream first ID is greater than or equal to the approved cutoff `1777222885206-0`,
  or Redis reports a nearby approximate trim boundary because `~` is used.
- Stream last ID is not older than the pre-trim last ID `1778436058746-7`.
- Consumer group `liq_levels` has pending `0` and lag `0`.
- No Redis write/delete/trim command other than the separately approved command
  was executed.
- Live trading remains `blocked_human_only`.
