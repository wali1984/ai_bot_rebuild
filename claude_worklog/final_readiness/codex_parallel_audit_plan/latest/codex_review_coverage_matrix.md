# Codex Review Coverage Matrix

- `codex_review_enterprise_ui_polish_quality`: TradingView primary, fallback-only old chart, no placeholder pages
- `codex_parallel_review_claude_design_handoff_enterprise_ui`: Claude Design handoff ingestion, route wiring, payload truthfulness, safety banners, Monitor Center, Trainer Prediction Monitor, Signal Explainability, Config Admin, no placeholder-only UI
- `codex_review_realtime_monitor_coverage`: real legacy runtime data, no Redis writes, truthful gaps
- `codex_review_v2_data_plane_independence`: bounded Redis, durable storage, no legacy writes
- `codex_review_risk_gateway_degraded_state_fail_closed`: stale/missing attribution, leverage/margin, kill switch
- `codex_review_trainer_prediction_explainability`: prediction_id, feature_snapshot_id, checkpoint, confidence, freshness
- `codex_review_system_atlas_delta`: no unsafe_unknown or unmapped exchange/Redis/runtime regressions
- `codex_review_paper_shadow_replay_truthfulness`: fixture vs continuous runtime separation and PnL assumptions
