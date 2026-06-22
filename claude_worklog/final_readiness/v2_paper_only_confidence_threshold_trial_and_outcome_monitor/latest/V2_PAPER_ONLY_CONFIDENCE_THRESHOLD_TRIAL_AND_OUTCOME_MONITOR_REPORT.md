# V2 Paper Only Confidence Threshold Trial And Outcome Monitor Report

Gate: `V2_PAPER_ONLY_CONFIDENCE_THRESHOLD_TRIAL_AND_OUTCOME_MONITOR_READY`
Generated EST: `2026-06-10T21:02:51-04:00`
Prediction rows: `665`
Paper allowed before: `21`
Trial candidates: `15`
Trial promoted signals: `15`
Paper threshold: `0.54`
Paper loop run: `True`
Paper equity: `10030.41842727`
Paper PnL: `30.41842727`
Live gate: `enabled_operator_approved`
Trader state: `LIVE_ARMED_BALANCE_HOLD`
Live submit blocker: `INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER`
Live threshold changed: `False`

## Result

The 0.54 confidence threshold is applied only as a guarded paper/shadow trial.
Rows must have clean market-state integrity, positive after-cost expected move,
fresh features, valid price targets, and deterministic paper-only lineage.
Live thresholds, live risk, leverage, margin, and exchange execution remain
unchanged.

## Blockers

- none

## Validation

- `python -m py_compile`: PASS
- focused backend tests: PASS, `9 passed`
- frontend typecheck: PASS
- frontend build: PASS, latest asset `index-Dnxuhzu_.js`
- local route crawl: PASS, `32/32`, repair flags `0`
- production route crawl: PASS with caveat, `32/32`, one production-only mission-control repair marker remains
- rendered bad-marker scan: PASS, `0` target hits
- exchange mutation scan: PASS, display-only safety text only
- old Redis scan: PASS, touched runtime writes are `v2:` paper trial/status keys only
- raw secret scan: PASS

Safety: no real order/test-order/cancel/modify, no leverage or margin mutation,
no old Redis write, no legacy restart, no Redis trim, no raw credential output,
and no live threshold change.
