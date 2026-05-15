from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


LIVE_GATE_STATUS = "blocked_human_only"


def repo_root() -> Path:
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "v2").exists() and (candidate / "claude_worklog").exists():
            return candidate
    return here.parents[4]


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_ts(value: Any) -> Optional[dt.datetime]:
    if not isinstance(value, str) or not value:
        return None
    try:
        return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
            dt.timezone.utc
        )
    except ValueError:
        return None


def age_seconds(value: Any) -> Optional[int]:
    parsed = parse_ts(value)
    if parsed is None:
        return None
    return max(0, int((dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()))


def load_json(path: Path) -> Optional[Any]:
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def first_json(paths: Iterable[Path]) -> tuple[Optional[Any], str]:
    for path in paths:
        payload = load_json(path)
        if payload is not None:
            return payload, str(path)
    return None, ""


def nested_get(payload: Any, dotted_path: str, default: Any = None) -> Any:
    current = payload
    for part in dotted_path.split("."):
        if isinstance(current, Mapping) and part in current:
            current = current[part]
            continue
        return default
    return current


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def confidence_bucket(value: Any) -> str:
    confidence = as_float(value)
    if confidence is None:
        return "missing"
    if confidence < 0.58:
        return "below_0.58"
    if confidence < 0.65:
        return "0.58_to_0.65"
    if confidence < 0.75:
        return "0.65_to_0.75"
    return "0.75_plus"


def file_mtime_status(path: Path, *, fresh_seconds: int = 900) -> dict[str, Any]:
    if not path.exists():
        return {
            "path": str(path),
            "state": "MISSING_EVIDENCE",
            "age_seconds": None,
            "fresh_seconds": fresh_seconds,
        }
    mtime = dt.datetime.fromtimestamp(path.stat().st_mtime, tz=dt.timezone.utc)
    age = max(0, int((dt.datetime.now(dt.timezone.utc) - mtime).total_seconds()))
    return {
        "path": str(path),
        "state": "CURRENT" if age <= fresh_seconds else "STALE",
        "age_seconds": age,
        "fresh_seconds": fresh_seconds,
        "mtime": mtime.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def tail_text(path: Path, *, max_bytes: int = 512 * 1024) -> str:
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            return handle.read().decode("utf-8", errors="replace")
    except OSError:
        return ""


def count_terms(text: str, terms: Iterable[str]) -> int:
    lowered = text.lower()
    return sum(lowered.count(term.lower()) for term in terms)


def safety_footer() -> dict[str, Any]:
    return {
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "live_blocked": True,
        "approval_token_created": False,
        "redis_trim_approval_created": False,
        "old_redis_write_performed": False,
        "exchange_action_taken": False,
        "legacy_mutation_performed": False,
    }
