# Redis Policy

Existing Redis stays in place.

Phase 1:
- read-only access to legacy Redis
- no writes to old keys
- no Redis container required
- no Redis migration
- no key deletion
- no stream trimming

V2:
- may use same Redis instance only with v2:* prefix
- may use separate Redis DB only if explicitly configured
- must never write to:
  - signals:trading*
  - executed_signals
  - positions:*
  - portfolio:*
  - any old legacy runtime keys

Preferred initial V2 persistence:
- SQLite audit index for local evidence
- existing Redis read-only for legacy observation

Future:
- Redis V2 can be isolated later
- Postgres can become source of truth for audit ledger
- existing Redis remains legacy runtime transport unless migration is approved
