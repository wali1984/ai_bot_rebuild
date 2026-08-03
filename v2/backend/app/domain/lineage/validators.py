"""Lineage chain validators.  Pure functions; no I/O.

Enforces that every actionable signal carries the complete 7-ID chain before
it is allowed to propagate downstream.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .chain import MINIMUM_ACTIONABLE_IDS, REQUIRED_LINEAGE_IDS


def validate_lineage_ids(lineage_ids: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, missing_fields).

    ok=True only when every REQUIRED_LINEAGE_ID is present (non-null, non-empty).
    """
    missing = [f for f in REQUIRED_LINEAGE_IDS if not lineage_ids.get(f)]
    return (len(missing) == 0), missing


def validate_minimum_actionable_ids(lineage_ids: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """Return (ok, missing_fields) for the minimum set needed for actionability.

    paper_ledger_entry_id is not required here — it's attached after fill.
    """
    missing = [f for f in MINIMUM_ACTIONABLE_IDS if not lineage_ids.get(f)]
    return (len(missing) == 0), missing


def assert_actionable_has_lineage(signal: Mapping[str, Any]) -> None:
    """Raise ValueError if a signal marked actionable=True is missing required lineage IDs.

    Call this in tests and at signal publication boundaries.
    """
    if not signal.get("actionable"):
        return
    ids = dict(signal.get("lineage_ids") or {})
    for field in MINIMUM_ACTIONABLE_IDS:
        ids.setdefault(field, signal.get(field))
    ok, missing = validate_minimum_actionable_ids(ids)
    if not ok:
        raise ValueError(
            f"Actionable signal is missing required lineage IDs: {missing}. "
            f"signal_id={signal.get('signal_id')!r} prediction_id={signal.get('prediction_id')!r}"
        )
