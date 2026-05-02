from __future__ import annotations

import datetime as dt
from typing import Dict, Iterable, List

from .models import FeatureFreshness


def parse_ts(value: str) -> dt.datetime:
    text = value.replace("Z", "+00:00")
    parsed = dt.datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def assess_freshness(source_name: str, source_ts: str | None, observed_ts: str, max_age_ms: int) -> FeatureFreshness:
    if not source_ts:
        return FeatureFreshness(source_name, None, observed_ts, max_age_ms, None, stale=False, missing=True)
    age = int((parse_ts(observed_ts) - parse_ts(source_ts)).total_seconds() * 1000)
    return FeatureFreshness(
        source_name=source_name,
        source_ts=source_ts,
        observed_ts=observed_ts,
        max_age_ms=max_age_ms,
        age_ms=age,
        stale=age > max_age_ms,
        missing=False,
    )


def stale_feature_names(feature_to_source: Dict[str, str], freshness_by_source: Dict[str, FeatureFreshness]) -> List[str]:
    return sorted(name for name, source in feature_to_source.items() if freshness_by_source.get(source) and freshness_by_source[source].stale)


def missing_feature_names(required_features: Iterable[str], feature_values: Dict[str, float]) -> List[str]:
    return sorted(name for name in required_features if name not in feature_values)


def unused_feature_names(feature_values: Dict[str, float], used_features: Iterable[str]) -> List[str]:
    used = set(used_features)
    return sorted(name for name in feature_values if name not in used)

