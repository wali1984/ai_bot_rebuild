# V2 Adaptive Capital Out-of-Sample Evidence Producer Validation

Generated UTC: `2026-06-22T00:23:05Z`

## Result

- Producer implementation: complete.
- Production evidence acquisition: not complete.
- Live-grade reverify: `NO_GO_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY_INCOMPLETE`.
- 1000x feasibility: `NO_GO_1000X_FEASIBILITY_REQUIRES_OUT_OF_SAMPLE_LIVE_GRADE_REVERIFY`.
- Goal remains active because production sidecars have zero countable rows.

## Evidence Produced

- Holdout final sidecar exists but has `0` rows.
- Realtime final sidecar exists but has `0` rows.
- Holdout rejection ledger has `19,800` rows.
- Realtime rejection ledger has `85,353` rows.
- Holdout producer labeling is now two-pass: a selected holdout candidate must exist in `out_of_sample_holdout_reverify_pending.jsonl` before a later producer pass can append the labeled final row. The latest run reports `holdout_labeling_policy=REQUIRES_PREEXISTING_PENDING_SELECTION_RECORD`, `0` labeled-from-preexisting-pending rows, and `0` same-run pending rows.
- Holdout registry preflight artifact was added and regenerated. It reports `NO_GO_NO_REGISTERED_HOLDOUT_WINDOWS`, source hash match `true`, `19,800` source rows across `90` symbols and `5` timeframes, `0` registered windows, `0` matching source rows, `0` decision-time candidate-ready rows, and `0` countable after-label rows. The preflight explicitly records that outcome fields are excluded before selection and that selection does not filter by outcome.
- Latest bounded Redis-only alias watch processed two realtime cycles and appended `467` new rejected rows, `0` pending rows, and `0` final rows.
- Latest single-cycle Redis-backed manifest processed `3,393` realtime Redis source rows and appended `1` new rejected row, `0` pending rows, and `0` final rows.
- Read-only Redis source coverage in the latest manifest: `0` paper intents, `755` paper signals, `755` predictions, `238` adaptive accepted fills, `0` open positions, and `1,645` closed trades.
- Rejection-ledger diagnostics are published in the holdout and realtime manifests. The realtime ledger has `85,353` rows; top reasons are `DYNAMIC_BUCKET_NOT_A_GRADE_ELIGIBLE` (`85,353`), `MISSING_ACCOUNTING_TAKE_PROFIT_STRUCTURE` (`85,353`), `MISSING_ACCOUNTING_ALLOCATED_MARGIN` (`84,530`), `MISSING_ACCOUNTING_LIQUIDATION_BUFFER` (`84,530`), `MISSING_ACCOUNTING_HEDGE` (`84,135`), and `MISSING_ACCOUNTING_STOP_DISTANCE` (`84,135`).
- Source-gate breakdown is now published in the holdout and realtime manifests. The latest realtime run had `0` candidate-ready rows, `3,393` rejected source rows, and source-gate category counts of accounting `36,707`, frozen selector `6,058`, point-in-time lineage `3,860`, and evidence protocol `727`.
- Holdout and realtime hash-chain JSONL files are present.
- Evidence integrity status: `PASSED_EVIDENCE_INTEGRITY`.
- Holdout hash chain verified `19,800` / `19,800` sidecar records with `0` failures.
- Realtime hash chain verified `85,353` / `85,353` sidecar records with `0` failures.
- Holdout registry was created with `NO_ELIGIBLE_HOLDOUT_WINDOWS_REGISTERED`; the available closed-candle replay source is excluded by default because it is the accelerated replay source.

## Tests

- `python -m py_compile v2/backend/app/cli/v2_out_of_sample_reverify_evidence_producer.py`: passed.
- `.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_out_of_sample_reverify_evidence_producer.py`: passed, 15 tests.
- `.venv/bin/pytest -q v2/backend/tests/unit/cli/test_v2_out_of_sample_reverify_evidence_producer.py v2/backend/tests/unit/cli/test_v2_adaptive_capital_productivity_status.py`: passed, 115 tests.

