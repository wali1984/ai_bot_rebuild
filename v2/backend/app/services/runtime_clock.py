"""Runtime timestamp helpers.

Operator-facing runtime payloads should be EST-first. Epoch milliseconds are
still kept for exchange protocol signing and point-in-time feature safety.
"""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

EST = ZoneInfo("America/New_York")


def epoch_ms_now() -> int:
    return int(datetime.now(UTC).timestamp() * 1000)


def est_now_iso(*, timespec: str = "seconds") -> str:
    return datetime.now(EST).isoformat(timespec=timespec)


def epoch_ms_to_est_iso(value: Any, *, timespec: str = "seconds") -> str | None:
    ms = parse_epoch_ms(value)
    if ms is None:
        return None
    return (
        datetime.fromtimestamp(ms / 1000.0, tz=UTC)
        .astimezone(EST)
        .isoformat(timespec=timespec)
    )


def parse_epoch_ms(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        numeric = int(value)
        return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            numeric = int(float(text))
            return numeric * 1000 if abs(numeric) < 10_000_000_000 else numeric
        except ValueError:
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                return None
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=EST)
            return int(parsed.timestamp() * 1000)
    return None


def age_seconds_from_epoch_ms(value: Any, *, now_ms: int | None = None) -> int | None:
    ms = parse_epoch_ms(value)
    if ms is None:
        return None
    reference = epoch_ms_now() if now_ms is None else int(now_ms)
    return max(0, int((reference - ms) / 1000))


def parse_iso_to_epoch_seconds(value: Any) -> float | None:
    ms = parse_epoch_ms(value)
    if ms is None:
        return None
    return ms / 1000.0
