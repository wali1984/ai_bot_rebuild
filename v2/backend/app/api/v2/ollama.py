"""B5: Ollama health route.

Reads `OLLAMA_HOST` (default `http://localhost:11434`) and pings the local
Ollama daemon's `/api/tags` endpoint with a 1s timeout. On any error,
returns `{ ready: false, model: None, last_draft_at: None }`.

This route never mutates Ollama state, never queries a remote provider,
and never reads secrets.

Shape:
{ model: str|None, ready: bool, last_draft_at: str|None }
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(prefix="/ollama", tags=["v2-landing"])


def _empty(reason: str | None = None) -> dict[str, Any]:
    out: dict[str, Any] = {"model": None, "ready": False, "last_draft_at": None}
    if reason:
        out["_reason"] = reason
    return out


def _ollama_host() -> str:
    return os.environ.get("OLLAMA_HOST", "http://localhost:11434").strip().rstrip("/")


def _last_draft_at_from_redis(r: Any) -> str | None:
    if r is None:
        return None
    for key in ("ollama:last_draft_at", "v2:ollama:last_draft_at"):
        try:
            v = r.get(key)
        except Exception:
            v = None
        if v:
            return str(v)
    return None


def _first_model_name(tags_json: Any) -> str | None:
    """Ollama's /api/tags returns `{ "models": [ { "name": ... }, ... ] }`.

    Be tolerant of variations.
    """
    if not isinstance(tags_json, dict):
        return None
    models = tags_json.get("models")
    if not isinstance(models, list) or not models:
        return None
    first = models[0]
    if isinstance(first, dict):
        name = first.get("name") or first.get("model")
        return str(name) if name else None
    return None


@router.get("/health")
async def get_ollama_health() -> dict[str, Any]:
    host = _ollama_host()
    r = get_redis()
    last_draft_at = _last_draft_at_from_redis(r)

    try:
        import httpx  # type: ignore
    except Exception:
        return _empty()

    url = f"{host}/api/tags"
    try:
        resp = httpx.get(url, timeout=1.0)
    except Exception:
        out = _empty()
        out["last_draft_at"] = last_draft_at
        return out

    if resp.status_code != 200:
        out = _empty()
        out["last_draft_at"] = last_draft_at
        return out

    try:
        data = resp.json()
    except Exception:
        data = None
    return {
        "model": _first_model_name(data),
        "ready": True,
        "last_draft_at": last_draft_at,
    }
