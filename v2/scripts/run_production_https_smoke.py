#!/usr/bin/env python3
"""Generate a production HTTPS smoke evidence artifact from safe evidence files.

This command validates already-produced deployment smoke evidence for HTTPS route
checks, public-safe status, browser console checks, auth gates, secret exposure,
and no-live-mutation posture. It does not submit orders, cancel orders, mutate
leverage/margin, touch the live gate, call Binance, or enable live trading.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence
from urllib.parse import urlparse

JSON_SUFFIXES = {".json", ".jsonl"}
REQUIRED_ROUTE_HINTS = {
    "/",
    "/login",
    "/status",
    "/dashboard",
    "/markets",
    "/market/BTCUSDT",
    "/trade",
    "/account-settings",
    "/chart/BTCUSDT",
    "/admin",
}
SENSITIVE_KEY_PARTS = {
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "access_token",
    "refresh_token",
    "authorization",
    "x_mbx_apikey",
    "x-mbx-apikey",
    "credential_reference",
    "credential_ref",
}
TRUE_VALUES = {"1", "true", "yes", "y", "on", "enabled", "pass", "passed", "ok", "verified"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "disabled", "fail", "failed", "missing", "pending", "none", "null"}
SAFE_SECRET_VALUES = {"", "none", "null", "redacted", "[redacted]", "masked", "hidden", "configured", "pending", "unavailable"}
SECRET_EXPOSURE_FLAG_KEYS = {
    "contains_credentials",
    "credentials_present",
    "raw_secret_visible",
    "secret_exposure_found",
    "secrets_exposed",
}


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
            yield str(index), value
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


def _numeric_zero_any(artifacts: Sequence[LoadedArtifact], aliases: set[str]) -> bool:
    normalized_aliases = {alias.lower() for alias in aliases}
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            if key.split(".")[-1].lower() not in normalized_aliases:
                continue
            try:
                if float(value) == 0:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def _https_url_seen(artifacts: Sequence[LoadedArtifact]) -> bool:
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            if key.split(".")[-1].lower() in {"base_url", "url", "origin", "deployment_url"}:
                if str(value).strip().lower().startswith("https://"):
                    return True
    return False


def _http_url_seen(artifacts: Sequence[LoadedArtifact]) -> bool:
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            if key.split(".")[-1].lower() in {"base_url", "url", "origin", "deployment_url"}:
                if str(value).strip().lower().startswith("http://"):
                    return True
    return False


def _normalized_route(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        path = parsed.path or "/"
    elif raw.startswith("/"):
        path = raw
    else:
        return None
    normalized = path.split("?", 1)[0].rstrip("/")
    return normalized or "/"


def _route_coverage(route_artifacts: Sequence[LoadedArtifact]) -> tuple[bool, list[str]]:
    seen: set[str] = set()
    for artifact in route_artifacts:
        for _key, value in _flatten(artifact.payload):
            route = _normalized_route(value)
            if route is not None:
                seen.add(route)
    missing = sorted(route for route in REQUIRED_ROUTE_HINTS if route not in seen)
    return not missing, missing


def _sensitive_value_seen(artifacts: Sequence[LoadedArtifact]) -> bool:
    for artifact in artifacts:
        for key, value in _flatten(artifact.payload):
            normalized_key = key.split(".")[-1].lower().replace("-", "_")
            if normalized_key in SECRET_EXPOSURE_FLAG_KEYS:
                continue
            if any(part.replace("-", "_") in normalized_key for part in SENSITIVE_KEY_PARTS):
                normalized_value = str(value).strip().lower()
                if normalized_value not in SAFE_SECRET_VALUES:
                    return True
    return False


def build_report(
    *,
    route_evidence_paths: Sequence[Path],
    status_evidence_paths: Sequence[Path],
    auth_evidence_paths: Sequence[Path],
    console_evidence_paths: Sequence[Path],
    safety_evidence_paths: Sequence[Path],
) -> dict[str, object]:
    warnings: list[str] = []
    route_artifacts = _load_json_artifacts(route_evidence_paths, warnings)
    status_artifacts = _load_json_artifacts(status_evidence_paths, warnings)
    auth_artifacts = _load_json_artifacts(auth_evidence_paths, warnings)
    console_artifacts = _load_json_artifacts(console_evidence_paths, warnings)
    safety_artifacts = _load_json_artifacts(safety_evidence_paths, warnings)
    all_artifacts = [*route_artifacts, *status_artifacts, *auth_artifacts, *console_artifacts, *safety_artifacts]

    if not route_artifacts:
        warnings.append("No HTTPS route smoke evidence artifacts were found")
    if not status_artifacts:
        warnings.append("No public status smoke evidence artifacts were found")
    if not auth_artifacts:
        warnings.append("No auth-gate smoke evidence artifacts were found")
    if not console_artifacts:
        warnings.append("No browser console smoke evidence artifacts were found")
    if not safety_artifacts:
        warnings.append("No no-live-mutation smoke evidence artifacts were found")

    https_enabled = _truthy_any(route_artifacts, {"https_enabled", "https", "tls_enabled"}) or _https_url_seen(route_artifacts)
    insecure_http_seen = _http_url_seen(route_artifacts)
    routes_checked, missing_routes = _route_coverage(route_artifacts)
    public_status_checked = _truthy_any(status_artifacts, {"public_status_checked", "status_checked", "status_page_checked"})
    public_status_safe = _truthy_any(status_artifacts, {"public_status_safe", "status_safe", "no_sensitive_status_fields"})
    auth_gate_checked = _truthy_any(auth_artifacts, {"auth_gate_checked", "admin_auth_gate_checked", "rbac_checked"})
    admin_unauthenticated_blocked = _truthy_any(auth_artifacts, {"admin_unauthenticated_blocked", "unauthenticated_admin_blocked"})
    superadmin_admin_rejected = _truthy_any(auth_artifacts, {"superadmin_admin_rejected", "admin_rejected_from_superadmin"})
    console_errors_absent = _truthy_any(console_artifacts, {"console_errors_absent", "no_console_errors"}) or _numeric_zero_any(console_artifacts, {"console_error_count", "errors_count"})
    secret_exposure_found = _truthy_any(all_artifacts, {"secret_exposure_found", "secrets_exposed", "raw_secret_visible"}) or _sensitive_value_seen(all_artifacts)
    live_trading_enabled = _truthy_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    exchange_mutation_enabled = _truthy_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})
    live_submit_available = _truthy_any(safety_artifacts, {"live_submit_available", "live_submit_button_visible", "live_order_submit_available"})
    live_cancel_available = _truthy_any(safety_artifacts, {"live_cancel_available", "live_cancel_button_visible", "live_order_cancel_available"})
    leverage_mutation_available = _truthy_any(safety_artifacts, {"leverage_mutation_available", "leverage_change_available"})
    margin_mutation_available = _truthy_any(safety_artifacts, {"margin_mutation_available", "margin_mode_change_available"})
    explicit_live_disabled = _falsey_any(all_artifacts, {"live_trading_enabled", "live_trading", "live_enabled"})
    explicit_exchange_mutation_disabled = _falsey_any(all_artifacts, {"exchange_mutation_enabled", "exchange_writes_enabled", "order_writes_enabled"})

    missing_fields: list[str] = []
    required_flags = {
        "https_enabled": https_enabled,
        "routes_checked": routes_checked,
        "public_status_checked": public_status_checked,
        "public_status_safe": public_status_safe,
        "auth_gate_checked": auth_gate_checked,
        "admin_unauthenticated_blocked": admin_unauthenticated_blocked,
        "superadmin_admin_rejected": superadmin_admin_rejected,
        "console_errors_absent": console_errors_absent,
    }
    for field, value in required_flags.items():
        if not value:
            missing_fields.append(field)
    if insecure_http_seen:
        missing_fields.append("no_insecure_http_origin")
    if secret_exposure_found:
        missing_fields.append("no_secret_exposure")
    if live_trading_enabled or not explicit_live_disabled:
        missing_fields.append("live_trading_disabled")
    if exchange_mutation_enabled or not explicit_exchange_mutation_disabled:
        missing_fields.append("exchange_mutation_disabled")
    if live_submit_available:
        missing_fields.append("live_submit_unavailable")
    if live_cancel_available:
        missing_fields.append("live_cancel_unavailable")
    if leverage_mutation_available:
        missing_fields.append("leverage_mutation_unavailable")
    if margin_mutation_available:
        missing_fields.append("margin_mutation_unavailable")
    for route in missing_routes:
        missing_fields.append(f"route_checked:{route}")

    passed = bool(route_artifacts and status_artifacts and auth_artifacts and console_artifacts and safety_artifacts) and not missing_fields

    return {
        "production_https_smoke_status": "passed" if passed else "failed",
        "status": "passed" if passed else "failed",
        "source": "local_production_https_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "checked_at": _utc_now(),
        "https_enabled": https_enabled,
        "routes_checked": routes_checked,
        "missing_routes": missing_routes,
        "public_status_checked": public_status_checked,
        "public_status_safe": public_status_safe,
        "auth_gate_checked": auth_gate_checked,
        "admin_unauthenticated_blocked": admin_unauthenticated_blocked,
        "superadmin_admin_rejected": superadmin_admin_rejected,
        "console_errors_absent": console_errors_absent,
        "secret_exposure_found": secret_exposure_found,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "live_submit_available": live_submit_available,
        "live_cancel_available": live_cancel_available,
        "leverage_mutation_available": leverage_mutation_available,
        "margin_mutation_available": margin_mutation_available,
        "missing_fields": missing_fields,
        "warnings": warnings,
        "files_checked": {
            "routes": len(route_artifacts),
            "status": len(status_artifacts),
            "auth": len(auth_artifacts),
            "console": len(console_artifacts),
            "safety": len(safety_artifacts),
        },
        "artifact_paths": [artifact.path for artifact in all_artifacts[:100]],
    }


def _paths(values: Sequence[str]) -> list[Path]:
    return [Path(value) for value in values if value]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run a safe production HTTPS smoke evidence check")
    parser.add_argument("--route-evidence-path", action="append", default=[], help="HTTPS route smoke evidence JSON/JSONL file or directory")
    parser.add_argument("--status-evidence-path", action="append", default=[], help="Public status evidence JSON/JSONL file or directory")
    parser.add_argument("--auth-evidence-path", action="append", default=[], help="Auth/RBAC smoke evidence JSON/JSONL file or directory")
    parser.add_argument("--console-evidence-path", action="append", default=[], help="Browser console smoke evidence JSON/JSONL file or directory")
    parser.add_argument("--safety-evidence-path", action="append", default=[], help="No-live-mutation safety evidence JSON/JSONL file or directory")
    parser.add_argument("--output", required=True, help="JSON artifact path to write")
    args = parser.parse_args(argv)

    report = build_report(
        route_evidence_paths=_paths(args.route_evidence_path),
        status_evidence_paths=_paths(args.status_evidence_path),
        auth_evidence_paths=_paths(args.auth_evidence_path),
        console_evidence_paths=_paths(args.console_evidence_path),
        safety_evidence_paths=_paths(args.safety_evidence_path),
    )

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["production_https_smoke_status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
