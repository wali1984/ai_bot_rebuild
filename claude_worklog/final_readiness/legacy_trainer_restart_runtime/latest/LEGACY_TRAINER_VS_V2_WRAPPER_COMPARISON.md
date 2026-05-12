# Legacy Trainer vs V2 Wrapper Comparison

Generated: 2026-05-12T16:50:13Z

Overall classification: `LEGACY_AND_V2_BOTH_CURRENT_BUT_NOT_PARITY`

| Field | Legacy trainer after restart | V2 paper wrapper |
|---|---|---|
| Source | `LEGACY_TRAINER_LOG_READONLY` | `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json` |
| Age seconds | `2` | `9` |
| Symbol | `ALICEUSDT` | `BTCUSDT` |
| Timeframe | `15m` | `1m` |
| prediction_id | `None` | `pred_paper_tick_1778604604851` |
| feature_snapshot_id | `None` | `fs_paper_tick_1778604604851` |
| checkpoint | `None` | `v2_paper_readonly_momentum_wrapper_v1` |
| confidence | `0.6154` | `0.8` |
| parity | `not proven` | `paper wrapper current` |

Full parity is not claimed. The two paths are both runtime-current, but they are not equivalent evidence.
