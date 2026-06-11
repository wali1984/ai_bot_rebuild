"""B3: latest codex review summary.

Reads `codex:reviews:*` Redis keys first, then falls back to scanning the
latest codex-review file under `CODEX_REVIEW_DIR` (defaults to
`claude_worklog/`). If neither is present, returns zeros and nulls — never
raises.

Shape:
{ open_count: int, blocker_count: int, last_pass_id: str|None,
  last_fail_id: str|None, last_blocker_text: str|None }
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(prefix="/codex", tags=["v2-landing"])


def _empty_shape() -> dict[str, Any]:
    return {
        "open_count": 0,
        "blocker_count": 0,
        "last_pass_id": None,
        "last_fail_id": None,
        "last_blocker_text": None,
    }


def _coerce_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _from_redis(r: Any) -> dict[str, Any] | None:
    """Try to assemble the shape from `codex:reviews:*` keys.

    Returns None if nothing was found.
    """
    if r is None:
        return None
    out = _empty_shape()
    found_any = False
    candidates = [
        "codex:reviews:latest",
        "codex:reviews:summary",
        "codex:reviews:state",
    ]
    for key in candidates:
        try:
            raw = r.get(key)
        except Exception:
            raw = None
        if raw is None:
            continue
        found_any = True
        try:
            data = json.loads(raw) if isinstance(raw, str) else None
        except (ValueError, TypeError):
            data = None
        if isinstance(data, dict):
            out["open_count"] = _coerce_int(data.get("open_count", out["open_count"]))
            out["blocker_count"] = _coerce_int(
                data.get("blocker_count", out["blocker_count"])
            )
            for k in ("last_pass_id", "last_fail_id", "last_blocker_text"):
                if data.get(k) not in (None, ""):
                    out[k] = data[k]
    # Also try discrete keys (each may store one field).
    for key, field in (
        ("codex:reviews:open_count", "open_count"),
        ("codex:reviews:blocker_count", "blocker_count"),
        ("codex:reviews:last_pass_id", "last_pass_id"),
        ("codex:reviews:last_fail_id", "last_fail_id"),
        ("codex:reviews:last_blocker_text", "last_blocker_text"),
    ):
        try:
            raw = r.get(key)
        except Exception:
            raw = None
        if raw is None:
            continue
        found_any = True
        if field in ("open_count", "blocker_count"):
            out[field] = _coerce_int(raw)
        else:
            out[field] = raw
    return out if found_any else None


def _codex_review_dir() -> Path:
    """Resolve the codex review evidence dir.

    `CODEX_REVIEW_DIR` env wins; else `<repo_root>/claude_worklog`.
    """
    override = os.environ.get("CODEX_REVIEW_DIR", "").strip()
    if override:
        return Path(override)
    # /v2/backend/app/api/v2/codex_reviews.py -> repo root is parents[5]
    return Path(__file__).resolve().parents[5] / "claude_worklog"


def _from_filesystem(base: Path) -> dict[str, Any] | None:
    """Best-effort: find the newest `*codex*review*.json` file in `base`.

    If the JSON includes any of the expected fields, return the merged shape.
    Returns None if no such file is found.
    """
    if not base.exists() or not base.is_dir():
        return None
    newest: tuple[float, Path] | None = None
    try:
        for p in base.rglob("*codex*review*.json"):
            if not p.is_file():
                continue
            try:
                mtime = p.stat().st_mtime
            except OSError:
                continue
            if newest is None or mtime > newest[0]:
                newest = (mtime, p)
    except OSError:
        return None
    if newest is None:
        return None
    try:
        with newest[1].open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    out = _empty_shape()
    out["open_count"] = _coerce_int(data.get("open_count", 0))
    out["blocker_count"] = _coerce_int(data.get("blocker_count", 0))
    for k in ("last_pass_id", "last_fail_id", "last_blocker_text"):
        v = data.get(k)
        if v not in (None, ""):
            out[k] = v
    return out


@router.get("/reviews/latest")
async def get_codex_reviews_latest() -> dict[str, Any]:
    r = get_redis()
    via_redis = _from_redis(r)
    if via_redis is not None:
        return via_redis
    via_fs = _from_filesystem(_codex_review_dir())
    if via_fs is not None:
        return via_fs
    return _empty_shape()
