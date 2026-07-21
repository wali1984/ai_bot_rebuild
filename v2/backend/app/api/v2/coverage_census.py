"""Bounded coverage-census summary endpoint.

``v2:universe:coverage_census`` is a ~2.15MB blob (157 symbols x 6 families x
5 timeframes of per-key hold detail). Serving it raw would violate the bounded
payload rule, so this endpoint parses it server-side on a short TTL cache and
returns ONLY aggregate counts: per-family status counts and counts per
consumer-hold/deferral reason. The full per-symbol blob is never returned.

Read-only; never mutates anything; live trading stays blocked.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter

from app.api.v2._common import get_redis

router = APIRouter(prefix="/coverage", tags=["v2-coverage"])

CENSUS_KEY = "v2:universe:coverage_census"
_CACHE_TTL_SECONDS = 60.0
_GAP_SYMBOL_SAMPLE_LIMIT = 20
_TOP_REASON_LIMIT = 12

_cache_lock = threading.Lock()
_cache: tuple[float, dict[str, Any]] | None = None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _iso_age_seconds(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (datetime.now(UTC) - parsed).total_seconds())


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _count_hold_reasons(
    symbols: dict[str, Any],
) -> tuple[dict[str, int], dict[str, dict[str, int]]]:
    """Counts per consumer-hold reason, overall and per family.

    Granularity: one count per (symbol, family, timeframe, reason) so the
    numbers answer "how many symbol-timeframe pairs does this reason hold?".
    Family-level single reasons (families without tf detail) count once per
    (symbol, family).
    """
    overall: dict[str, int] = {}
    by_family: dict[str, dict[str, int]] = {}

    def _add(family: str, reason: Any) -> None:
        if reason in (None, ""):
            return
        key = str(reason)
        overall[key] = overall.get(key, 0) + 1
        fam_bucket = by_family.setdefault(family, {})
        fam_bucket[key] = fam_bucket.get(key, 0) + 1

    for sym_entry in symbols.values():
        families = _dict(_dict(sym_entry).get("families"))
        for family_name, family_entry in families.items():
            family_entry = _dict(family_entry)
            tfs = _dict(family_entry.get("tfs"))
            if tfs:
                for tf_entry in tfs.values():
                    tf_entry = _dict(tf_entry)
                    reasons = tf_entry.get("consumer_hold_reasons")
                    if isinstance(reasons, list) and reasons:
                        for reason in reasons:
                            _add(family_name, reason)
                    elif tf_entry.get("reason") not in (None, "", "ok"):
                        _add(family_name, tf_entry.get("reason"))
            else:
                reason = family_entry.get("consumer_hold_reason")
                if reason not in (None, ""):
                    _add(family_name, reason)
    return overall, by_family


def _build_summary(raw: str) -> dict[str, Any]:
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("census payload is not an object")
    symbols = _dict(payload.get("symbols"))
    summary = _dict(payload.get("summary"))
    hold_counts, hold_counts_by_family = _count_hold_reasons(symbols)
    top_reasons = [
        {"reason": reason, "count": count}
        for reason, count in sorted(
            hold_counts.items(), key=lambda item: (-item[1], item[0])
        )[:_TOP_REASON_LIMIT]
    ]
    gap_symbols = summary.get("gap_symbols")
    gap_symbols = gap_symbols if isinstance(gap_symbols, list) else []
    return {
        "schema_version": "coverage_census_summary_v1",
        "source_key": CENSUS_KEY,
        "source_bytes": len(raw),
        "census_as_of_utc": payload.get("census_as_of_utc"),
        "census_generated_utc": payload.get("generated_utc"),
        "worker_id": payload.get("worker_id"),
        "universe_count": payload.get("universe_count"),
        "universe_profile": payload.get("universe_profile"),
        "universe_source": payload.get("universe_source"),
        "timeframes": payload.get("timeframes"),
        "feature_spec_total": payload.get("feature_spec_total"),
        "feature_spec_coverage_pct_avg": summary.get("feature_spec_coverage_pct_avg"),
        "symbols_fully_covered": summary.get("symbols_fully_covered"),
        "symbols_with_gaps": summary.get("symbols_with_gaps"),
        "gap_symbol_count": len(gap_symbols),
        "gap_symbols_sample": [str(s) for s in gap_symbols[:_GAP_SYMBOL_SAMPLE_LIMIT]],
        "family_status_counts": _dict(summary.get("families")),
        "consumer_hold_reason_counts": hold_counts,
        "consumer_hold_reason_counts_by_family": hold_counts_by_family,
        "top_hold_reasons": top_reasons,
        "global_hold_reasons": {
            "feature_consumer_hold_reason": payload.get("feature_consumer_hold_reason"),
            "ohlcv_consumer_hold_reason": payload.get("ohlcv_consumer_hold_reason"),
            "ta_consumer_hold_reason": payload.get("ta_consumer_hold_reason"),
            "feature_publication_receipt_validator_bound": payload.get(
                "feature_publication_receipt_validator_bound"
            ),
            "ohlcv_consumer_selection_bound": payload.get(
                "ohlcv_consumer_selection_bound"
            ),
            "ta_finality_consumer_bound": payload.get("ta_finality_consumer_bound"),
            "ohlcv_coverage_semantics": payload.get("ohlcv_coverage_semantics"),
        },
        "thresholds": _dict(payload.get("thresholds")),
        "backfill": _dict(payload.get("backfill")),
        "core_ta_minimum_source_rows": payload.get("core_ta_minimum_source_rows"),
        "live_gate": payload.get("live_gate") or "blocked_human_only",
        "places_real_order": False,
        "routes_to_live": False,
        # Contract: the 2.15MB per-symbol blob is parsed server-side only.
        "per_symbol_blob_excluded": True,
    }


@router.get("/census-summary")
async def get_coverage_census_summary() -> dict[str, Any]:
    """Aggregate hold/deferral-reason counts from the universe coverage census."""
    global _cache
    now_mono = time.monotonic()
    with _cache_lock:
        if _cache is not None and now_mono - _cache[0] <= _CACHE_TTL_SECONDS:
            cached = dict(_cache[1])
            cached["generated_at_utc"] = _utc_now()
            cached["census_age_seconds"] = _iso_age_seconds(
                cached.get("census_generated_utc")
            )
            cached["cache_hit"] = True
            return cached

    r = get_redis()
    unavailable_reason: str | None = None
    raw: Any = None
    if r is None:
        unavailable_reason = "redis_unavailable"
    else:
        try:
            raw = r.get(CENSUS_KEY)
        except Exception:
            unavailable_reason = "redis_read_failed"
        if unavailable_reason is None and not raw:
            unavailable_reason = "census_key_missing"

    if unavailable_reason is not None:
        return {
            "schema_version": "coverage_census_summary_v1",
            "available": False,
            "reason": unavailable_reason,
            "source_key": CENSUS_KEY,
            "generated_at_utc": _utc_now(),
            "live_gate": "blocked_human_only",
            "places_real_order": False,
            "routes_to_live": False,
        }

    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        summary = _build_summary(str(raw))
    except (ValueError, TypeError):
        return {
            "schema_version": "coverage_census_summary_v1",
            "available": False,
            "reason": "census_payload_unparseable",
            "source_key": CENSUS_KEY,
            "generated_at_utc": _utc_now(),
            "live_gate": "blocked_human_only",
            "places_real_order": False,
            "routes_to_live": False,
        }
    summary["available"] = True
    summary["cache_ttl_seconds"] = _CACHE_TTL_SECONDS
    with _cache_lock:
        _cache = (time.monotonic(), dict(summary))
    summary["generated_at_utc"] = _utc_now()
    summary["census_age_seconds"] = _iso_age_seconds(
        summary.get("census_generated_utc")
    )
    summary["cache_hit"] = False
    return summary
