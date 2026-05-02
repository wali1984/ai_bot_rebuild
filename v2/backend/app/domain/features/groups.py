from __future__ import annotations

from typing import Dict, Iterable, List

from .models import FeatureGroup


DEFAULT_FEATURE_GROUPS = [
    FeatureGroup("price", ["close", "return_1m", "return_5m"], required_for_trainer=True),
    FeatureGroup("liquidity", ["spread_bps", "orderbook_depth_usd"], required_for_trainer=True),
    FeatureGroup("liquidations", ["liq_long_usd", "liq_short_usd"], required_for_trainer=False),
    FeatureGroup("technical", ["rsi_14", "ema_fast", "ema_slow"], required_for_trainer=False),
]


def group_features(feature_values: Dict[str, float], groups: Iterable[FeatureGroup] = DEFAULT_FEATURE_GROUPS) -> List[FeatureGroup]:
    available = set(feature_values)
    grouped = []
    for group in groups:
        present = [name for name in group.feature_names if name in available]
        if present or group.required_for_trainer:
            grouped.append(FeatureGroup(group.name, present, group.required_for_trainer, group.description))
    return grouped


def required_feature_names(groups: Iterable[FeatureGroup] = DEFAULT_FEATURE_GROUPS) -> List[str]:
    names: List[str] = []
    for group in groups:
        if group.required_for_trainer:
            names.extend(group.feature_names)
    return sorted(set(names))

