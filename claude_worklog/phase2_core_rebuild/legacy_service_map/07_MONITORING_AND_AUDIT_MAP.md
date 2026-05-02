# Monitoring and Audit Map

Running monitors:
- `scripts/memory_monitor.py`
- `scripts/monitor_trainer_predictions.py`
- extra runtime process `scripts/monitor_trainer_prices.py`

Startup monitors currently absent:
- `vpn_monitor.py`
- `system_telegram_monitor.py`
- `monitor_system_memory.py`
- GNOME monitoring terminals
- portfolio monitors

V2 strategy:
- Preserve read-only monitoring evidence.
- Replace shell/terminal-only monitors with evidence packets, dashboard panels, and audit ledger records.
- No monitor may restart services, mutate Redis, or place/cancel orders.

MONITORING_AND_AUDIT_MAP_READY
