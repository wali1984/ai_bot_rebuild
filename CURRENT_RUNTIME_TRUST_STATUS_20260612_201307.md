# Current Runtime Trust Status 20260612_201307

Mode: `READ_ONLY_AUDIT`
Redis mutation: `none`
Quarantine apply executed: `false`

## Fresh quarantine

- Fresh quarantine run directory: `pipeline_trust_quarantine/20260612_201307`
- Fresh review: `QUARANTINE_REVIEW_20260612_201307.md`
- Fresh sidecar: `QUARANTINE_REVIEW_20260612_201307.targets.json`
- Safe quarantine target count: `0`
- Manual review count: `0`
- Do-not-touch count: `0`
- Apply recommended: `false`

## Fresh runtime evidence

- Evidence run directory: `pipeline_trust_evidence/20260612_201347`
- Strict verifier exit code: `1`
- Critical failures remaining: `3`

## Evidence counts

| Evidence file | Count |
|---|---:|
| `candles.jsonl` | 3370 |
| `features.jsonl` | 4471 |
| `masa_ppo.jsonl` | 2 |
| `training_samples.jsonl` | 9 |
| `execution_records.jsonl` | 11 |
| `positions.jsonl` | 266 |
| `config_admin.jsonl` | 4 |
| `replay_snapshots.jsonl` | 0 |

## Requested trust metrics

| Metric | Count |
|---|---:|
| active_stale count | 5 |
| replay snapshot count | 0 |
| MTF snapshot count | 0 |
| missing available_at count | 0 |
| missing feature_cutoff count | 0 |
| abnormal OHLC count | 0 |
| approved/pre-trade records missing replay snapshot | 5 |
| approved/pre-trade records missing MTF snapshot | 5 |

## Critical failure checks

| Check | Count |
|---|---:|
| `mtf_snapshot.missing` | 1 |
| `replay_snapshot.missing` | 1 |
| `runtime_trust.active_stale_missing_contract` | 1 |

## All failed checks

| Check | Count |
|---|---:|
| `candle_integrity.duplicates` | 5 |
| `candle_integrity.non_positive_volume` | 16 |
| `candle_integrity.out_of_order` | 5 |
| `candle_integrity.source_disagreement` | 1 |
| `feature_integrity.invalid_values` | 1 |
| `masa_ppo.missing_contract` | 1 |
| `mtf_snapshot.missing` | 1 |
| `parity.known_differences` | 1 |
| `replay_snapshot.missing` | 1 |
| `runtime_trust.active_stale_missing_contract` | 1 |

## Manifest warnings

```json
[
  "missing_evidence:replay_snapshots"
]
```

## Final recommendation

`RUNTIME_STILL_BLOCKED`: strict verification has critical failures. Do not proceed to strategy evaluation. Fix only the remaining critical trust failures, then re-export and rerun strict verification.

## Next blockers

- `replay_snapshot.missing`: prediction missing replay snapshot evidence
- `mtf_snapshot.missing`: prediction missing multi-timeframe decision snapshot evidence
- `runtime_trust.active_stale_missing_contract`: active approval/training/prediction record missing trust contract evidence