## Runtime Producer Run

- First producer run was terminated after it wrote partial holdout rejections because the first hash-chain implementation reread the chain per append.
- Producer was patched to cache chain state and dedupe existing rejection identities.
- Rerun completed successfully and regenerated the validator status.
- Status regeneration returned code `2`, expected because the production gate remains `NO_GO`.
- Redis-enabled run completed successfully and regenerated the validator status.
- The Redis producer is read-only. Current decision-time sources did not contain a qualifying frozen A-grade candidate with complete accounting. Historical accepted/closed ledger rows were rejected unless they already had a prior pending record, preventing post-outcome evidence fabrication.
- The realtime producer now validates a sparse later closed-outcome row against its prior immutable pending selection record when one exists, so real close records do not need to repeat all selector/accounting fields. Outcome fields are appended from the close; selection fields remain from the pending record.
- A bounded realtime watch mode was added and run for two read-only Redis cycles. It is intended for repeated local polling so pending rows can be captured at decision time when the frozen selector first admits a qualifying paper candidate.
- A hash-chain integrity verifier was added and run against the real holdout/realtime sidecars. It passed and wrote `out_of_sample_evidence_integrity_status.json`.
- Verify mode now reloads sidecar manifests into `out_of_sample_evidence_producer_summary.json`, so integrity-only runs preserve the latest accepted/rejected count blocks instead of publishing only the integrity block.
- Realtime CLI now supports `--realtime-redis-only` so watch cycles can poll current Redis snapshots without rereading large filesystem paper event logs. The latest alias-watch run used this mode and processed `3,609` rows per cycle.
- Realtime pending/outcome merge now indexes deterministic lineage aliases, including position, source fill, entry order, signal, prediction, and decision identifiers, so a future sparse close can label a prior pending row even when the canonical first identity differs.
- The latest alias-watch run used Redis-only source mode and processed `3,609` rows per cycle. It found no countable frozen A-grade rows; all new rows were rejected fail-closed, primarily for non-A-grade eligibility, generated-at/decision-time ordering, non-directional side, missing complete accounting, and non-positive decision-time edge.
- Rejection-ledger summaries remain published in the manifests and regenerated from the real append-only sidecars. The latest `both` producer run processed `19,800` holdout rows and `3,393` realtime Redis rows, appended only one new realtime rejection, and kept both final evidence sidecars empty because no current source row satisfied frozen A-grade selection and complete accounting requirements.
- Source-gate breakdowns remain published in the manifests and regenerated from the real append-only sidecars plus current Redis source rows. The latest `both` producer run processed `19,800` holdout rows and `3,393` realtime Redis rows, appended `1` new realtime rejection, and kept both final evidence sidecars empty because no current source row satisfied frozen A-grade selection, evidence protocol, point-in-time lineage, and complete accounting requirements simultaneously.
- Holdout registry preflight was added to the producer and regenerated into `out_of_sample_holdout_window_registry_preflight.json`. It validates registry/source hashes, untouched-window registration, source symbol/timeframe coverage, window matches, overlap proof, and decision-time candidate readiness before any holdout rows can be counted. The latest `both` producer run processed `19,800` holdout rows and `3,393` realtime Redis rows, appended `1` new realtime rejection, and kept both final evidence sidecars empty because no registered holdout windows exist and no current realtime source row satisfied frozen A-grade selection plus complete evidence/accounting requirements.
- Holdout final labeling now requires a prior pending selection from an earlier producer pass. Unit tests cover first-pass pending capture, later-pass labeling, and a losing holdout outcome that still counts when selected by decision-time fields, preventing single-run or outcome-first holdout evidence construction.

## Safety

No real orders, test orders, leverage exchange mutation, margin-mode exchange mutation, live-gate change, or Redis writes were performed by the producer.
