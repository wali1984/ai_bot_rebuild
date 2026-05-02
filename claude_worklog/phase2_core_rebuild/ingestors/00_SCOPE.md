# Phase 2A Ingestor Preservation Scope

This task inventories and hashes known legacy ingestors without modifying the live legacy bot.

Actions performed:
- Located known ingestor and feature pipeline sources.
- Copied `live_coinank.py` as-is into V2 preservation space.
- Verified original and copied `live_coinank.py` SHA256 hashes match.
- Recorded config symbol source names and counts only.

Forbidden actions respected:
- No writes to `/home/wali/Desktop/AI BOT`.
- No Redis writes or deletes.
- No ingestor execution.
- No service restarts.
- No secrets written.

PHASE2_INGESTOR_COPY_HASH_SCOPE_READY
