# V2 vs Legacy Model + Signal Gap Matrix (war-room cycle)

Generated: 2026-05-18T05:55:22Z

## Aggregated classification counts

- ALT_DATA_PROVIDER_FORBIDDEN_OR_MISSING: 6
- CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED: 1
- FULL_OBSERVATION_PARTIAL: 3
- MISSING_LEGACY_LOG_ACTION_EVIDENCE: 3
- PAPER_FILL_GATE_STRICT_BLOCK: 1
- V2_POSITION_HISTORY_FLAT: 1
- V2_POSITION_HISTORY_MISSING: 2

## Per-symbol classifications

### BTCUSDT

- v2_prediction_present: True
- selected_action: hold
- paper_fill_allowed: True
- feature_freshness_state: CURRENT
- price_track_state: OPEN_MISSING_PRICE_INPUTS
- price_track_missing_flags: ['MISSING_ENTRY_PRICE']
- nansen_payload_present: False
- lunarcrush_payload_present: False
- held_by_paper_fill_gate: False
- held_block_reasons: []
- checkpoint_blocker: None
- classifications:
  - ALT_DATA_PROVIDER_FORBIDDEN_OR_MISSING:lunarcrush_payload_missing
  - ALT_DATA_PROVIDER_FORBIDDEN_OR_MISSING:nansen_payload_missing
  - FULL_OBSERVATION_PARTIAL
  - MISSING_LEGACY_LOG_ACTION_EVIDENCE
  - V2_POSITION_HISTORY_MISSING:MISSING_ENTRY_PRICE

### ETHUSDT

- v2_prediction_present: True
- selected_action: hold
- paper_fill_allowed: True
- feature_freshness_state: CURRENT
- price_track_state: OPEN_MISSING_PRICE_INPUTS
- price_track_missing_flags: ['MISSING_ENTRY_PRICE']
- nansen_payload_present: False
- lunarcrush_payload_present: False
- held_by_paper_fill_gate: False
- held_block_reasons: []
- checkpoint_blocker: None
- classifications:
  - ALT_DATA_PROVIDER_FORBIDDEN_OR_MISSING:lunarcrush_payload_missing
  - ALT_DATA_PROVIDER_FORBIDDEN_OR_MISSING:nansen_payload_missing
  - FULL_OBSERVATION_PARTIAL
  - MISSING_LEGACY_LOG_ACTION_EVIDENCE
  - V2_POSITION_HISTORY_MISSING:MISSING_ENTRY_PRICE

### SOLUSDT

- v2_prediction_present: True
- selected_action: hold
- paper_fill_allowed: False
- feature_freshness_state: CURRENT
- price_track_state: FLAT
- price_track_missing_flags: ['FLAT_NO_OPEN_POSITION']
- nansen_payload_present: False
- lunarcrush_payload_present: False
- held_by_paper_fill_gate: True
- held_block_reasons: ['EDGE_AFTER_COST_BELOW_THRESHOLD_BLOCK']
- checkpoint_blocker: CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED
- classifications:
  - ALT_DATA_PROVIDER_FORBIDDEN_OR_MISSING:lunarcrush_payload_missing
  - ALT_DATA_PROVIDER_FORBIDDEN_OR_MISSING:nansen_payload_missing
  - CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED
  - FULL_OBSERVATION_PARTIAL
  - MISSING_LEGACY_LOG_ACTION_EVIDENCE
  - PAPER_FILL_GATE_STRICT_BLOCK:EDGE_AFTER_COST_BELOW_THRESHOLD
  - V2_POSITION_HISTORY_FLAT:NO_OPEN_POSITION

## Safety

- legacy evidence consumed as current truth: false
- invented outcomes: false
- missing provider data converted to numeric score: false
- gate: blocked_human_only
- symbols_real: []
- writes_legacy_redis: false
- writes_exchange_orders: false
