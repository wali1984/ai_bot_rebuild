# Scoped Quarantine Dry Run 20260612

Mode: `DRY_RUN_ONLY`
Redis mutation: `none`
Apply executed: `false`

## Input review file

- `QUARANTINE_REVIEW_20260612_180857.targets.json`

## Requested scoped dry-run command

```bash
./quarantine_pipeline_trust_stale_records \
  --redis-url redis://127.0.0.1:6379/0 \
  --output-dir pipeline_trust_quarantine \
  --review-file QUARANTINE_REVIEW_20260612_180857.targets.json \
  --only-review-group SAFE_TO_QUARANTINE \
  --exclude-review-group REQUIRES_MANUAL_REVIEW \
  --exclude-review-group DO_NOT_TOUCH \
  --expect-targets 1536 \
  --max-targets 1536 \
  --require-backup \
  --require-review-file \
  --fail-if-v3-targeted \
  --fail-if-live-order-targeted \
  --fail-if-manual-review-targeted \
  --fail-if-do-not-touch-targeted \
  --dry-run
```

## Result

The scoped dry-run failed closed before mutation:

```text
selected target count 0 does not match --expect-targets 1536
```

## Selected target count

| Metric | Count |
|---|---:|
| Expected SAFE_TO_QUARANTINE targets from review | 1536 |
| Actual selected targets from current Redis | 0 |
| Count exactly equals 1536 | 0 |

## Excluded counts from review

| Review group | Count |
|---|---:|
| REQUIRES_MANUAL_REVIEW | 203 |
| DO_NOT_TOUCH | 0 |

## Current Redis read-only spot check

| Pattern | Current key count |
|---|---:|
| `v2:prediction:*` | 0 |
| `v2:signals:paper:*` | 1 |
| `v2:paper:intents` | 1 |
| `v2:risk:decisions` | 1 |

Interpretation: the Redis runtime state has changed since `pipeline_trust_quarantine/20260612_180857/quarantine_report.json` was created. The reviewed safe target population is no longer present in current Redis, so applying the old 1536-target plan would be unsafe without a fresh dry-run/review cycle.

## Selected target count by key pattern

No records were selected from current Redis under the exact-count guarded run.

## Selected target count by reason

No records were selected from current Redis under the exact-count guarded run.

## Selected target count by action

No records were selected from current Redis under the exact-count guarded run.

## Safety checks

| Check | Result |
|---|---|
| pipeline_trust_v3 selected | `0` |
| live/exchange order selected | `0` |
| manual-review selected | `0` |
| do-not-touch selected | `0` |
| dry-run mutated Redis | `false` |

## Final go/no-go for apply

`NO_GO_FOR_APPLY`

Reason: selected target count did not exactly match `1536`. Current Redis no longer matches the reviewed dry-run artifact, so the safe next step is to create a fresh quarantine dry-run and review from the current runtime state.
