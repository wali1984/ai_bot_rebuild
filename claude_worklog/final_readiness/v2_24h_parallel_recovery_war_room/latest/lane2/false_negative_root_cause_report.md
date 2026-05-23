# V2 False-Negative Root-Cause Report (analysis-only)

live_gate=blocked_human_only. live_symbols=[]. approves_live=false.

false_negative_count: 6

## Cause counts

- altdata_missing: 6
- observation_gap: 6
- paper_fill_gate_block: 6
- paper_fill_gate_block_unrecorded_reason: 6

## Per-bundle classifications

### BTCUSDT @ BTCUSDT:1m:2026-05-23T07:32:33Z
- prediction_id: v2_native_pred_d7405570556139ba92d58dc92e542514_219a2190e2b0ebb8
- expected_move_after_cost_bps: 108.56573370692621
- outcome_after_cost: 13.521622377145906
- trainer_selected_action: long
- altdata_snapshot_present: False
- root_causes: ['paper_fill_gate_block', 'paper_fill_gate_block_unrecorded_reason', 'observation_gap', 'altdata_missing']
  - note: paper_fill_allowed=false with empty paper_fill_gate_block_reasons — block reason is not observable from the bundle
  - note: altdata_snapshot is null
  - note: paper intent recorded as SHADOW_OBSERVATION_ONLY — fill path was not exercised even though risk/edge cleared

### SOLUSDT @ SOLUSDT:1m:2026-05-23T08:42:33Z
- prediction_id: v2_native_pred_e86cd804d4fa791177f4fb402f9d5992_219a2190e2b0ebb8
- expected_move_after_cost_bps: 80.62953958840102
- outcome_after_cost: 18.69750367107293
- trainer_selected_action: long
- altdata_snapshot_present: False
- root_causes: ['paper_fill_gate_block', 'paper_fill_gate_block_unrecorded_reason', 'observation_gap', 'altdata_missing']
  - note: paper_fill_allowed=false with empty paper_fill_gate_block_reasons — block reason is not observable from the bundle
  - note: altdata_snapshot is null
  - note: paper intent recorded as SHADOW_OBSERVATION_ONLY — fill path was not exercised even though risk/edge cleared

### BTCUSDT @ BTCUSDT:1m:2026-05-23T09:40:33Z
- prediction_id: v2_native_pred_b94814c3a447d7da858fe9f3fc8db5ed_219a2190e2b0ebb8
- expected_move_after_cost_bps: 108.56573370692621
- outcome_after_cost: 1.1441424841954397
- trainer_selected_action: long
- altdata_snapshot_present: False
- root_causes: ['paper_fill_gate_block', 'paper_fill_gate_block_unrecorded_reason', 'observation_gap', 'altdata_missing']
  - note: paper_fill_allowed=false with empty paper_fill_gate_block_reasons — block reason is not observable from the bundle
  - note: altdata_snapshot is null
  - note: paper intent recorded as SHADOW_OBSERVATION_ONLY — fill path was not exercised even though risk/edge cleared

### SOLUSDT @ SOLUSDT:1m:2026-05-23T12:51:34Z
- prediction_id: v2_native_pred_1b149421eba72000b5ce3295b279e489_219a2190e2b0ebb8
- expected_move_after_cost_bps: 79.58064189921629
- outcome_after_cost: 11.20830298616238
- trainer_selected_action: long
- altdata_snapshot_present: False
- root_causes: ['paper_fill_gate_block', 'paper_fill_gate_block_unrecorded_reason', 'observation_gap', 'altdata_missing']
  - note: paper_fill_allowed=false with empty paper_fill_gate_block_reasons — block reason is not observable from the bundle
  - note: altdata_snapshot is null
  - note: paper intent recorded as SHADOW_OBSERVATION_ONLY — fill path was not exercised even though risk/edge cleared

### SOLUSDT @ SOLUSDT:1m:2026-05-23T13:42:19Z
- prediction_id: v2_native_pred_b2f2188bb8df79726b63573646322ecf_219a2190e2b0ebb8
- expected_move_after_cost_bps: 58.558119822133236
- outcome_after_cost: 12.270143321690544
- trainer_selected_action: long
- altdata_snapshot_present: False
- root_causes: ['paper_fill_gate_block', 'paper_fill_gate_block_unrecorded_reason', 'observation_gap', 'altdata_missing']
  - note: paper_fill_allowed=false with empty paper_fill_gate_block_reasons — block reason is not observable from the bundle
  - note: altdata_snapshot is null
  - note: paper intent recorded as SHADOW_OBSERVATION_ONLY — fill path was not exercised even though risk/edge cleared

### SOLUSDT @ SOLUSDT:1m:2026-05-23T13:49:34Z
- prediction_id: v2_native_pred_37403f58e1401e5a4306e275e4783a9a_219a2190e2b0ebb8
- expected_move_after_cost_bps: 48.64078662443205
- outcome_after_cost: 1.4073985106885871
- trainer_selected_action: long
- altdata_snapshot_present: False
- root_causes: ['paper_fill_gate_block', 'paper_fill_gate_block_unrecorded_reason', 'observation_gap', 'altdata_missing']
  - note: paper_fill_allowed=false with empty paper_fill_gate_block_reasons — block reason is not observable from the bundle
  - note: altdata_snapshot is null
  - note: paper intent recorded as SHADOW_OBSERVATION_ONLY — fill path was not exercised even though risk/edge cleared

