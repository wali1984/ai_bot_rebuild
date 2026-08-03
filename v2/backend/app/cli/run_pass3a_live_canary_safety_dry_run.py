"""Pass 3A live-canary safety dry run.

Read-only command. It never submits orders, changes leverage, changes margin
mode, writes Redis, or mutates exchange state.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from app.services.live_gate.live_position_state_machine import (
    LiveCanaryConfig,
    evaluate_live_canary_preflight,
)
from app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_pass3a_live_canary_safety_dry_run")
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)

    client = redis_client(args.redis_url)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    out_dir = Path(args.output_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    report = run_dry_run(client=client, redis_url=args.redis_url, run_id=run_id, output_dir=out_dir)
    (out_dir / "pass3a_live_canary_safety_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    md_name = f"PASS3A_LIVE_CANARY_SAFETY_REPORT_{run_id}.md"
    (out_dir / md_name).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True, default=str))
    return 0


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def run_dry_run(*, client: Any, redis_url: str, run_id: str, output_dir: Path) -> dict[str, Any]:
    live_gate_state = read_json(client, "v2:live_gate:state")
    trader_execution_state = read_json(client, "v2:trader:execution_state")
    live_transport_status = read_json(client, "v2:live_order_transport:status")
    predictions = read_pattern(client, "v2:prediction:*")
    replay_count = count_pattern(client, "v2:replay:snapshots:*")
    mtf_count = count_pattern(client, "v2:market:mtf_snapshot:*") + count_pattern(client, "v2:decision:mtf_snapshot:*") + count_pattern(client, "v2:mtf_snapshot:*")
    trusted_predictions = [payload for _, payload in predictions if is_trusted_prediction(payload)]
    selected = trusted_predictions[-1] if trusted_predictions else None
    config = LiveCanaryConfig.from_mapping((live_gate_state or {}).get("live_canary_config") or {})
    action = str((selected or {}).get("selected_action") or (selected or {}).get("action") or "hold").lower()
    symbol = str((selected or {}).get("symbol") or "").upper()
    quantity = numeric((selected or {}).get("quantity"), 0.0)
    notional = numeric((selected or {}).get("requested_notional_usdt") or (selected or {}).get("notional_usd"), 0.0)
    signed_ts = numeric((live_transport_status or {}).get("signed_read_ts_ms"), 0.0) or None
    exchange_position = as_dict((live_transport_status or {}).get("exchange_position"))
    local_position = as_dict((trader_execution_state or {}).get("local_position") or (live_gate_state or {}).get("local_position"))
    open_orders = as_list((live_transport_status or {}).get("open_orders"))
    strict_status = latest_report_summary("pipeline_trust_evidence_pass3a")
    recorded_status = latest_recorded_summary("recorded_state_verification_pass3a")
    strict_ok = (strict_status.get("critical_failures") == 0) if strict_status else False
    replay_exists = bool((selected or {}).get("replay_snapshot_id")) and replay_count > 0
    mtf_exists = bool((selected or {}).get("mtf_snapshot_id")) and mtf_count > 0
    preflight = evaluate_live_canary_preflight(
        config=config,
        decision=selected,
        replay_snapshot_exists=replay_exists,
        mtf_snapshot_exists=mtf_exists,
        strict_pipeline_trust_ok=strict_ok,
        pass2a_trusted_decision_ok=bool(selected),
        runtime_payload=live_gate_state,
        local_position=local_position,
        exchange_position=exchange_position,
        open_orders=[item for item in open_orders if isinstance(item, Mapping)],
        hedge_mode=(live_transport_status or {}).get("position_mode_status", {}).get("dual_side_position")
        if isinstance((live_transport_status or {}).get("position_mode_status"), Mapping)
        else None,
        margin_mode=str((live_transport_status or {}).get("margin_mode") or ""),
        signed_read_ts_ms=signed_ts,
        requested_action=action,
        symbol=symbol,
        quantity=quantity,
        notional_usd=notional,
        reduce_only=bool((selected or {}).get("reduce_only")),
        open_positions_count=int(numeric((live_gate_state or {}).get("open_positions_count"), 0.0)),
        daily_order_count=int(numeric((live_gate_state or {}).get("daily_order_count"), 0.0)),
        daily_loss_usd=numeric((live_gate_state or {}).get("daily_loss_usd"), 0.0),
        kill_switch_active=(live_gate_state or {}).get("kill_switch_active") is True,
        human_operator_armed=(live_gate_state or {}).get("live_canary_human_armed") is True,
        lifecycle_status=as_dict((live_gate_state or {}).get("order_lifecycle_status")),
    )
    return {
        "run_id": run_id,
        "generated_at": utc_now(),
        "redis_url": redact_redis_url(redis_url),
        "output_dir": str(output_dir),
        "strict_verifier_status": strict_status or {"status": "not_available"},
        "recorded_state_verifier_status": recorded_status or {"status": "not_available"},
        "live_control_state": {
            "live_gate": (live_gate_state or {}).get("live_gate"),
            "order_transport_submit_enabled": (live_gate_state or {}).get("order_transport_submit_enabled"),
            "live_trading_enabled": (live_gate_state or {}).get("live_trading_enabled"),
            "places_real_order": (live_gate_state or {}).get("places_real_order"),
            "exchange_action_taken": (live_gate_state or {}).get("exchange_action_taken"),
            "release_mode": (live_gate_state or {}).get("release_mode"),
            "transport_order_submitted": (live_transport_status or {}).get("order_submitted"),
        },
        "trusted_prediction_count": len(trusted_predictions),
        "replay_snapshot_count": replay_count,
        "mtf_snapshot_count": mtf_count,
        "selected_candidate_decision": summarize_decision(selected),
        "state_machine_result": preflight.get("state_machine"),
        "exchange_local_reconciliation_result": preflight.get("exchange_local_reconciliation"),
        "lifecycle_safety_result": preflight.get("order_lifecycle"),
        "canary_cap_result": preflight.get("canary_caps"),
        "preflight": preflight,
        "submit_allowed": bool(preflight.get("submit_allowed")),
        "submit_block_reason": preflight.get("reason_code"),
        "live_canary_enabled": bool(preflight.get("live_canary_enabled")),
        "order_transport_submit_enabled": (live_gate_state or {}).get("order_transport_submit_enabled") is True,
        "live_trading_enabled": (live_gate_state or {}).get("live_trading_enabled") is True,
        "places_real_order": False,
        "exchange_action_taken": False,
        "live_order_submitted": False,
    }


def read_json(client: Any, key: str) -> dict[str, Any]:
    try:
        raw = client.get(key)
    except Exception:
        return {}
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def read_pattern(client: Any, pattern: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    try:
        keys = sorted(client.scan_iter(match=pattern, count=500))
    except Exception:
        return out
    for key in keys:
        payload = read_json(client, str(key))
        if payload:
            out.append((str(key), payload))
    return out


def count_pattern(client: Any, pattern: str) -> int:
    try:
        return len(list(client.scan_iter(match=pattern, count=500)))
    except Exception:
        return 0


def latest_report_summary(root: str) -> dict[str, Any]:
    base = Path(root)
    if not base.exists():
        return {}
    reports = sorted(base.glob("*/report/pipeline_trust_report.json"))
    if not reports:
        return {}
    try:
        return dict((json.loads(reports[-1].read_text(encoding="utf-8")).get("summary") or {}))
    except Exception:
        return {"critical_failures": 1, "status": "parse_failed"}


def latest_recorded_summary(root: str) -> dict[str, Any]:
    base = Path(root)
    if not base.exists():
        return {}
    reports = sorted(base.glob("*/recorded_state_verification_report.json"))
    if not reports:
        return {}
    try:
        payload = json.loads(reports[-1].read_text(encoding="utf-8"))
    except Exception:
        return {"status": "parse_failed"}
    return dict(payload.get("metrics") or payload.get("summary") or {})


def is_trusted_prediction(payload: Mapping[str, Any]) -> bool:
    return payload.get("trust_schema_version") == TRUST_SCHEMA_VERSION and bool(payload.get("prediction_id"))


def summarize_decision(payload: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not payload:
        return None
    return {
        "symbol": payload.get("symbol"),
        "selected_action": payload.get("selected_action") or payload.get("action"),
        "prediction_id": payload.get("prediction_id"),
        "decision_id": payload.get("decision_id"),
        "mtf_snapshot_id": payload.get("mtf_snapshot_id"),
        "replay_snapshot_id": payload.get("replay_snapshot_id"),
        "trust_schema_version": payload.get("trust_schema_version"),
        "routes_to_live": payload.get("routes_to_live"),
        "live_order_allowed": payload.get("live_order_allowed"),
    }


def as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def numeric(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed == parsed else default


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def redact_redis_url(value: str) -> str:
    if "@" not in value:
        return value
    scheme, rest = value.split("://", 1)
    return f"{scheme}://***@{rest.split('@', 1)[1]}"


def render_markdown(report: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            f"# Pass 3A Live-Canary Safety Report: {report.get('run_id')}",
            "",
            f"Generated: `{report.get('generated_at')}`",
            "",
            "| Field | Value |",
            "|---|---:|",
            f"| Submit allowed | `{report.get('submit_allowed')}` |",
            f"| Submit block reason | `{report.get('submit_block_reason')}` |",
            f"| Live canary enabled | `{report.get('live_canary_enabled')}` |",
            f"| Order transport submit enabled | `{report.get('order_transport_submit_enabled')}` |",
            f"| Live trading enabled | `{report.get('live_trading_enabled')}` |",
            f"| Places real order | `{report.get('places_real_order')}` |",
            f"| Exchange action taken | `{report.get('exchange_action_taken')}` |",
            f"| Live order submitted | `{report.get('live_order_submitted')}` |",
            f"| Trusted predictions | `{report.get('trusted_prediction_count')}` |",
            f"| Replay snapshots | `{report.get('replay_snapshot_count')}` |",
            f"| MTF snapshots | `{report.get('mtf_snapshot_count')}` |",
            "",
            "## Preflight blockers",
            "",
            "```json",
            json.dumps((report.get("preflight") or {}).get("blockers") or [], indent=2),
            "```",
        ]
    ) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
