# Config Admin UI Coverage

Config Admin renders safety-classified settings:

- `live_trading_enabled`: requires human approval
- `exchange_order_methods`: read-only disabled
- `paper_shadow_runtime`: requires validation
- `manual_external_quarantine`: safe display-only setting

Live-impacting changes remain blocked and human-approved only.

CONFIG_ADMIN_UI_COVERAGE_READY
