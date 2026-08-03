#!/usr/bin/env python3
"""Validate derivative realtime/source evidence from safe local artifacts.

This command produces an evidence artifact for the derivatives_realtime_sources
blocker. It reads already-produced JSON/JSONL evidence only. It does not call
market APIs, create websocket connections, fabricate live data, submit/cancel
orders, mutate leverage/margin, touch live gates, or enable live trading.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

JSON_SUFFIXES = {".json", ".jsonl"}
TRUE_VALUES = {"1", "true", "yes", "y", "on", "enabled", "pass", "passed", "ok", "verified"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "disabled", "fail", "failed", "missing", "pending", "none", "null"}


@dataclass(frozen=True)
class LoadedArtifact:
    path: str
    payload: Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _iter_files(paths: Sequence[Path]) -> Iterable[Path]:
    for path in paths:
        if path.is_file() and path.suffix.lower() in JSON_SUFFIXES:
            yield path
        elif path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in JSON_SUFFIXES:
                    yield child


def _load_json_artifacts(paths: Sequence[Path], warnings: list[str]) -> list[LoadedArtifact]:
    loaded: list[LoadedArtifact] = []
    for path in _iter_files(paths):
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix.lower() == ".jsonl":
                for index, line in enumerate(text.splitlines(), start=1):
                    stripped = line.strip()
                    if stripped:
                        loaded.append(LoadedArtifact(path=f"{path}:{index}", payload=json.loads(stripped)))
            else:
                loaded.append(LoadedArtifact(path=str(path), payload=json.loads(text)))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Skipped {path}: {exc}")
    return loaded


def _flatten(payload: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            key_text = str(key)
            yield key_text, value
            for child_key, child_value in _flatten(value):
                yield f"{key_text}.{child_key}", child_value
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            for child_key, child_value in _flatten(value):
                yield f"{index}.{child_key}", child_value


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _truthy_any(artifacts: Sequence[LoadedArtifact], aliases: set[str]) -> bool:
    normalized_aliases = {alias.lower() for alias in aliases}
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            if key.split(".")[-1].lower() in normalized_aliases and _as_bool(value) is True:
                return True
    return False


def _falsey_any(artifacts: Sequence[LoadedArtifact], aliases: set[str]) -> bool:
    normalized_aliases = {alias.lower() for alias in aliases}
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            if key.split(".")[-1].lower() in normalized_aliases and _as_bool(value) is False:
                return True
    return False


def build_report(*, derivative_evidence_paths: Sequence[Path], safety_evidence_paths: Sequence[Path]) -> dict[str, object]:
    warnings: list[str] = []
    derivative_artifacts = _load_json_artifacts(derivative_evidence_paths, warnings)
    safety_artifacts = _load_json_artifacts(safety_evidence_paths, warnings)
    all_artifacts = [*derivative_artifacts, *safety_artifacts]

    if not derivative_artifacts:
        warnings.append("No derivatives realtime/source evidence artifacts were found")
    if not safety_artifacts:
        warnings.append("No derivatives safety evidence artifacts were found")

    funding_realtime_verified = _truthy_any(derivative_artifacts, {"funding_realtime_verified", "funding_stream_verified", "funding_source_verified"})
    open_interest_realtime_verified = _truthy_any(derivative_artifacts, {"open_interest_realtime_verified", "oi_realtime_verified", "open_interest_source_verified"})
    liquidation_source_verified = _truthy_any(derivative_artifacts, {"liquidation_source_verified", "liquidations_verified", "liquidation_feed_verified"})
    long_short_source_verified = _truthy_any(derivative_artifacts, {"long_short_source_verified", "long_short_ratio_verified", "long_short_verified"})
    basis_source_verified = _truthy_any(derivative_artifacts, {"basis_source_verified", "basis_verified", "mark_index_basis_verified"})
    exchange_comparison_verified = _truthy_any(derivative_artifacts, {"exchange_comparison_verified", "multi_exchange_comparison_verified"})
    freshness_enforced = _truthy_any(derivative_artifacts, {"freshness_enforced", "freshness_verified", "stale_detection_verified"})
    stale_marking_verified = _truthy_any(derivative_artifacts, {"stale_marking_verified", "stale_state_verified", "stale_warning_verified"})
    source_labels_verified = _truthy_any(derivative_artifacts, {"source_labels_verified", "source_freshness_labels_verified"})
    no_static_presented_as_live = _truthy_any(derivative_artifacts, {"no_static_presented_as_live", "fallback_not_presented_as_live"})

    fake_live_data_detected = _truthy_any(all_artifacts, {"fake_live_data_detected", "static_presented_as_live", "fallback_presented_as_live"})
    live_trading_enabled = _truthy_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    exchange_mutation_enabled = _truthy_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    live_submit_available = _truthy_any(all_artifacts, {"live_submit_available", "live_order_submit_available"})
    live_cancel_available = _truthy_any(all_artifacts, {"live_cancel_available", "live_order_cancel_available"})
    explicit_live_disabled = _falsey_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    explicit_exchange_disabled = _falsey_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})

    required_flags = {
        "funding_realtime_verified": funding_realtime_verified,
        "open_interest_realtime_verified": open_interest_realtime_verified,
        "liquidation_source_verified": liquidation_source_verified,
        "long_short_source_verified": long_short_source_verified,
        "basis_source_verified": basis_source_verified,
        "exchange_comparison_verified": exchange_comparison_verified,
        "freshness_enforced": freshness_enforced,
        "stale_marking_verified": stale_marking_verified,
        "source_labels_verified": source_labels_verified,
        "no_static_presented_as_live": no_static_presented_as_live,
    }
    missing_fields = [field for field, value in required_flags.items() if not value]
    forbidden_flags = {
        "no_fake_live_data": fake_live_data_detected,
        "live_trading_disabled": live_trading_enabled or not explicit_live_disabled,
        "exchange_mutation_disabled": exchange_mutation_enabled or not explicit_exchange_disabled,
        "live_submit_unavailable": live_submit_available,
        "live_cancel_unavailable": live_cancel_available,
    }
    for field, failed in forbidden_flags.items():
        if failed:
            missing_fields.append(field)

    passed = bool(derivative_artifacts and safety_artifacts) and not missing_fields
    return {
        "derivatives_realtime_source_status": "passed" if passed else "failed",
        "source": "local_derivatives_realtime_source_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "generated_at": _utc_now(),
        "funding_realtime_verified": funding_realtime_verified,
        "open_interest_realtime_verified": open_interest_realtime_verified,
        "liquidation_source_verified": liquidation_source_verified,
        "long_short_source_verified": long_short_source_verified,
        "basis_source_verified": basis_source_verified,
        "exchange_comparison_verified": exchange_comparison_verified,
        "freshness_enforced": freshness_enforced,
        "stale_marking_verified": stale_marking_verified,
        "source_labels_verified": source_labels_verified,
        "no_static_presented_as_live": no_static_presented_as_live,
        "fake_live_data_detected": fake_live_data_detected,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "live_submit_available": live_submit_available,
        "live_cancel_available": live_cancel_available,
        "missing_fields": sorted(set(missing_fields)),
        "warnings": warnings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--derivative-evidence-path", action="append", type=Path, default=[])
    parser.add_argument("--safety-evidence-path", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    report = build_report(
        derivative_evidence_paths=args.derivative_evidence_path,
        safety_evidence_paths=args.safety_evidence_path,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["derivatives_realtime_source_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
