# Phase 2 Legacy Service Map Scope and Safety

Generated: 2026-05-02T06:19:17.031987+00:00

Objective: deterministically map the live legacy production runtime to V2 preservation/parity rebuild modules.

Safety boundaries:
- Read `/home/wali/Desktop/AI BOT` only.
- Do not execute `scripts/start_all_services_production.sh`.
- Do not write Redis.
- Do not restart, kill, or modify live services.
- Do not place/cancel orders or enable live trading.
- Do not expose secrets.

Primary source of truth:
- `/home/wali/Desktop/AI BOT/scripts/start_all_services_production.sh`
- current process table
- `legacy_reference/`
- preservation policies and Phase 2 artifacts

PHASE2_LEGACY_SERVICE_MAP_SCOPE_READY
