# Autonomous Decision Policy

The controller may create and run safe non-live tasks inside `AI BOT REBUILD` when:

- no live/legacy/Redis/exchange/deploy/secrets boundary is crossed
- task outputs are inside allowed prefixes
- Codex review is required after implementation milestones
- live trading remains `blocked_human_only`

It must stop for final live approval, live service restarts, exchange actions, legacy mutation, live Redis writes/deletes, deployment, or secrets exposure.
