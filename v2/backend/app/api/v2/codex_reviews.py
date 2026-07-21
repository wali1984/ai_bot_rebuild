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


_VERDICT_RESULT_KEYS = {
    "result",
    "classification",
    "go_no_go",
    "review_result",
    "review_status",
    "outcome",
}
_ARTIFACT_SCAN_LIMIT = 40
_ARTIFACT_MAX_BYTES = 5_000_000


def extract_codex_artifact_verdict(data: dict[str, Any], *, name: str = "") -> dict[str, Any]:
    """Map heterogeneous codex artifact fields to a normalized verdict.

    Real artifacts on disk never carry the open_count/last_pass_id shape this
    API originally expected — they carry verdict strings under keys like
    ``burndown_review_verdict``, ``mapping.remediation_verdict``,
    ``classification``, ``go_no_go`` or a task lifecycle ``status``.
    Returns {result, verdict_field, verdict_value} where result is one of
    pass/fail/completed/pending/blocked/superseded/<raw status>/unknown.
    """
    found: list[tuple[str, str]] = []

    def _walk(obj: Any, depth: int = 0, prefix: str = "") -> None:
        if depth > 2 or not isinstance(obj, dict):
            return
        for key, value in obj.items():
            key_l = str(key).lower()
            if isinstance(value, str) and value and (
                "verdict" in key_l or key_l in _VERDICT_RESULT_KEYS or key_l == "status"
            ):
                found.append((prefix + str(key), value))
            elif isinstance(value, dict):
                _walk(value, depth + 1, prefix + str(key) + ".")

    _walk(data)
    verdict_candidates = [
        (key, value)
        for key, value in found
        if "verdict" in key.lower()
        or key.lower().rsplit(".", 1)[-1] in _VERDICT_RESULT_KEYS
    ]
    fail_hit = next(
        (
            (key, value)
            for key, value in verdict_candidates
            if "FAIL" in value.upper() or "NO_GO" in value.upper()
        ),
        None,
    )
    pass_hit = next(
        (
            (key, value)
            for key, value in verdict_candidates
            if "PASS" in value.upper()
            or value.upper() == "GO"
            or (value.upper().endswith("_GO") and "NO_GO" not in value.upper())
        ),
        None,
    )
    if fail_hit is not None:
        return {"result": "fail", "verdict_field": fail_hit[0], "verdict_value": fail_hit[1]}
    if pass_hit is not None:
        return {"result": "pass", "verdict_field": pass_hit[0], "verdict_value": pass_hit[1]}
    name_u = name.upper()
    if "FAIL" in name_u:
        return {"result": "fail", "verdict_field": "filename", "verdict_value": name}
    if "PASS" in name_u:
        return {"result": "pass", "verdict_field": "filename", "verdict_value": name}
    status = next(
        (value for key, value in found if key.lower().rsplit(".", 1)[-1] == "status"),
        None,
    )
    if isinstance(status, str) and status:
        status_l = status.lower()
        if status_l in {"done", "completed"}:
            result = "completed"
        elif "block" in status_l:
            result = "blocked"
        elif "pending" in status_l:
            result = "pending"
        elif "supersed" in status_l or "obsolete" in status_l:
            result = "superseded"
        else:
            result = status_l[:40]
        return {"result": result, "verdict_field": "status", "verdict_value": status}
    return {"result": "unknown", "verdict_field": None, "verdict_value": None}


def _from_filesystem(base: Path) -> dict[str, Any] | None:
    """Derive the summary shape from the newest codex-review artifacts.

    The artifacts never carry open_count/last_pass_id keys (the previous
    mapping always yielded zeros despite ~1,200 review files on disk), so
    derive: last pass/fail ids from normalized verdicts, open_count from
    pending/blocked review tasks, blocker_count from blocked ones.
    """
    if not base.exists() or not base.is_dir():
        return None
    candidates: list[tuple[float, Path]] = []
    try:
        for p in base.rglob("*codex*review*.json"):
            if not p.is_file():
                continue
            try:
                candidates.append((p.stat().st_mtime, p))
            except OSError:
                continue
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    out = _empty_shape()
    open_count = 0
    blocker_count = 0
    scanned = 0
    for _, path in candidates[:_ARTIFACT_SCAN_LIMIT]:
        try:
            if path.stat().st_size > _ARTIFACT_MAX_BYTES:
                continue
            with path.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        scanned += 1
        # Direct summary fields win if some artifact ever publishes them.
        if any(k in data for k in ("open_count", "last_pass_id", "last_fail_id")):
            out["open_count"] = _coerce_int(data.get("open_count", out["open_count"]))
            out["blocker_count"] = _coerce_int(data.get("blocker_count", out["blocker_count"]))
            for k in ("last_pass_id", "last_fail_id", "last_blocker_text"):
                if data.get(k) not in (None, "") and out[k] is None:
                    out[k] = data[k]
        verdict = extract_codex_artifact_verdict(data, name=path.stem)
        result = verdict["result"]
        if result == "pass" and out["last_pass_id"] is None:
            out["last_pass_id"] = path.stem
        elif result == "fail":
            if out["last_fail_id"] is None:
                out["last_fail_id"] = path.stem
            if out["last_blocker_text"] is None and verdict["verdict_value"]:
                out["last_blocker_text"] = str(verdict["verdict_value"])[:200]
        elif result in {"pending", "blocked"}:
            open_count += 1
            if result == "blocked":
                blocker_count += 1
    if not out["open_count"]:
        out["open_count"] = open_count
    if not out["blocker_count"]:
        out["blocker_count"] = blocker_count
    out["source"] = "filesystem_verdict_scan"
    out["scanned_artifacts"] = scanned
    out["newest_artifact"] = candidates[0][1].name
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
