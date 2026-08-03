from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


MISSING_NAME_KEYS = ("missing_feature_names", "missing_feature_flags", "missing_features")
STALE_NAME_KEYS = ("stale_feature_names", "stale_feature_flags", "stale_features")


def _as_feature_mapping(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    features = snapshot.get("features")
    if isinstance(features, Mapping):
        return {str(name): value for name, value in features.items()}
    feature_values = snapshot.get("feature_values")
    if isinstance(feature_values, Mapping):
        return {str(name): value for name, value in feature_values.items()}
    nested = snapshot.get("feature_snapshot")
    if isinstance(nested, Mapping):
        return _as_feature_mapping(nested)
    return {}


def _mask_from_value(value: Any) -> dict[str, bool]:
    if isinstance(value, Mapping):
        return {str(name): bool(flag) for name, flag in value.items() if str(name).strip()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        return {str(name): True for name in value if str(name).strip()}
    return {}


def _names_from_value(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        return {str(name) for name, flag in value.items() if bool(flag) and str(name).strip()}
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        return {str(name) for name in value if str(name).strip()}
    return set()


def _explicit_names_or_mask_present(snapshot: Mapping[str, Any], *, mask_key: str, names_keys: tuple[str, ...]) -> bool:
    return mask_key in snapshot or any(key in snapshot for key in names_keys)


def mask_names(
    snapshot: Mapping[str, Any],
    *,
    mask_key: str,
    names_keys: tuple[str, ...],
) -> list[str]:
    names: set[str] = set()
    names.update(_names_from_value(snapshot.get(mask_key)))
    for key in names_keys:
        names.update(_names_from_value(snapshot.get(key)))
    return sorted(names)


def mask_dict(
    snapshot: Mapping[str, Any],
    *,
    mask_key: str,
    names_keys: tuple[str, ...],
) -> dict[str, bool]:
    raw = _mask_from_value(snapshot.get(mask_key))
    if raw:
        return raw
    names: set[str] = set()
    for key in names_keys:
        names.update(_names_from_value(snapshot.get(key)))
    return {name: True for name in sorted(names)}


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = int(float(value))
    except (TypeError, ValueError):
        return None
    return max(0, parsed)


def _effective_count(
    snapshot: Mapping[str, Any],
    *,
    count_key: str,
    mask_key: str,
    names_keys: tuple[str, ...],
    names: list[str],
) -> int:
    if _explicit_names_or_mask_present(snapshot, mask_key=mask_key, names_keys=names_keys):
        return len(names)
    return _int_or_none(snapshot.get(count_key)) or len(names)


def source_availability(snapshot: Mapping[str, Any]) -> Any:
    for key in ("source_availability", "source_availability_vector", "source_inputs"):
        value = snapshot.get(key)
        if isinstance(value, Mapping):
            return {str(name): item for name, item in value.items()}
        if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
            return list(value)
    nested = snapshot.get("feature_snapshot")
    if isinstance(nested, Mapping):
        return source_availability(nested)
    return {}


def canonical_feature_lineage(snapshot: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {
            "feature_lineage_source": "FEATURE_SNAPSHOT_MISSING",
            "feature_names": [],
            "missing_feature_names": [],
            "missing_feature_count": 0,
            "missing_mask": {},
            "stale_feature_names": [],
            "stale_feature_count": 0,
            "stale_mask": {},
            "source_availability": {},
            "lineage_fields_present": False,
        }
    missing_names = mask_names(snapshot, mask_key="missing_mask", names_keys=MISSING_NAME_KEYS)
    stale_names = mask_names(snapshot, mask_key="stale_mask", names_keys=STALE_NAME_KEYS)
    return {
        "feature_lineage_source": "FEATURE_SNAPSHOT_CANONICAL_MASKS",
        "feature_names": sorted(_as_feature_mapping(snapshot)),
        "missing_feature_names": missing_names,
        "missing_feature_count": _effective_count(
            snapshot,
            count_key="missing_feature_count",
            mask_key="missing_mask",
            names_keys=MISSING_NAME_KEYS,
            names=missing_names,
        ),
        "missing_mask": mask_dict(snapshot, mask_key="missing_mask", names_keys=MISSING_NAME_KEYS),
        "stale_feature_names": stale_names,
        "stale_feature_count": _effective_count(
            snapshot,
            count_key="stale_feature_count",
            mask_key="stale_mask",
            names_keys=STALE_NAME_KEYS,
            names=stale_names,
        ),
        "stale_mask": mask_dict(snapshot, mask_key="stale_mask", names_keys=STALE_NAME_KEYS),
        "source_availability": source_availability(snapshot),
        "lineage_fields_present": True,
    }
