# Phase 2X External Manual Position Quarantine Spec

`ManualPositionFlag` is a frozen slots dataclass whose state is either `manual_position_quarantined` or `manual_position_not_present`. Both states require `live_blocked is True`.

`ExternalPositionQuarantineRecord` is a frozen slots dataclass carrying:
- `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`
- `symbol`, `risk_decision_ts_ms`
- `manual_position_flag`
- `model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `trainer_worker_liveness`
- `live_blocked`

`assemble_external_position_quarantine_record` accepts keyword-only inputs and returns a new quarantine record derived from a `RiskDecisionRecord` plus trainer-parity fields.

`build_external_position_quarantine_runtime` validates `now_ms_clock` is callable, does not invoke it at build time, and invokes it exactly once per runtime call as a non-live runtime boundary check.

PHASE_2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_SPEC_READY
