# 06 Heartbeat Schema Policy

## Objective
Eliminate heartbeat `WRONGTYPE` ambiguity by enforcing a single key-type and payload policy.

## Canonical heartbeat contract
For each component heartbeat key:
- fixed Redis data type (one type only per key)
- JSON payload with required fields:
  - `component`
  - `status`
  - `heartbeat_ts_ms`
  - `schema_version`
  - `instance_id`

## Keying policy
- Each logical heartbeat channel has one canonical key pattern.
- No component may write a different Redis type to an existing heartbeat key.
- Type mismatch is a schema violation and must trigger explicit monitoring alert.

## Versioning policy
- Heartbeat payload changes require `schema_version` increment.
- Consumers must validate `schema_version` and fail-safe on unsupported versions.

## Monitoring policy
Read-only monitor must validate:
- key exists,
- key type matches contract,
- payload parses,
- `heartbeat_ts_ms` freshness within SLA.
