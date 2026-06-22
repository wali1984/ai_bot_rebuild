#!/usr/bin/env python3
"""Validate Phase 13 visual-review evidence from safe local artifacts.

This command validates already-produced screenshot review metadata. It does not
launch a browser, inspect images, run OCR, call backend services, call exchanges,
submit/cancel orders, mutate leverage/margin, touch live gates, or enable live
trading. A passing artifact is evidence that a separate human/CI visual review
claimed coverage; it is not launch approval by itself.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

JSON_SUFFIXES = {".json", ".jsonl"}
REQUIRED_ROUTES = {
    "/",
    "/login",
    "/account-settings",
    "/status",
    "/dashboard",
    "/markets",
    "/markets/symbols",
    "/market/BTCUSDT",
    "/chart/BTCUSDT",
    "/trade",
    "/trade/paper",
    "/derivatives",
    "/signals",
    "/ai-predictions",
    "/ai-predictions/model-state",
    "/portfolio",
    "/portfolio/executions",
    "/portfolio/history",
    "/backtests",
    "/backtests/replay",
    "/research",
    "/research/technical-analysis",
    "/alerts",
    "/admin",
}
REQUIRED_VIEWPORTS = {"1920x1080", "1440x900", "768x1024", "390x844"}
TRUE_VALUES = {"1", "true", "yes", "y", "on", "pass", "passed", "ok", "verified", "reviewed"}
FALSE_VALUES = {"0", "false", "no", "n", "off", "fail", "failed", "missing", "pending", "none", "null"}


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


def _route(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.startswith("http://") or raw.startswith("https://"):
        raw = "/" + raw.split("/", 3)[3] if "/" in raw[8:] else "/"
    raw = raw.split("?", 1)[0].rstrip("/") or "/"
    if raw.startswith("/market/"):
        return "/market/BTCUSDT"
    return raw


def _viewport(row: dict[str, Any]) -> str | None:
    value = row.get("viewport") or row.get("size")
    if isinstance(value, str) and "x" in value:
        return value.strip().lower()
    width = row.get("width") or row.get("viewport_width")
    height = row.get("height") or row.get("viewport_height")
    if width and height:
        try:
            return f"{int(width)}x{int(height)}"
        except (TypeError, ValueError):
            return None
    return None


def _entries(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("screenshots", "reviews", "entries", "routes"):
        value = payload.get(key)
        if isinstance(value, list):
            return [row for row in value if isinstance(row, dict)]
    if payload.get("route") or payload.get("viewport"):
        return [payload]
    return []


def _row_passed(row: dict[str, Any]) -> bool:
    status = str(row.get("status") or row.get("result") or "").strip().lower()
    explicit_pass = status in {"pass", "passed", "fixed", "approved", "verified"} or _as_bool(row.get("pass")) is True
    required_true_fields = (
        "screenshot_exists",
        "human_reviewed",
        "visual_reviewed",
        "visual_pass",
        "professional_visual_pass",
        "copy_checked",
        "forbidden_strings_absent",
        "no_overflow",
        "responsive_pass",
        "data_honesty_checked",
        "missing_data_states_checked",
    )
    return explicit_pass and all(_as_bool(row.get(field)) is True for field in required_true_fields)


def build_report(*, review_artifact_paths: Sequence[Path]) -> dict[str, object]:
    warnings: list[str] = []
    artifacts = _load_json_artifacts(review_artifact_paths, warnings)
    if not artifacts:
        warnings.append("No Phase 13 visual-review artifacts were found")

    covered: dict[str, set[str]] = {route: set() for route in REQUIRED_ROUTES}
    failed_rows: list[dict[str, str]] = []
    forbidden_visible = False
    live_trading_enabled = False
    exchange_mutation_enabled = False

    for artifact in artifacts:
        for row in _entries(artifact.payload):
            route = _route(row.get("route") or row.get("path") or row.get("url"))
            viewport = _viewport(row)
            if _as_bool(row.get("forbidden_strings_visible")) is True:
                forbidden_visible = True
            if _as_bool(row.get("live_trading_enabled")) is True:
                live_trading_enabled = True
            if _as_bool(row.get("exchange_mutation_enabled")) is True:
                exchange_mutation_enabled = True
            if route in REQUIRED_ROUTES and viewport in REQUIRED_VIEWPORTS and _row_passed(row):
                covered[route].add(viewport)
            elif route in REQUIRED_ROUTES or viewport in REQUIRED_VIEWPORTS:
                failed_rows.append(
                    {
                        "artifact": artifact.path,
                        "route": route or "missing_route",
                        "viewport": viewport or "missing_viewport",
                    }
                )

    missing_fields: list[str] = []
    missing_pairs: list[str] = []
    for route in sorted(REQUIRED_ROUTES):
        for viewport in sorted(REQUIRED_VIEWPORTS):
            if viewport not in covered[route]:
                missing_pairs.append(f"{route}@{viewport}")
    if missing_pairs:
        missing_fields.append("full_route_viewport_visual_review_matrix")
    if forbidden_visible:
        missing_fields.append("no_forbidden_public_trader_strings")
    if live_trading_enabled:
        missing_fields.append("live_trading_disabled")
    if exchange_mutation_enabled:
        missing_fields.append("exchange_mutation_disabled")

    passed = bool(artifacts) and not missing_fields and not failed_rows
    return {
        "phase13_visual_review_status": "passed" if passed else "failed",
        "source": "local_phase13_visual_review_smoke",
        "source_type": "local_smoke",
        "mode": "read_only",
        "generated_at": _utc_now(),
        "required_routes": sorted(REQUIRED_ROUTES),
        "required_viewports": sorted(REQUIRED_VIEWPORTS),
        "covered_route_viewport_count": sum(len(viewports) for viewports in covered.values()),
        "required_route_viewport_count": len(REQUIRED_ROUTES) * len(REQUIRED_VIEWPORTS),
        "missing_pairs": missing_pairs[:200],
        "failed_rows": failed_rows[:100],
        "forbidden_strings_visible": forbidden_visible,
        "live_trading_enabled": live_trading_enabled,
        "exchange_mutation_enabled": exchange_mutation_enabled,
        "missing_fields": missing_fields,
        "warnings": warnings,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-artifact-path", action="append", type=Path, default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    report = build_report(review_artifact_paths=args.review_artifact_path)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0 if report["phase13_visual_review_status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
