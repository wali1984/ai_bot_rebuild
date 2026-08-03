# Publisher Proof Result: 20260612_215719

Generated: `2026-06-12`

Scope: fresh export and strict verification after paper-only publisher proof attempt.

## Publisher proof command result

| Field | Value |
|---|---:|
| Proof run directory | `publisher_proof/20260612_215709` |
| Proof status | `BLOCKED` |
| Proof success | `false` |
| Block reason | `NO_SYMBOL_WITH_CANONICAL_CLOSED_CANDLE_COVERAGE` |
| Prediction emitted | `false` |
| Replay snapshot emitted | `false` |
| MTF snapshot emitted | `false` |
| Routes to live | `false` |
| Live order allowed | `false` |

## Fresh runtime verification

| Field | Value |
|---|---:|
| Evidence run | `pipeline_trust_evidence/20260612_215719` |
| Strict verifier exit code | `0` |
| Critical failures | `0` |
| Active-stale count | `0` |
| Prediction key count | `0` |
| Replay snapshot count | `0` |
| MTF snapshot count | `0` |

## Evidence counts

| File | Records |
|---|---:|
| `candles.jsonl` | `3368` |
| `features.jsonl` | `4471` |
| `masa_ppo.jsonl` | `2` |
| `training_samples.jsonl` | `9` |
| `execution_records.jsonl` | `11` |
| `positions.jsonl` | `266` |
| `config_admin.jsonl` | `4` |
| `replay_snapshots.jsonl` | `0` |

## Acceptance criteria status

| Criterion | Status |
|---|---|
| `strict verifier exit = 0` | Pass |
| `critical failures = 0` | Pass |
| `active-stale count = 0` | Pass |
| `v2:prediction:* > 0` | Fail |
| `v2:replay:snapshots:* > 0` | Fail |
| `MTF snapshot count > 0` | Fail |
| Fresh prediction has `pipeline_trust_v3` | Not produced |
| Fresh prediction has `mtf_snapshot_id` | Not produced |
| Fresh prediction has `replay_snapshot_id` | Not produced |
| Fresh replay snapshot exists | Fail |
| Fresh MTF snapshot exists | Fail |
| No live order submitted | Pass |
| No strategy/PPO/MASA optimization changed | Pass |

## Test result

Focused trust suite including publisher proof tests:

```text
81 passed
```

## Final recommendation

Do not proceed to live-canary safety yet.

Next surgical pass: restore canonical closed-candle runtime coverage, then re-run:

```bash
./run_trusted_prediction_publisher_once \
  --redis-url redis://127.0.0.1:6379/0 \
  --paper-only \
  --no-live

./export_pipeline_trust_evidence \
  --redis-url redis://127.0.0.1:6379/0 \
  --output-dir pipeline_trust_evidence

./verify_pipeline_trust \
  --input pipeline_trust_evidence/<new_run> \
  --output-dir pipeline_trust_evidence/<new_run>/report \
  --strict-unknown
```

Pass condition remains:

```text
strict_verifier_exit = 0
critical_failures = 0
active_stale_count = 0
v2:prediction:* > 0
v2:replay:snapshots:* > 0
MTF snapshot count > 0
```
