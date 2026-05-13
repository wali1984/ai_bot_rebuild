# Website Signal and Prediction Visibility Review

Generated: 2026-05-13T04:22:07.783209Z

Classification: `PAYLOAD_WIRED_PRIOR_ROUTE_CRAWL_VALID_BUT_BROWSER_RECRAWL_NOT_RUN_THIS_TURN`

Evidence:
- v2/frontend/src/components/layout/PageShell.tsx references lineage_ids.prediction_id and feature_snapshot_id
- v2/frontend/src/components/layout/AdminShell.tsx reads current_risk_decision from paper runtime
- v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json contains current pred_*/fs_*/sig_*/risk_* IDs

Current runtime IDs visible in payload:
- prediction_id: `pred_paper_tick_1778646096231`
- feature_snapshot_id: `fs_paper_tick_1778646096231`
- signal_id: `sig_paper_tick_1778646096231`
- risk_decision_id: `risk_paper_tick_1778646096231`

Caveat: No public/local browser crawl was run in this reconciliation turn; prior production website crawl remains the latest route-level evidence.
