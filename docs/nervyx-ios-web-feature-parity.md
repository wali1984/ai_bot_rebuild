# NERVYX iOS/Web Feature Parity

| Feature | Web route | iOS screen | Status | Notes |
| --- | --- | --- | --- | --- |
| Welcome/onboarding | public landing/login | LoginView | partial | NERVYX ONE login present; onboarding remains lightweight |
| Login | /login | LoginView | yes | Backend auth preserved |
| Public status | /status | Dashboard/Monitor summary | partial | iOS uses mobile health/status summaries |
| Markets | /markets /market/:symbol | not yet full native detail | partial | mobile dashboard focuses current summaries |
| Signals | /signals | SignalsView | yes | Typed MobileSignal fields preserved |
| Dashboard | /dashboard | DashboardView | yes | NERVYX module labels added |
| Trade terminal | /trade | PaperTradingView | partial | paper/read-only summary; no live submit added |
| Portfolio/positions | /portfolio | PositionsView | yes | Typed MobilePosition fields preserved |
| Executions/orders | /portfolio/executions | PaperTradingView summary | partial | paper lifecycle summary preserved |
| Alerts | /alerts | AlertsView | yes | Typed MobileAlert fields preserved |
| Admin overview | /admin | AdminDashboardView | yes | Backend admin gate preserved |
| Risk | /admin/risk | RiskControlView | yes | No mobile live approval |
| Monitor/system health | /admin/monitor-center | MonitorView | yes | Existing health models preserved |
