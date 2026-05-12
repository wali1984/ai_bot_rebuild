# Legacy Trainer Publish Risk Review

Generated: 2026-05-12T16:50:13Z

Status: `PUBLISH_PATH_REQUIRES_OPERATOR_DECISION`

Classifications:

- `LEGACY_PROPOSAL_PUBLISH_OBSERVED`
- `LEGACY_SIGNAL_PUBLISH_OBSERVED`
- `LEGACY_TRADER_CONSUMER_OBSERVED`
- `EXECUTION_FEEDBACK_AFTER_RESTART_OBSERVED`
- `EXCHANGE_ORDER_AFTER_RESTART_OBSERVED`
- `PUBLISH_PATH_REQUIRES_OPERATOR_DECISION`

Key stream deltas over 31 samples from 2026-05-12T16:09:21Z to 2026-05-12T16:39:29Z:

| Stream | First XLEN | Last XLEN | Delta | Fresh observed | Best latest id | Best age seconds |
|---|---:|---:|---:|---|---|---:|
| wma:trainer:predictions | 0 | 0 | 0 | False | `None` | None |
| wma:proposals | 50000 | 50187 | 187 | True | `1778603004986-0` | 0 |
| signals:trading | 0 | 0 | 0 | False | `None` | None |
| signals:trading:primary | 50000 | 50000 | 0 | True | `1778602212078-0` | 9 |
| signals:trading:asjad | 200 | 200 | 0 | False | `1770275879664-0` | 8326281 |
| executed_signals | 1918 | 1920 | 2 | True | `1778602997962-0` | 7 |

Observed exchange order id in `executed_signals`: `49654220167`.

This task did not write Redis and did not place, cancel, or modify exchange orders. The observed publish/execution activity came from already-running legacy processes.
