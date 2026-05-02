# Requirement 0005 - Startup Script and Runtime Service Map Source of Truth

The legacy production startup script and actual running services are source-of-truth for Phase 2 core rebuild planning.

Primary legacy script:
`/home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh`

Rules:
- Read only.
- Do not execute.
- Map all phases and service dependencies.
- Include actual running services.
- Include missing services.
- Include extra services such as monitor_trainer_prices.py if running but not in script.
- Use service map to plan V2 replacements/wrappers/parity modules.

REQ_STARTUP_SCRIPT_RUNTIME_MAP_READY
