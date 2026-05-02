# Missing and Extra Process Analysis

Startup-script expected but not currently running:
- `vpn_monitor.py`
- `system_telegram_monitor.py`
- `monitor_system_memory.py`
- `trading/trader-asjad.py`
- `monitor_portfolio_primary.py`
- `monitor_portfolio_asjad.py`
- `scripts/paralysis_detectors.py`
- `scripts/validate_symbol_universe_data.py`
- `scripts/health_probe.py`

Currently running but not referenced by startup script:
- `scripts/monitor_trainer_prices.py`
- `scripts/ingestors_watchdog.py`

Explanation:
- `scripts/monitor_trainer_prices.py` is an extra runtime monitor and should be included in V2 monitoring inventory.
- Missing startup monitors are not failures for V2; they must be documented and replaced/preserved through read-only monitoring design.
- Deprecated/removed services should not be reintroduced blindly.

MISSING_AND_EXTRA_PROCESS_ANALYSIS_READY
