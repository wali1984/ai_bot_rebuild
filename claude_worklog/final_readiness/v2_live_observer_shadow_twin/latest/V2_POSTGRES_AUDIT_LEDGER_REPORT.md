# V2 Postgres Audit Ledger Report

Generated at: 2026-05-12T20:11:28Z

Status: `POSTGRES_RUNTIME_WRITE_NOT_ATTEMPTED_NO_V2_DATABASE_URL`

Current V2 audit events are written to V2-owned JSON ledger artifacts. Postgres schema is represented by the audit event contract in the payload, but runtime Postgres writes were not attempted unless an explicit V2 `DATABASE_URL` is configured. No secret values were printed or stored.
