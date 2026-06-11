# Pipeline Trust Synthetic Testing

This test suite exercises the read-only `verify_pipeline_trust` command with synthetic end-to-end evidence. It does not submit live orders, change strategy logic, optimize PPO, modify MASA, or touch live execution behavior.

## Test file

The synthetic tests live at:

```text
v2/backend/tests/unit/test_pipeline_trust.py
```

They create temporary JSONL evidence records, run the verifier, and inspect `pipeline_trust_report.json` plus the verifier exit code.

## Safety contract

Every synthetic case checks that the verifier gives an explicit outcome:

- `status`
- `severity`
- affected modules
- example records for failed dirty evidence
- recommended fix

Critical failures must cause a non-zero verifier exit. Clean and correctly handled cases must produce zero critical failures and replayable report files.

## Covered scenarios

| Scenario | Expected verifier behavior |
|---|---|
| Clean data path | Accepted with zero critical failures and replayable JSON/Markdown reports. |
| Missing candle | Candle gap is flagged, and dirty training acceptance is critical if the sample is still used. |
| Duplicate candle | Duplicate candle is flagged before training/execution. |
| Out-of-order candle/event | Out-of-order candle is flagged before training/execution. |
| Unfinished higher-timeframe candle | Critical failure before decision/training/execution trust. |
| Future feature leakage via `available_at` | Critical future feature use failure. |
| MASA future cutoff | Critical MASA cutoff failure. |
| MASA/PPO cutoff mismatch | Critical mismatch failure. |
| NaN/inf/null features | Invalid features are flagged, and accepted dirty training is critical. |
| Backfilled data marked live | Critical dirty training sample failure. |
| Stale Redis/event message | Stale feature is flagged, and accepted dirty training is critical. |
| Source disagreement | Cross-source disagreement is flagged before training/execution. |
| Invalid position transition | Critical invalid transition failure; no live order should be considered safe. |
| Local/exchange position drift | Critical position drift failure requiring reconciliation. |
| Partial fill | Accepted only when partial-fill state, remaining quantity, fees, and training outcome are represented. |
| Rejected/canceled order | Accepted only when position is not falsely updated and the order is not turned into a positive training sample. |
| Unsafe config/admin state | Critical failure if config evidence shows secret leakage, self-created approvals, old Redis writes, exchange action, or leverage/margin mutation. |

## Run command

From the repository root:

```bash
cd v2
python -m pytest backend/tests/unit/test_pipeline_trust.py
```

## Design notes

The tests are intentionally synthetic. They prove the verifier can detect or accept the specified safety conditions with controlled evidence. They do not prove production data is safe unless the verifier is also run against representative runtime snapshots or Redis read-only evidence.
