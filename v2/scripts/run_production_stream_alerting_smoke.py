#!/usr/bin/env python3
"""Generate a production stream alerting evidence artifact.

This command validates already-produced public market-data alerting/dashboard
evidence and emits the JSON artifact consumed by
ALPHAFORGE_MARKET_STREAM_PRODUCTION_ALERTING_ARTIFACT.

It does not open WebSockets, call Binance, submit orders, cancel orders, mutate
leverage/margin, touch the live gate, or enable live trading.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

JSON_SUFFIXES = {".json", ".jsonl"}
SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "access_token",
    "refresh_token",
    "authorization",
    "x-mbx-apikey",
    "credential_reference",
    "credential_ref",
}
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
                    if not stripped:
                        continue
                    loaded.append(LoadedArtifact(path=f"{path}:{index}", payload=json.loads(stripped)))
            else:
                loaded.append(LoadedArtifact(path=str(path), payload=json.loads(text)))
        except (OSError, json.JSONDecodeError) as exc:
            warnings.append(f"Skipped {path}: {exc}")
    return loaded


def _flatten(payload: Any) -> Iterable[tuple[str, Any]]:
    if isinstance(payload, dict):
        for key, value in payload.items():
            normalized = str(key)
            yield normalized, value
            for child_key, child_value in _flatten(value):
                yield f"{normalized}.{child_key}", child_value
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            for child_key, child_value in _flatten(value):
                yield f"{index}.{child_key}", child_value


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
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


def _sensitive_key_seen(artifacts: Sequence[LoadedArtifact]) -> bool:
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            normalized = key.split(".")[-1].lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                if str(value).strip().lower() not in {"", "none", "null", "redacted", "[redacted]", "masked", "hidden"}:
                    return True
    return False


def build_report(
    *,
    alerting_config_paths: Sequence[Path],
    dashboard_evidence_paths: Sequence[Path],
    stream_status_paths: Sequence[Path],
) -> dict[str, object]:
    warnings: list[str] = []
    alerting_artifacts = _load_json_artifacts(alerting_config_paths, warnings)
    dashboard_artifacts = _load_json_artifacts(dashboard_evidence_paths, warnings)
    stream_status_artifacts = _load_json_artifacts(stream_status_paths, warnings)
    all_artifacts = [*alerting_artifacts, *dashboard_artifacts, *stream_status_artifacts]

    if not alerting_artifacts:
        warnings.append("No alerting configuration/evidence artifacts were found")
    if not dashboard_artifacts:
        warnings.append("No dashboard evidence artifacts were found")
    if not stream_status_artifacts:
        warnings.append("No stream-status artifacts were found")

    production_alerting_integrated = _truthy_any(
        all_artifacts,
        {"production_alerting_integrated", "alerting_integrated", "alerts_integrated"},
    )
    dashboard_integrated = _truthy_any(
        dashboard_artifacts,
        {"dashboard_integrated", "dashboard_connected", "dashboard_enabled", "stream_dashboard_integrated"},
    )
    stale_alerts_enabled = _truthy_any(
        all_artifacts,
        {"stale_alerts_enabled", "stale_alert_enabled", "stale_data_alerts_enabled"},
    )
    reconnect_alerts_enabled = _truthy_any(
        all_artifacts,
        {"reconnect_alerts_enabled", "reconnect_alert_enabled", "disconnect_alerts_enabled"},
    )
    lag_monitoring_enabled = _truthy_any(
        all_artifacts,
        {"lag_monitoring_enabled", "lag_alerts_enabled", "stream_lag_monitoring_enabled"},
    )
    missing_source_alerts_enabled = _truthy_any(
        all_artifacts,
        {"missing_source_alerts_enabled", "missing_data_alerts_enabled", "source_unavailable_alerts_enabled"},
    )
    public_market_data_only = _truthy_any(
        all_artifacts,
        {"public_market_data_only", "market_data_public_only", "public_data_only"},
    )
    contains_credentials = _truthy_any(all_artifacts, {"contains_credentials", "credentials_present"}) or _sensitive_key_seen(
        all_artifacts
    )
    live_trading_enabled = _truthy_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    exchange_mutation_enabled = _truthy_any(
        all_artifacts,
        {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"},
    )
    explicit_live_disabled = _falsey_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    explicit_exchange_mutation_disabled = _falsey_any(
        all_artifacts,
        {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"},
    )

    missing_fields: list[str] = []
    required_flags = {
        "production_alerting_integrated": production_alerting_integrated,
        "dashboard_integrated": dashboard_integrated,
        "stale_alerts_enabled": stale_alerts_enabled,
        "reconnect_alerts_enabled": reconnect_alerts_enabled,
        "lag_monitoring_enabled": lag_monitoring_enabled,
        "missing_source_alerts_enabled": missing_source_alerts_enabled,
        "public_market_data_only": public_market_data_only,
    }
    for field, value in required_flags.items():
        if not value:
            missing_fields.append(field)
    if contains_credentials:
        missing_fields.append("credential_free_public_payloads")
    if live_trading_enabled or not explicit_live_disabled:
        missing_fields.append("live_trading_disabled")
    if exchange_mutation_enabled or not explicit_exchange_mutation_disabled:
        missing_fields.append("exchange_mutation_disabled")

    passed = bool(alerting_artifacts and dashboard_artifacts and stream_status_artifacts) and not missing_fields

    return {
        "production_alerting_status": "passed" if passed else "failed",
        "status": "passed" if passed else "failed",
        "source": "local_production_stream_alerting_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "checked_at": _utc_now(),
        "production_alerting_integrated": production_alerting_integrated,
        "dashboard_integrated": dashboard_integrated,
        "stale_alerts_enabled": stale_alerts_enabled,
        "reconnect_alerts_enabled": reconnect_alerts_enabled,
        "lag_monitoring_enabled": lag_monitoring_enabled,
        "missing_source_alerts_enabled": missing_source_alerts_enabled,
        "public_market_data_only": public_market_data_only,
        "contains_credentials": contains_credentials,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "files_checked": {
            "alerting": len(alerting_artifacts),
            "dashboard": len(dashboard_artifacts),
            "stream_status": len(stream_status_artifacts),
        },
        "artifact_paths": [artifact.path for artifact in all_artifacts[:100]],
    }


def _paths(values: Sequence[str]) -> list[Path]:
    return [Path(value) for value in values if value]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe production stream alerting evidence smoke check")
    parser.add_argument("--alerting-config-path", action="append", default=[], help="Alerting evidence JSON/JSONL file or directory")
    parser.add_argument("--dashboard-evidence-path", action="append", default=[], help="Dashboard evidence JSON/JSONL file or directory")
    parser.add_argument("--stream-status-path", action="append", default=[], help="Stream-status JSON/JSONL file or directory")
    parser.add_argument("--output", required=True, help="JSON artifact path to write")
    args = parser.parse_args(argv)

    report = build_report(
        alerting_config_paths=_paths(args.alerting_config_path),
        dashboard_evidence_paths=_paths(args.dashboard_evidence_path),
        stream_status_paths=_paths(args.stream_status_path),
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["production_alerting_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
