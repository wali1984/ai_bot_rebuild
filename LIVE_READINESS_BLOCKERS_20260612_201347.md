# Live Readiness Blockers: 20260612_201347

Generated: `2026-06-12`

Scope: diagnosis of strict verifier critical failures from `pipeline_trust_evidence/20260612_201347/report/pipeline_trust_report.json`.

## Summary

| Field | Value |
|---|---:|
| Evidence run | `pipeline_trust_evidence/20260612_201347` |
| Strict verifier exit | `1` |
| Critical failures | `3` |
| Replay snapshot records exported | `0` |
| Active-stale examples reported | `5` |
| Root cause | Terminal carried-forward paper fills were classified as active runtime approvals. |

## Critical failures

| Check | Affected evidence | Classification | Fix |
|---|---|---|---|
| `replay_snapshot.missing` | `v2:paper:ledger.accepted` and mirrored `v2:paper:positions` rows | Verifier classification bug on stale terminal paper fills | Treat `paper_lifecycle_status=CLOSED_PREVIOUSLY` as inactive runtime history. |
| `mtf_snapshot.missing` | Same rows | Verifier classification bug on stale terminal paper fills | Do not require MTF snapshot evidence for terminal carried-forward paper fills. |
| `runtime_trust.active_stale_missing_contract` | Same rows | Verifier classification bug on stale terminal paper fills | Reuse the same inactive lifecycle classification before active trust contract checks. |

## Affected records

| Intent id | Prediction id | Symbol | Lifecycle | Persistence |
|---|---|---|---|---|
| `v2_paper_intent_BEATUSDT` | `v2h_7ab18a6f9b9e54161a8976ae23671872` | `BEATUSDT` | `CLOSED_PREVIOUSLY` | `EXISTING_FILL_CARRIED_FORWARD` |
| `v2_paper_intent_XMRUSDT` | `v2h_02741bfa62988f43cc21d7f1843386c3` | `XMRUSDT` | `CLOSED_PREVIOUSLY` | `EXISTING_FILL_CARRIED_FORWARD` |
| `v2_paper_intent_ZECUSDT` | `v2h_bf61020ce093a08b5bc2d1cc5f9513aa` | `ZECUSDT` | `CLOSED_PREVIOUSLY` | `EXISTING_FILL_CARRIED_FORWARD` |
| `v2_paper_intent_BABYUSDT` | `v2h_30b60edc42cf8385a5f8dc86ed36a6af` | `BABYUSDT` | `CLOSED_PREVIOUSLY` | `EXISTING_FILL_CARRIED_FORWARD` |
| `v2_paper_intent_HYPEUSDT` | `v2h_f229341904a2cbf13de6e6d2fb3ab2f8` | `HYPEUSDT` | `CLOSED_PREVIOUSLY` | `EXISTING_FILL_CARRIED_FORWARD` |
| `v2_paper_intent_VVVUSDT` | `v2h_4862e4b45273aea3b160cf58eaa4a84d` | `VVVUSDT` | `CLOSED_PREVIOUSLY` | `EXISTING_FILL_CARRIED_FORWARD` |
| `v2_paper_intent_AAVEUSDT` | `v2h_956ffee8538b4e312e991aab833f491d` | `AAVEUSDT` | `CLOSED_PREVIOUSLY` | `EXISTING_FILL_CARRIED_FORWARD` |

## Writer and exporter path

| Path | Function | Role |
|---|---|---|
| `v2/backend/app/cli/v2_trade_management_paper_loop.py` | `_merge_persistent_accepted_fills` | Carries accepted paper fill economics forward and stamps `paper_fill_persistence_status=EXISTING_FILL_CARRIED_FORWARD`. |
| `v2/backend/app/cli/v2_trade_management_paper_loop.py` | runtime write block | Writes `v2:paper:ledger` and `v2:paper:positions`. |
| `v2/backend/app/cli/export_pipeline_trust_evidence.py` | `CATEGORY_PATTERNS["execution_records"]` and `CATEGORY_PATTERNS["positions"]` | Exports the paper ledger and positions records. |
| `v2/backend/app/cli/verify_pipeline_trust.py` | `requires_snapshot_evidence` | Previously re-required snapshot evidence from `paper_fill_allowed` even for terminal lifecycle rows. |
| `v2/backend/app/services/market_state_integrity/trust.py` | `is_active_runtime_record` | Previously treated terminal carried-forward fills as active because legacy `paper_fill_allowed` and `pre_trade_allowed` flags were true. |

## Fix implemented

| File | Change |
|---|---|
| `v2/backend/app/services/market_state_integrity/trust.py` | Added `is_terminal_inactive_runtime_record` and made `is_active_runtime_record` return false for terminal carried-forward paper fills. |
| `v2/backend/app/cli/verify_pipeline_trust.py` | Made `requires_snapshot_evidence` use the same terminal inactive lifecycle rule. |
| `v2/backend/tests/unit/test_pipeline_trust_runtime_enforcement.py` | Added regression coverage for terminal carried-forward paper fills and replay snapshot export. |

## Replay snapshot diagnosis

| Question | Result |
|---|---|
| Is the trusted publisher coded to write replay snapshots? | Yes. `V2HybridPredictionPublisher.publish_prediction` writes `v2:replay:snapshots:{prediction_id}` before writing the prediction when `replay_snapshot_ready=True`. |
| Does the exporter scan publisher replay snapshot keys? | Yes. `export_pipeline_trust_evidence.py` scans `v2:replay:snapshots:*` and related snapshot patterns. |
| Are replay snapshot keys present in current Redis? | No. Current Redis scan found `0` `v2:replay:snapshots:*` keys. |
| Are prediction keys present in current Redis? | No. Current Redis scan found `0` `v2:prediction:*` keys. |
| Responsible issue for `replay_snapshot_count=0` | No fresh trusted prediction/snapshot evidence currently exists in Redis. This is not an exporter pattern miss. |

## Result after fix

Re-running strict verification on the same evidence under `pipeline_trust_evidence/20260612_201347/report_after_lifecycle_fix` produced:

| Field | Value |
|---|---:|
| Strict verifier exit | `0` |
| Critical failures | `0` |
| Active runtime records missing contract | `0` |

## Remaining live-readiness note

Strict critical failures are closed, but runtime cannot yet prove fresh replayable prediction activity because replay and MTF snapshot key counts are still `0`. Live-canary safety should wait for a fresh trusted prediction publisher cycle that emits `v2:prediction:*`, `v2:replay:snapshots:*`, and MTF snapshot evidence.
