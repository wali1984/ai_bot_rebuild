"""Legacy log intelligence read-only service."""
from .service import (
    LEGACY_BOT_ROOT,
    LEGACY_SCRIPTS_DIR,
    LEGACY_LOGS_DIR,
    discover_legacy_sources,
    observe_once,
    parse_trainer_log_tail,
    parse_orchestrator_log_tail,
    inspect_monitor_script,
    enrich_comparison,
    remediation_hints_from_summary,
)

__all__ = [
    "LEGACY_BOT_ROOT",
    "LEGACY_SCRIPTS_DIR",
    "LEGACY_LOGS_DIR",
    "discover_legacy_sources",
    "observe_once",
    "parse_trainer_log_tail",
    "parse_orchestrator_log_tail",
    "inspect_monitor_script",
    "enrich_comparison",
    "remediation_hints_from_summary",
]
