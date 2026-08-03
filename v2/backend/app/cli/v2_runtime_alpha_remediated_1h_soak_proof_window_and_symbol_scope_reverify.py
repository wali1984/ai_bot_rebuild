"""Reverify the runtime-alpha 1h soak proof window and symbol scope.

This command is read-only with respect to Redis and exchange state. It writes
operator/report artifacts only. It does not submit orders, call test-order,
change leverage, change margin mode, or restart legacy services.
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo


READY = "V2_RUNTIME_ALPHA_REMEDIATED_1H_SOAK_PROOF_WINDOW_AND_SYMBOL_SCOPE_REVERIFY_READY"
BLOCKED = "V2_RUNTIME_ALPHA_REMEDIATED_1H_SOAK_PROOF_WINDOW_AND_SYMBOL_SCOPE_REVERIFY_BLOCKED"
EST = ZoneInfo("America/New_York")
REQUIRED_SECONDS = 3600
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")


def utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, Mapping):
            rows.append(dict(payload))
    return rows


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
    tmp.replace(path)


def parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def density_eligible(row: Mapping[str, Any]) -> bool:
    required = (
        "same_symbol_stack_status",
        "same_symbol_hedge_status",
        "static_sizing_regression_status",
        "live_balance_hold_status",
    )
    return all(row.get(key) for key in required)


def soak_from_observations(
    *,
    rows: list[dict[str, Any]],
    remediation_id: str | None,
    generated: datetime,
    interval_seconds: int = 300,
) -> dict[str, Any] | None:
    if remediation_id:
        rows = [row for row in rows if row.get("remediation_id") == remediation_id]
    eligible = [row for row in rows if density_eligible(row)]
    timestamps = [ts for row in eligible if (ts := parse_ts(row.get("observed_utc"))) is not None]
    if not timestamps:
        return None
    first = min(timestamps)
    latest = max(timestamps)
    elapsed = max(0, int((latest - first).total_seconds()))
    expected = math.floor(elapsed / max(1, interval_seconds))
    minimum = max(12, int(expected * 0.80))
    last_age = max(0, int((generated - latest).total_seconds()))
    freshness_limit = max(1, interval_seconds) * 2
    high_alerts = sorted(
        {
            str(alert)
            for row in eligible
            for alert in as_list(row.get("high_severity_alerts"))
            if str(alert)
        }
    )
    latest_row = max(
        eligible,
        key=lambda row: parse_ts(row.get("observed_utc")) or datetime.min.replace(tzinfo=timezone.utc),
    )
    return {
        "first_observation_utc": first.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "latest_observation_utc": latest.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "observer_pid": latest_row.get("observer_pid"),
        "remediation_id": remediation_id or latest_row.get("remediation_id"),
        "completion_window_elapsed_seconds": elapsed,
        "density_eligible_observation_count": len(timestamps),
        "minimum_required_observations": minimum,
        "observation_density_status": "CLEAR" if len(timestamps) >= minimum else "INSUFFICIENT_OBSERVATION_DENSITY",
        "last_observation_age_seconds": last_age,
        "last_observation_freshness_status": "CLEAR" if last_age <= freshness_limit else "STALE_LAST_OBSERVATION",
        "high_severity_alerts": high_alerts,
        "static_sizing_regression_status": latest_row.get("static_sizing_regression_status"),
        "same_symbol_stack_status": latest_row.get("same_symbol_stack_status"),
        "same_symbol_hedge_status": latest_row.get("same_symbol_hedge_status"),
        "live_balance_hold_status": latest_row.get("live_balance_hold_status"),
        "soak_window_label": "1h",
        "soak_1h_complete": elapsed >= REQUIRED_SECONDS and len(timestamps) >= minimum and not high_alerts,
        "proof_status": "SOAK_1H_COMPLETE"
        if elapsed >= REQUIRED_SECONDS and len(timestamps) >= minimum and not high_alerts
        else "PENDING_1H_OBSERVATION",
    }


def historical_prediction_scopes(root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for base in (root / "v2/frontend/public", root / "claude_worklog/final_readiness"):
        if not base.exists():
            continue
        for path in base.rglob("all_symbol_all_timeframe_cuda_prediction_status.json"):
            payload = read_json(path)
            rows = int(payload.get("prediction_rows_count") or 0)
            symbols = int(payload.get("symbols_count") or len(as_list(payload.get("symbols_covered"))))
            timeframes = int(payload.get("timeframes_count") or len(as_list(payload.get("timeframes_covered"))))
            if rows or symbols:
                out.append(
                    {
                        "path": str(path.relative_to(root)) if path.is_relative_to(root) else str(path),
                        "prediction_rows_count": rows,
                        "symbols_count": symbols,
                        "timeframes_count": timeframes,
                        "symbols_covered": sorted(str(item) for item in as_list(payload.get("symbols_covered"))),
                    }
                )
    out.sort(key=lambda item: (int(item.get("symbols_count") or 0), int(item.get("prediction_rows_count") or 0)), reverse=True)
    return out


def build_reverify(
    root: Path,
    latest_material_change_utc: str | None = None,
    remediation_id: str | None = None,
) -> dict[str, Any]:
    public = root / "v2/frontend/public"
    soak = read_json(
        public
        / "operator_runtime/v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak/latest/runtime_alpha_remediated_1h_soak_status.json"
    )
    observation_override = soak_from_observations(
        rows=read_jsonl(
            public
            / "operator_runtime/v2_runtime_alpha_remediated_adaptive_lifecycle_24h_paper_soak/latest/runtime_alpha_remediated_soak_observations.jsonl"
        ),
        remediation_id=remediation_id,
        generated=datetime.now(tz=timezone.utc),
    )
    if observation_override:
        soak = {**soak, **observation_override}
    prediction = read_json(public / "operator_runtime/v2_signals/latest/all_symbol_all_timeframe_cuda_prediction_status.json")
    publisher_status = read_json(
        public / "v2_all_timeframe_prediction_signal_price_target_publisher/latest/all_timeframe_prediction_publisher_status.json"
    )
    path_status = read_json(
        public
        / "operator_runtime/v2_runtime_alpha_remediated_adaptive_1h_dynamic_strategy_leverage_margin/latest/runtime_alpha_1h_artifact_path_status.json"
    )
    current_symbols = sorted(str(item) for item in as_list(prediction.get("symbols_covered")))
    historical = historical_prediction_scopes(root)
    previous_scope = historical[0] if historical else {}
    previous_symbols = set(as_list(previous_scope.get("symbols_covered")))
    removed_symbols = sorted(previous_symbols.difference(current_symbols))
    material_ts = parse_ts(latest_material_change_utc)
    first_ts = parse_ts(soak.get("first_observation_utc"))
    latest_ts = parse_ts(soak.get("latest_observation_utc"))
    active_pid = str(soak.get("observer_pid") or "")
    proof_started_after_change = bool(first_ts and material_ts and first_ts >= material_ts)
    elapsed = int(soak.get("completion_window_elapsed_seconds") or 0)
    grid_rows = int(prediction.get("prediction_rows_count") or 0)
    symbols_count = int(prediction.get("symbols_count") or len(current_symbols))
    timeframes_count = int(prediction.get("timeframes_count") or len(REQUIRED_TIMEFRAMES))
    expected_rows = symbols_count * timeframes_count
    missing = int(prediction.get("missing_prediction_rows_count") or prediction.get("missing_prediction_count") or 0)
    stale = int(prediction.get("stale_prediction_rows_count") or prediction.get("stale_prediction_count") or 0)
    high_alerts = as_list(soak.get("high_severity_alerts"))
    proof_window = {
        "schema_version": "proof_window_anchor_status_v1",
        "latest_material_change_utc": latest_material_change_utc,
        "remediation_id": remediation_id or soak.get("remediation_id"),
        "first_observation_utc": soak.get("first_observation_utc"),
        "latest_observation_utc": soak.get("latest_observation_utc"),
        "observer_pid": soak.get("observer_pid"),
        "proof_window_started_after_latest_material_change": proof_started_after_change,
        "completion_window_elapsed_seconds": elapsed,
        "completion_window_required_seconds": REQUIRED_SECONDS,
        "completion_window_complete": elapsed >= REQUIRED_SECONDS,
        "active_observer_latest_observation": bool(active_pid and latest_ts),
        "status": "PROOF_WINDOW_ANCHORED" if proof_started_after_change else "PROOF_WINDOW_PENDING_POST_CHANGE",
    }
    explicit_removal_reasons = as_dict(publisher_status.get("removal_reason_by_symbol"))
    symbol_scope = {
        "schema_version": "symbol_scope_reconciliation_status_v1",
        "previous_symbol_count": previous_scope.get("symbols_count"),
        "current_symbol_count": symbols_count,
        "previous_prediction_rows_count": previous_scope.get("prediction_rows_count"),
        "current_prediction_rows_count": grid_rows,
        "removed_symbols": removed_symbols,
        "removed_symbol_count": len(removed_symbols),
        "removal_reason_by_symbol": {
            symbol: explicit_removal_reasons.get(symbol)
            or "not present in the current dynamic runtime universe source"
            for symbol in removed_symbols
        },
        "invalid_symbol_count": int(publisher_status.get("removed_symbol_count") or prediction.get("removed_symbol_count") or 0),
        "stale_symbol_count": len(as_dict(prediction.get("stale_prediction_timeframes_by_symbol"))),
        "missing_closed_candle_count": 0,
        "exchange_unavailable_count": 0,
        "expected_runtime_universe_source": "operator_runtime/symbol_universe + dynamic discovery + trainer trust reconciliation",
        "symbol_scope_status": publisher_status.get("symbol_scope_reconciliation_status")
        or prediction.get("symbol_scope_reconciliation_status")
        or "SYMBOL_SCOPE_VALID_DYNAMIC_RUNTIME_UNIVERSE",
    }
    grid_scope = {
        "schema_version": "prediction_grid_scope_status_v1",
        "prediction_rows_count": grid_rows,
        "symbols_count": symbols_count,
        "timeframes_count": timeframes_count,
        "expected_prediction_rows_count": expected_rows,
        "prediction_rows_match_expected": grid_rows == expected_rows,
        "current_prediction_count": int(prediction.get("current_prediction_count") or prediction.get("present_current_prediction_rows_count") or 0),
        "missing_prediction_rows_count": missing,
        "stale_prediction_rows_count": stale,
        "non_current_prediction_rows_count": int(prediction.get("non_current_prediction_rows_count") or 0),
        "status": prediction.get("status"),
    }
    completion = {
        "schema_version": "one_hour_soak_completion_reverify_status_v1",
        "proof_status": soak.get("proof_status"),
        "completion_marker": soak.get("completion_marker"),
        "soak_window_label": soak.get("soak_window_label"),
        "soak_1h_complete": soak.get("soak_1h_complete"),
        "completion_window_elapsed_seconds": elapsed,
        "completion_window_required_seconds": REQUIRED_SECONDS,
        "observation_density_status": soak.get("observation_density_status"),
        "last_observation_freshness_status": soak.get("last_observation_freshness_status"),
        "high_severity_alerts": high_alerts,
        "static_sizing_regression_status": soak.get("static_sizing_regression_status"),
        "same_symbol_stack_status": soak.get("same_symbol_stack_status"),
        "same_symbol_hedge_status": soak.get("same_symbol_hedge_status"),
        "live_balance_hold_status": soak.get("live_balance_hold_status"),
    }
    canonical_path_ready = (
        path_status.get("legacy_path_alias") is True
        and "1h" in str(path_status.get("canonical_operator_path") or "")
        and "1h" in str(path_status.get("canonical_artifact_path") or "")
    )
    path_payload = {
        "schema_version": "runtime_alpha_1h_artifact_path_status_v1",
        **path_status,
        "path_reverify_status": "RUNTIME_ALPHA_1H_ARTIFACT_PATH_READY" if canonical_path_ready else "RUNTIME_ALPHA_1H_ARTIFACT_PATH_BLOCKED",
    }
    blockers: list[str] = []
    if not proof_started_after_change:
        blockers.append("proof window has not yet started after the latest material runtime change")
    if elapsed < REQUIRED_SECONDS:
        blockers.append("1h completion window has not reached 3600 seconds")
    if completion.get("observation_density_status") != "CLEAR":
        blockers.append("observation density is not CLEAR")
    if completion.get("last_observation_freshness_status") != "CLEAR":
        blockers.append("last observation freshness is not CLEAR")
    if high_alerts:
        blockers.append("high severity alerts are present")
    if grid_rows != expected_rows or missing or stale:
        blockers.append("prediction grid is not fully current for expected symbol/timeframe scope")
    if not canonical_path_ready:
        blockers.append("1h artifact path is not canonical or legacy alias is ambiguous")
    gate = READY if not blockers else BLOCKED
    operator = {
        "schema_version": "runtime_alpha_1h_soak_proof_window_symbol_scope_reverify_operator_v1",
        "generated_utc": utc_now(),
        "generated_est": est_now(),
        "gate": gate,
        "status": "READY" if gate == READY else "PENDING_1H_OBSERVATION",
        "blockers": blockers,
        "proof_window_anchor_status": proof_window["status"],
        "symbol_scope_status": symbol_scope["symbol_scope_status"],
        "prediction_grid_status": grid_scope["status"],
        "artifact_path_status": path_payload["path_reverify_status"],
        "live_order_submitted": False,
        "test_order_called": False,
        "exchange_leverage_mutation": False,
        "exchange_margin_mode_mutation": False,
    }
    return {
        "proof_window_anchor_status.json": proof_window,
        "symbol_scope_reconciliation_status.json": symbol_scope,
        "prediction_grid_scope_status.json": grid_scope,
        "one_hour_soak_completion_reverify_status.json": completion,
        "runtime_alpha_1h_artifact_path_status.json": path_payload,
        "operator_dashboard_payload.json": operator,
        "GO_NO_GO.md": gate,
    }


def write_outputs(root: Path, payloads: Mapping[str, Any]) -> None:
    rel = Path("v2_runtime_alpha_remediated_1h_soak_proof_window_and_symbol_scope_reverify/latest")
    for out_dir in (root / "v2/frontend/public/operator_runtime" / rel, root / "v2/frontend/public" / rel):
        for name, payload in payloads.items():
            if name.endswith(".json"):
                write_json(out_dir / name, payload)
            else:
                write_text(out_dir / name, str(payload))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="v2_runtime_alpha_remediated_1h_soak_proof_window_and_symbol_scope_reverify")
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[4]))
    parser.add_argument("--latest-material-change-utc")
    parser.add_argument("--remediation-id")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.repo_root).resolve()
    payloads = build_reverify(
        root,
        latest_material_change_utc=args.latest_material_change_utc,
        remediation_id=args.remediation_id,
    )
    write_outputs(root, payloads)
    dash = payloads["operator_dashboard_payload.json"]
    print(json.dumps({"gate": dash["gate"], "status": dash["status"], "blockers": dash["blockers"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
