# Phase 2E1C Alpha Trainer Liveness Implementation Report

## Scope

Phase 2E1C Alpha creates the non-live V2 trainer liveness domain foundation.
It is split across:

- 060A trainer liveness source domain files.
- 060B trainer liveness unit tests.
- 060C validation-readiness docs and GO/NO-GO marker.

This phase does not run or restart the live trainer, write Redis, mutate the
legacy bot, call exchanges, deploy, or enable live trading.

## 060A Source

060A produced the V2 trainer liveness domain under:

`v2/backend/app/domain/trainer_liveness/`

The source provides:

- `LivenessSignalSnapshot`
- `LivenessSLAConfig`
- `LivenessAlert`
- `evaluate_liveness`
- `LivenessDomainError`
- stable liveness reason constants for stale prediction, stale GPU batch,
  stale proposal, zero prediction stream growth, prediction worker death, and
  fatal log signatures

The implementation is pure local domain code. It has no Redis client, exchange
client, subprocess runner, service restart path, or legacy import path.

## 060B Tests

060B produced focused unit tests under:

`v2/backend/tests/unit/domain/trainer_liveness/`

The tests cover:

- signal snapshot invariants
- SLA config invariants
- alert invariants
- no-alert evaluation
- stale prediction/GPU/proposal checks
- zero prediction stream growth
- prediction worker death even when prediction stream growth is nonzero
- fatal log signature handling
- multi-reason alerts
- public import surface

During recovery, the tests were remapped from Claude's incorrect
`v2/tests/trainer_liveness/` output path to the canonical backend unit-test
path and adjusted to match the committed 060A domain contract.

## Local Recovery Validation

The recovery validation run completed before this report was written:

- Python compile passed for trainer liveness source and tests.
- `PYTHONPATH=. .venv/bin/pytest -q v2/backend/tests/unit/domain/trainer_liveness`
  initially passed with 23 tests, then post-autofix validation passed with
  24 tests after adding the prediction-worker-dead regression case.
- High-confidence secret scan was clean.
- No live trainer restart, Redis write, legacy mutation, exchange action,
  deployment, or live trading action was performed.

## Next Gate

This alpha milestone is ready for the formal local-validation task. Do not run
Codex review until the configured 061 local-validation task records its result.

PHASE2E1C_ALPHA_IMPLEMENTATION_REPORT_READY

## Post-Codex Remediation Addendum

Formal Codex review identified missing spec-43 coverage and stale documentation
after the worker-dead autofix. The remediation added unit coverage for:

- never-observed optional timestamp construction
- negative observation and optional timestamp invariants
- nonpositive process identifiers
- RSS-without-trainer invariants
- invalid and empty alert reasons
- strict equal-to-SLA boundary behavior
- missing prediction timestamp age suppression
- `now_ms` validation
- zero-growth RSS-zero and nonzero-growth no-alert cases
- fatal-log false no-alert behavior
- deterministic subset reason ordering
- public-surface internal exclusion checks

The source now documents that deconflict freshness is captured for lineage but
not used by alpha alerting, that missing timestamps are handled through stream
growth rather than age rules, and that worker-dead evidence is independent of
zero-growth evidence.
