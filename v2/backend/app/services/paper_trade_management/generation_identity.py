"""Deterministic paper-position entry generation identity helpers.

Signal and prediction identifiers may legitimately recur across decision cycles.
They identify lineage, not a particular economic entry.  These helpers combine
the strongest available source-fill identity with the normalized entry timestamp
and immutable entry dimensions so a reopened symbol becomes a new generation.

The module is pure and paper-only.  It performs no I/O and has no exchange path.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

POSITION_ID_VERSION = "PAPER_POSITION_GENERATION_V1"

_ENTRY_TIME_FIELDS = (
    "fill_time_utc",
    "fill_time",
    "fill_price_utc",
    "accepted_at_utc",
    "entry_price_utc",
    "entry_time",
    "opened_est",
    "decision_time",
    "generated_utc",
    "fill_time_est",
    "accepted_at_est",
    "generated_est",
)

_EXIT_TIME_FIELDS = (
    "exit_price_utc",
    "exit_time",
    "closed_at",
    "generated_utc",
)

_STRONG_ID_FIELDS = (
    "entry_fill_id",
    "fill_id",
    "paper_fill_id",
    "ledger_row_id",
    "intent_id",
)

_LINEAGE_ID_FIELDS = (
    "entry_signal_id",
    "signal_id",
    "entry_prediction_id",
    "prediction_id",
    "source_prediction_id",
    "trainer_prediction_id",
)


def _first_present(row: Mapping[str, Any], fields: Sequence[str]) -> Any:
    for field in fields:
        value = row.get(field)
        if value not in (None, ""):
            return value
    return None


def normalize_timestamp(value: Any) -> str | None:
    """Return a comparable UTC ISO timestamp, or ``None`` when invalid."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def entry_timestamp(row: Mapping[str, Any]) -> str | None:
    return normalize_timestamp(_first_present(row, _ENTRY_TIME_FIELDS))


def exit_timestamp(row: Mapping[str, Any]) -> str | None:
    return normalize_timestamp(_first_present(row, _EXIT_TIME_FIELDS))


def identity_values(row: Mapping[str, Any], fields: Sequence[str]) -> set[str]:
    values: set[str] = set()
    for field in fields:
        value = row.get(field)
        if isinstance(value, list | tuple | set):
            values.update(str(item) for item in value if item not in (None, ""))
        elif value not in (None, ""):
            values.add(str(value))
    return values


def strong_identity_values(row: Mapping[str, Any]) -> set[str]:
    values = identity_values(row, _STRONG_ID_FIELDS)
    values.update(identity_values(row, ("source_fill_ids",)))
    return values


def lineage_identity_values(row: Mapping[str, Any]) -> set[str]:
    return identity_values(row, _LINEAGE_ID_FIELDS)


def source_fill_identity(row: Mapping[str, Any], *, fallback: Any = None) -> str | None:
    """Return the entry-anchoring fill identity without treating lineage as unique."""
    value = _first_present(row, _STRONG_ID_FIELDS)
    if value not in (None, ""):
        return str(value)
    source_fill_ids = row.get("source_fill_ids")
    if isinstance(source_fill_ids, list | tuple):
        for item in source_fill_ids:
            if item not in (None, ""):
                return str(item)
    if fallback not in (None, ""):
        return str(fallback)
    value = _first_present(row, _LINEAGE_ID_FIELDS)
    return str(value) if value not in (None, "") else None


@dataclass(frozen=True)
class EntryGenerationIdentity:
    generation_id: str
    source_identity: str | None
    entry_time_utc: str | None
    complete: bool


