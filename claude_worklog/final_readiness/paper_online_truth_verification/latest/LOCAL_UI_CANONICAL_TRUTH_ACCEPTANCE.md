# Local UI Canonical Truth Acceptance

| Scope | Route | HTTP | Pass | Trainer | Lineage | Prediction | Live block | Static primary | hist as current | Console | Blocking network | Benign warnings | Screenshot |
|---|---|---:|---|---|---|---|---|---|---|---:|---:|---:|---|
| local | /admin/mission-control?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 1 | screenshots/local/admin_mission_control_role_admin.png |
| local | /admin/trainer-prediction-monitor?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 0 | screenshots/local/admin_trainer_prediction_monitor_role_admin.png |
| local | /admin/signal-explainability?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 0 | screenshots/local/admin_signal_explainability_role_admin.png |
| local | /admin/risk-control?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 0 | screenshots/local/admin_risk_control_role_admin.png |
| local | /admin/paper-trading?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 0 | screenshots/local/admin_paper_trading_role_admin.png |

Known benign warning: TradingView widget-sheriff aborted requests are recorded as warnings only when the route still shows canonical V2 paper runtime truth.

Verdict: PASS
