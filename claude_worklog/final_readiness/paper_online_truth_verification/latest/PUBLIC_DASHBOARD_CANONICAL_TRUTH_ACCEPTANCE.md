# Public Dashboard Canonical Truth Acceptance

| Scope | Route | HTTP | Pass | Trainer | Lineage | Prediction | Live block | Static primary | hist as current | Console | Blocking network | Benign warnings | Screenshot |
|---|---|---:|---|---|---|---|---|---|---|---:|---:|---:|---|
| public | /admin/mission-control?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 1 | screenshots/public/admin_mission_control_role_admin.png |
| public | /admin/trainer-prediction-monitor?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 0 | screenshots/public/admin_trainer_prediction_monitor_role_admin.png |
| public | /admin/signal-explainability?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 0 | screenshots/public/admin_signal_explainability_role_admin.png |
| public | /admin/risk-control?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 0 | screenshots/public/admin_risk_control_role_admin.png |
| public | /admin/paper-trading?role=admin | 200 | yes | yes | yes | yes | yes | no | no | 0 | 0 | 0 | screenshots/public/admin_paper_trading_role_admin.png |

Known benign warning: TradingView widget-sheriff aborted requests are recorded as warnings only when the route still shows canonical V2 paper runtime truth.

Verdict: PASS

Public dashboard payload check: fresh canonical truth visible
