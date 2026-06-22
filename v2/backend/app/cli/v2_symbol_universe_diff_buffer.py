"""V2 symbol-universe rolling diff buffer (paper-only, read-only observer).

Captures point-in-time snapshots of the symbol-universe payload
(``v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json``)
into a rolling on-disk buffer and computes adds/removes vs prior snapshots
inside 1h / 6h / 12h windows. The buffer is bounded by both age and entry
count so it cannot grow unbounded.

This script writes ONLY to filesystem paths under
- ``v2/runtime/symbol_universe_diff_buffer/snapshots/``
- ``v2/frontend/public/operator_runtime/symbol_universe_diff_buffer/latest/symbol_universe_diff_buffer_status.json``

It NEVER touches Redis, NEVER calls exchange endpoints, NEVER enables
live/canary, NEVER changes leverage/margin, and NEVER touches legacy.

Usage::

    .venv/bin/python3 -m v2.backend.app.cli.v2_symbol_universe_diff_buffer --append
    .venv/bin/python3 -m v2.backend.app.cli.v2_symbol_universe_diff_buffer --emit-status
    .venv/bin/python3 -m v2.backend.app.cli.v2_symbol_universe_diff_buffer  # both
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
SNAPSHOT_SRC = REPO / "v2/frontend/public/operator_runtime/symbol_universe/latest/symbol_universe_status.json"
BUFFER_DIR = REPO / "v2/runtime/symbol_universe_diff_buffer/snapshots"
STATUS_PUBLIC = REPO / "v2/frontend/public/operator_runtime/symbol_universe_diff_buffer/latest/symbol_universe_diff_buffer_status.json"
STATUS_WORKLOG = REPO / "claude_worklog/final_readiness/symbol_universe_diff_buffer/latest/symbol_universe_diff_buffer_status.json"

MAX_BUFFER_ENTRIES = 2048
MAX_BUFFER_AGE_SECONDS = 14 * 24 * 3600


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc_iso(value: dt.datetime) -> str:
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (ValueError, OSError):
        return None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _symbol_set(payload: dict | None, key: str) -> set[str]:
    if not payload:
        return set()
    raw = payload.get(key) or []
    if not isinstance(raw, list):
        return set()
    return {str(s).upper() for s in raw if isinstance(s, str)}


def append_snapshot(now: dt.datetime | None = None) -> Path | None:
    now = now or _now_utc()
    src = _load_json(SNAPSHOT_SRC)
    if src is None:
        return None
    entry = {
        "captured_utc": _utc_iso(now),
        "dynamic_discovered_symbols": sorted(_symbol_set(src, "dynamic_discovered_symbols")),
        "discovered_symbols": sorted(_symbol_set(src, "discovered_symbols")),
        "binance_usdm_confirmed_symbols": sorted(_symbol_set(src, "binance_usdm_confirmed_symbols")),
        "observed_symbols": sorted(_symbol_set(src, "observed_symbols")),
        "paper_symbols": sorted(_symbol_set(src, "paper_symbols")),
        "live_symbols": sorted(_symbol_set(src, "live_symbols")),
        "live_gate": src.get("live_gate"),
    }
    BUFFER_DIR.mkdir(parents=True, exist_ok=True)
    path = BUFFER_DIR / (now.strftime("%Y%m%dT%H%M%SZ") + ".json")
    path.write_text(json.dumps(entry, indent=2, sort_keys=True) + "\n")
    return path


def _list_snapshots() -> list[Path]:
    if not BUFFER_DIR.exists():
        return []
    return sorted(BUFFER_DIR.glob("*.json"))


def prune_buffer(now: dt.datetime | None = None) -> int:
    """Drop snapshots older than MAX_BUFFER_AGE_SECONDS and trim count."""
    now = now or _now_utc()
    paths = _list_snapshots()
    removed = 0
    for p in paths:
        try:
            entry = json.loads(p.read_text())
        except (ValueError, OSError):
            p.unlink(missing_ok=True)
            removed += 1
            continue
        captured = entry.get("captured_utc")
        try:
            captured_dt = dt.datetime.fromisoformat(captured.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            p.unlink(missing_ok=True)
            removed += 1
            continue
        age = (now - captured_dt).total_seconds()
        if age > MAX_BUFFER_AGE_SECONDS:
            p.unlink(missing_ok=True)
            removed += 1
    paths = _list_snapshots()
    if len(paths) > MAX_BUFFER_ENTRIES:
        for p in paths[: len(paths) - MAX_BUFFER_ENTRIES]:
            p.unlink(missing_ok=True)
            removed += 1
    return removed


def _diff(current: set[str], earlier: set[str]) -> dict:
    return {
        "added": sorted(current - earlier),
        "removed": sorted(earlier - current),
        "unchanged_count": len(current & earlier),
    }


def _earlier_snapshot(now: dt.datetime, window_seconds: int) -> dict | None:
    cutoff = now - dt.timedelta(seconds=window_seconds)
    candidates: list[tuple[dt.datetime, Path]] = []
    for p in _list_snapshots():
        try:
            entry = json.loads(p.read_text())
            captured = dt.datetime.fromisoformat(entry["captured_utc"].replace("Z", "+00:00"))
        except (ValueError, OSError, KeyError):
            continue
        if captured <= cutoff:
            candidates.append((captured, p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])
    return _load_json(candidates[-1][1])


def emit_status(now: dt.datetime | None = None) -> dict:
    now = now or _now_utc()
    snapshots = _list_snapshots()
    current_entry: dict | None = None
    if snapshots:
        current_entry = _load_json(snapshots[-1])
    current_symbols = set(current_entry.get("dynamic_discovered_symbols") or []) if current_entry else set()

    windows: dict[str, dict] = {}
    for label, seconds in (("1h", 3600), ("6h", 6 * 3600), ("12h", 12 * 3600)):
        earlier = _earlier_snapshot(now, seconds)
        if earlier is None:
            windows[label] = {
                "earlier_snapshot_captured_utc": None,
                "diff": None,
                "verdict": "INSUFFICIENT_HISTORY_FOR_WINDOW",
            }
            continue
        earlier_symbols = set(earlier.get("dynamic_discovered_symbols") or [])
        windows[label] = {
            "earlier_snapshot_captured_utc": earlier.get("captured_utc"),
            "diff": _diff(current_symbols, earlier_symbols),
            "verdict": "DIFF_AVAILABLE",
        }

    payload = {
        "schema_version": "v2_symbol_universe_diff_buffer_status_v1",
        "generated_utc": _utc_iso(now),
        "live_gate": (current_entry or {}).get("live_gate") or "blocked_human_only",
        "live_symbols": (current_entry or {}).get("live_symbols") or [],
        "buffer": {
            "snapshot_count": len(snapshots),
            "earliest_captured_utc": (
                _load_json(snapshots[0]) or {}
            ).get("captured_utc") if snapshots else None,
            "latest_captured_utc": (current_entry or {}).get("captured_utc"),
            "max_buffer_entries": MAX_BUFFER_ENTRIES,
            "max_buffer_age_seconds": MAX_BUFFER_AGE_SECONDS,
        },
        "current_dynamic_discovered_count": len(current_symbols),
        "current_dynamic_discovered_symbols": sorted(current_symbols),
        "windows": windows,
        "no_redis_writes": True,
        "no_exchange_action": True,
        "no_legacy_mutation": True,
    }
    _write_json(STATUS_PUBLIC, payload)
    _write_json(STATUS_WORKLOG, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_symbol_universe_diff_buffer")
    parser.add_argument("--append", action="store_true", help="Append current snapshot to buffer")
    parser.add_argument("--emit-status", action="store_true", help="Emit diff status payload")
    parser.add_argument("--prune", action="store_true", help="Prune buffer of stale entries")
    args = parser.parse_args(argv)

    if not (args.append or args.emit_status or args.prune):
        args.append = True
        args.emit_status = True
        args.prune = True

    now = _now_utc()
    if args.append:
        append_snapshot(now)
    if args.prune:
        prune_buffer(now)
    if args.emit_status:
        payload = emit_status(now)
        print(json.dumps({
            "snapshot_count": payload["buffer"]["snapshot_count"],
            "current_dynamic_discovered_count": payload["current_dynamic_discovered_count"],
            "windows": {k: v.get("verdict") for k, v in payload["windows"].items()},
        }, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
