# Config Admin Coverage

- marker: `PROFESSIONAL_OPERATOR_GUI_AND_DECISION_EXPLAINABILITY_READY`
- generated_at: `2026-05-09T18:24:30.839656+00:00`
- live_gate_status: `blocked_human_only`
- git_head: `c7ef000 Build professional operator GUI decision explainability cockpit`

## Evidence

- `operator_cockpit_payload.json`
- `non_live_operational_proof/latest`
- `historical_30d_replay_and_paper_proof/latest`
- `agent_supervisor/status`
- `legacy_readonly_audit`

## Data Gaps

- `confidence_calibration`
- `confidence_delta`
- `liquidity_score`
- `model_checkpoint`
- `old_confidence`
- `open_interest_score`
- `volatility_score`
- `volume_score`

## Settings

- `trainer confidence threshold`: requires validation
- `model checkpoint`: read-only
- `symbol universe`: requires validation
- `daily loss limit`: requires explicit human approval
- `leverage`: requires explicit human approval
- `margin mode`: requires explicit human approval
- `stop policy`: requires validation
- `hedge/DCA`: requires explicit human approval
- `paper/live mode`: read-only
- `API key status`: read-only
- `kill switch`: requires explicit human approval
