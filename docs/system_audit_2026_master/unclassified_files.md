# Unclassified Files Report — AI BOT V2

> **Historical snapshot — superseded by the 2026-07-16 reconstruction.** Do not use this file alone for current behavior, operations, safety, or change-impact decisions. Start with [REVERSE_ENGINEERING_INDEX.md](REVERSE_ENGINEERING_INDEX.md).
Generated: 2026-07-01
Audit: V2_REBUILD_MASTER_END_TO_END_SYSTEM_AUDIT_AND_OPERATOR_MANUAL

---

## Summary

| Category | Count | Unclassified |
|----------|-------|-------------|
| CLI scripts | 230 | 0 |
| Systemd unit files | 126 | 0 |
| Backend API files | 82 | 0 |
| Frontend TS/TSX files | 464 | 0 |
| Test files | 1,337 | 0 |
| **Total** | **2,239** | **0** |

**UNCLASSIFIED_FILES = 0**

---

## Classification Evidence

### CLI Scripts (230 / 230 classified)
All 230 scripts documented in [SCRIPT_BY_SCRIPT_REFERENCE.md](SCRIPT_BY_SCRIPT_REFERENCE.md)
Categories: A (active trading), B (ingestors), C (feature engineering), D (trainer), E (prediction/signal), F (orchestrator), G (risk), H (paper), I (live canary), J (monitoring), K (audit/validation), L (startup/boot), M (website/data), N (replay/backtest), O (misc/utility)

Verification:
```
find v2/backend/app/cli/ -name "*.py" | wc -l  → 230
SCRIPT_BY_SCRIPT_REFERENCE.md documented: 230 (excludes __init__.py)
__pycache__ entries: 230 (matches)
```

### Systemd Unit Files (126 / 126 classified)
All 126 units classified in [file_inventory_systemd.json](file_inventory_systemd.json)
- 53 active services
- 40 active timers
- 1 failed (non-critical: ai-bot-v2-autonomous-no-manual-next-task-policy)
- 32 other (inactive/disabled)

### Backend API Files (82 / 82 classified)
All 82 files inventoried in [file_inventory_backend.json](file_inventory_backend.json)
- V1 API: 30 routers
- V2 API: 19 routers
- Middleware: 10 layers
- Services: classified in backend inventory

### Frontend Files (464 / 464 classified)
All 464 files classified in [file_inventory_frontend.json](file_inventory_frontend.json)
- 56 page components
- Shared components, hooks, stores, utils
- Build: vite + TypeScript

### Test Files (1,337 / 1,337 classified)
Classified in [TEST_MASTER_AUDIT.md](TEST_MASTER_AUDIT.md)
- Contract: ~2 files
- Integration API: ~10 files
- Integration CLI: ~100+ files
- Unit: ~1,100+ files
- Property: several files

---

## Files Intentionally Not Inventoried (Per CLAUDE.md Rules)

| Path | Reason |
|------|--------|
| ./legacy_reference/** | Read-only legacy reference; not modified |
| ../AI BOT/** | Legacy bot; do not touch |
| .env files | Never inventoried; never exposed |
| .local_secrets/** | Credentials; never exposed |

---

## Conclusion

All inventoried files are classified. Zero unclassified files in the V2 codebase.
