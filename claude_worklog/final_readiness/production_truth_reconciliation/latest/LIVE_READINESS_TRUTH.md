# Live Readiness Truth

Generated: 2026-05-13T04:43:38.228869Z

Direct answers:

- Is V2 fully migrated from legacy? **No**.
- Is V2 executing live? **No**.
- Is V2 paper/shadow current? **Yes**.
- Are scripts migrated? **No**. Migrated-to-V2 rows: `1592`. Backlog/not-migrated rows: `2603`.
- Is trainer parity proven? **No**.
- Is Risk Gateway final authority for V2 paper runtime? **Yes**.
- Is website current-data complete? **No**.
- Is full live ready? **No**.
- Is tiny canary approval packet ready? **Yes**, but approval is still required and blockers remain.
- Live gate: `blocked_human_only`.

Classifications:

```json
[
  "FULL_LIVE_NOT_READY",
  "PAPER_SHADOW_READY",
  "MIGRATION_INCOMPLETE",
  "WEBSITE_DATA_TRUTH_INCOMPLETE",
  "HUMAN_APPROVAL_REQUIRED"
]
```

What blocks live tonight:

- No human final approval token exists.
- Final canary checklist still has 3 MISSING_EVIDENCE items.
- Script migration incomplete: 1592 migrated-to-v2 rows vs 2603 backlog/not-migrated rows.
- Legacy system still owns real live execution and trainer/orchestrator runtime.
- Full legacy PPO/MASA trainer parity is not proven.
- Website current-data proof is incomplete: current IDs are not visible on several key routes, and static/hist proof appears on Signals/Executions.
- V2 data plane durability is partial: Postgres runtime writes and V2 Redis writes are not proven/enabled.
- Paper/shadow has current runtime evidence but not a complete 6h/24h profitable strategy proof.
