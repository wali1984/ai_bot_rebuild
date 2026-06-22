from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from v2.backend.app.composition.current_signal_lineage_adapter.runtime import REQUIRED_LINEAGE_IDS


SIGNAL_LINEAGE_STATUS_SCHEMA_VERSION = "v2_signal_lineage_status_v1"


def build_signal_lineage_status(
    *,
    current_lineage_payload: Mapping[str, Any] | None = None,
    historical_index_payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    current = dict(current_lineage_payload or {})
    historical = dict(historical_index_payload or {})
    lineage_ids = current.get("lineage_ids")
    if not isinstance(lineage_ids, Mapping):
        lineage_ids = {}
    missing_ids = [field for field in REQUIRED_LINEAGE_IDS if not lineage_ids.get(field)]
    historical_records = historical.get("records")
    historical_count = len(historical_records) if isinstance(historical_records, list) else 0
    blockers = []
    if missing_ids:
        blockers.append("current_lineage_ids_missing")

    return {
        "schema_version": SIGNAL_LINEAGE_STATUS_SCHEMA_VERSION,
        "classification": "V2_SIGNAL_LINEAGE_READY"
        if not blockers
        else "V2_SIGNAL_LINEAGE_PARTIAL",
        "source": "v2.backend.app.services.signal_lineage",
        "required_lineage_ids": list(REQUIRED_LINEAGE_IDS),
        "missing_ids": missing_ids,
        "historical_aggregate_index": {
            "available": historical_count > 0 or bool(historical),
            "record_count": historical_count,
            "source": historical.get("source") or "v2_signal_lineage_worker",
        },
        "current_lineage_classification": current.get("classification"),
        "blockers": blockers,
        "live_safety": {
            "live_gate": "blocked_human_only",
            "live_symbols": [],
            "trader_execution_enabled": False,
            "places_real_order": False,
            "exchange_action_taken": False,
            "writes_exchange_orders": False,
            "writes_legacy_redis": False,
        },
    }