def entry_generation_identity(
    row: Mapping[str, Any],
    *,
    source_identity_override: Any = None,
) -> EntryGenerationIdentity:
    """Build a stable identity for one economic entry generation.

    ``complete`` means both an entry source and a real entry timestamp were
    present.  Incomplete identities remain useful for deterministic legacy
    aliases, but must not be used alone to suppress a future re-entry.
    """
    source_identity = source_fill_identity(row, fallback=source_identity_override)
    entry_time_utc = entry_timestamp(row)
    side = str(
        _first_present(row, ("side", "selected_action", "action", "position_side"))
        or ""
    ).strip().lower()
    if side == "buy":
        side = "long"
    elif side == "sell":
        side = "short"
    payload = {
        "version": POSITION_ID_VERSION,
        "source_identity": source_identity or "MISSING_SOURCE_IDENTITY",
        "entry_time_utc": entry_time_utc or "MISSING_ENTRY_TIME",
        "symbol": str(row.get("symbol") or "").strip().upper(),
        "timeframe": str(row.get("timeframe") or "").strip().lower(),
        "side": side,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return EntryGenerationIdentity(
        generation_id=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        source_identity=source_identity,
        entry_time_utc=entry_time_utc,
        complete=bool(source_identity and entry_time_utc),
    )


def closed_generation_match(
    accepted_row: Mapping[str, Any],
    closed_row: Mapping[str, Any],
    *,
    accepted_source_identity: Any = None,
) -> dict[str, Any] | None:
    """Return suppression evidence only when the same entry generation closed.

    New-format rows match their explicit generation ID.  Legacy rows require
    strong fill identity plus temporal evidence.  Reusable signal/prediction
    lineage is considered only when an accepted entry occurred no later than
    the recorded close; a later entry is always a new generation.
    """
    accepted_generation = entry_generation_identity(
        accepted_row,
        source_identity_override=accepted_source_identity,
    )
    accepted_explicit = accepted_row.get("position_generation_id")
    closed_explicit = closed_row.get("position_generation_id")
    if (
        accepted_explicit not in (None, "")
        and closed_explicit not in (None, "")
        and str(accepted_explicit) == str(closed_explicit)
    ):
        return {
            "match_type": "EXPLICIT_POSITION_GENERATION_ID",
            "position_generation_id": str(accepted_explicit),
        }

    closed_generation = entry_generation_identity(closed_row)
    if (
        closed_explicit not in (None, "")
        and accepted_generation.complete
        and accepted_generation.generation_id == str(closed_explicit)
    ):
        return {
            "match_type": "DERIVED_ACCEPTED_TO_EXPLICIT_CLOSED_GENERATION",
            "position_generation_id": str(closed_explicit),
        }
    if (
        accepted_generation.complete
        and closed_generation.complete
        and accepted_generation.generation_id == closed_generation.generation_id
    ):
        return {
            "match_type": "DERIVED_ENTRY_GENERATION_ID",
            "position_generation_id": accepted_generation.generation_id,
        }

    accepted_time = accepted_generation.entry_time_utc
    closed_entry_time = closed_generation.entry_time_utc
    closed_exit_time = exit_timestamp(closed_row)
    strong_overlap = sorted(
        strong_identity_values(accepted_row) & strong_identity_values(closed_row)
    )
    if accepted_source_identity not in (None, ""):
        accepted_strong = strong_identity_values(accepted_row) | {
            str(accepted_source_identity)
        }
        strong_overlap = sorted(accepted_strong & strong_identity_values(closed_row))

    if strong_overlap:
        if accepted_time and closed_exit_time and accepted_time > closed_exit_time:
            return None
        if accepted_time and closed_entry_time and accepted_time != closed_entry_time:
            # A reused strong id with a different entry timestamp is a distinct
            # generation unless it is an old replay that predates the close.
            if closed_exit_time and accepted_time <= closed_exit_time:
                return {
                    "match_type": "LEGACY_STRONG_ID_REPLAY_BEFORE_CLOSE",
                    "matched_ids": strong_overlap,
                }
            return None
        if accepted_time or closed_entry_time or closed_exit_time:
            return {
                "match_type": "LEGACY_STRONG_ID_WITH_TEMPORAL_EVIDENCE",
                "matched_ids": strong_overlap,
            }
        # Compatibility for old ledgers that carried a real fill id but no
        # timestamps.  Reusable lineage-only ids never enter this branch.
        return {
            "match_type": "LEGACY_STRONG_ID_NO_TIMESTAMP",
            "matched_ids": strong_overlap,
        }

    lineage_overlap = sorted(
        lineage_identity_values(accepted_row) & lineage_identity_values(closed_row)
    )
    if lineage_overlap and accepted_time and closed_exit_time and accepted_time <= closed_exit_time:
        return {
            "match_type": "LEGACY_LINEAGE_REPLAY_BEFORE_CLOSE",
            "matched_ids": lineage_overlap,
        }
    return None
