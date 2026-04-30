# 06 Validation Checklist

## Pre-start validation (design/implementation)
- [ ] Continuous mode implemented in monitor without mutation commands.
- [ ] Packet schemas include required fields.
- [ ] Alert threshold logic includes 85/90/95 Redis memory bands.
- [ ] Feature freshness and attribution checks implemented.
- [ ] Dashboard shows packet readiness and latest alert.

## Runtime validation (after later start)
- [ ] Monitor process alive continuously.
- [ ] Hourly packets generated on schedule.
- [ ] Daily packets generated at UTC boundary.
- [ ] Alert packets generated on threshold breaches.
- [ ] No Redis write/delete operations observed.
- [ ] Heartbeat WRONGTYPE anomalies detected/classified when present.
- [ ] Signal stream divergence alert works (empty signals while executions continue).

## Quality validation
- [ ] Packet `raw_evidence_pointer` fields resolve to real files/rows.
- [ ] `verification_command` entries are executable read-only checks.
- [ ] `missing_evidence` populated when inputs absent.
- [ ] `confidence_level` is present and consistent with evidence quality.

## Gate result
- [ ] Ready for continuous monitor launch procedure later.
