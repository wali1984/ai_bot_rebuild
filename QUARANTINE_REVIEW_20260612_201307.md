# Quarantine Review 20260612_201307

Fresh review generated from current Redis dry-run artifacts. No Redis mutation was performed.

## Inputs

- `pipeline_trust_quarantine/20260612_201307/quarantine_report.json`
- `pipeline_trust_quarantine/20260612_201307/backup.jsonl`

## Summary

| Metric | Value |
|---|---:|
| run_id | `20260612_201307` |
| redis_db | `0` |
| dbsize | `27134` |
| keys_scanned | `1029` |
| records_targeted | `0` |
| safe_to_quarantine | `0` |
| requires_manual_review | `0` |
| do_not_touch | `0` |
| active_targets | `0` |
| pipeline_trust_v3_targets | `0` |
| live_or_exchange_order_targets | `0` |

## Key count by major pattern

| Pattern | Count |
|---|---:|
| `v2:prediction:*` | 0 |
| `v2:risk:decisions` | 1 |
| `v2:risk:gateway:decisions` | 1 |
| `v2:orchestrator:decisions` | 1 |
| `v2:signals:paper:*` | 0 |
| `v2:paper:intents` | 1 |
| `v2:features:microfeat:*` | 390 |
| `v2:market:kucoin:*` | 635 |
| `v2:replay:snapshots:*` | 0 |
| `v2:market:mtf_snapshot:*` | 0 |
| `v2:decision:mtf_snapshot:*` | 0 |
| `v2:mtf_snapshot:*` | 0 |

## Fingerprints

- Target keys fingerprint: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`
- Safe target keys fingerprint: `4f53cda18c2baa0c0354bb5f9a3ecbe5ed12ab4d8e11ba873c2f11161202b945`

## Classification

| Group | Count |
|---|---:|
| SAFE_TO_QUARANTINE | 0 |
| REQUIRES_MANUAL_REVIEW | 0 |
| DO_NOT_TOUCH | 0 |

## Recommendation

`NO_QUARANTINE_APPLY_NEEDED`

Current Redis produced zero quarantine targets. Do not reuse the historical `20260612_180857` review for apply. Proceed to runtime evidence export and strict verification.
