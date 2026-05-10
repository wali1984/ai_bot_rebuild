# Automation Hold Guard

Phase 3H must remain blocked until an operator explicitly approves the exact
documented command.

Automation guard state:

- Do not create the Phase 3H approval file automatically.
- Do not run `redis-cli XTRIM liquidations:events MINID ~ 1777222885206-0`.
- Do not run any other Redis mutation command.
- Do not infer approval from Phase 3G or Phase 3G2 readiness markers.
- Do not proceed to Phase 3H unless the approval file exists and content exactly
  matches the required token.

Required approval path:

```text
claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md
```

Required content:

```text
APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY
```

Current state: approval file absent; Phase 3H blocked.
