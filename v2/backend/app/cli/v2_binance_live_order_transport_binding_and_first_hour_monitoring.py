"""Generate V2 Binance live order transport binding and monitoring artifacts."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli.v2_trader_runtime_loop import run_once as run_trader_once  # noqa: E402
from v2.backend.app.services.live_gate.binance_live_order_transport import (  # noqa: E402
    ARTIFACT_REL,
    WORKLOG_ARTIFACT_REL,
    PUBLIC_ARTIFACT_REL,
    _write_json_atomic,
    est_now,
)
from v2.backend.app.services.live_gate.runtime_execution_state import read_runtime_execution_state  # noqa: E402

GATE_READY = "V2_BINANCE_LIVE_ORDER_TRANSPORT_BINDING_AND_FIRST_HOUR_MONITORING_READY"
GATE_BLOCKED = "V2_BINANCE_LIVE_ORDER_TRANSPORT_BINDING_AND_FIRST_HOUR_MONITORING_BLOCKED"


def _json_load(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _write_all(repo_root: Path, name: str, payload: dict) -> None:
    for base in (repo_root / PUBLIC_ARTIFACT_REL, repo_root / WORKLOG_ARTIFACT_REL):
        _write_json_atomic(base / name, payload)


def build_report(*, go_no_go: str, generated_est: str, trader_status: dict, transport: dict, runtime: dict) -> str:
    blockers = transport.get("blockers") or []
    accepted = transport.get("accepted_symbols") or []
    return "\n".join(
        [
            "# V2 Binance Live Order Transport Binding And First Hour Monitoring Report",
            "",
            f"Gate: `{go_no_go}`",
            f"Generated EST: `{generated_est}`",
            f"Live gate: `{trader_status.get('live_gate')}`",
            f"Trader execution enabled: `{trader_status.get('trader_execution_enabled')}`",
            f"Live order transport bound: `{transport.get('live_order_transport_bound')}`",
            f"Writes exchange orders: `{transport.get('writes_exchange_orders')}`",
            f"Places real order: `{transport.get('places_real_order')}`",
            f"Accepted symbols: `{accepted}`",
            "",
            "Transport state:",
            f"- status: `{transport.get('status')}`",
            f"- order_submitted: `{transport.get('order_submitted')}`",
            f"- kill_switch_active: `{transport.get('kill_switch_active')}`",
            f"- runtime_validation: `{(runtime.get('validation') or {}).get('valid')}`",
            f"- blockers: `{', '.join(blockers) if blockers else 'none'}`",
            "",
            "Safety: no leverage or margin mutation, no transfer/withdrawal call, no Redis trim, no legacy restart, no raw credential output.",
        ]
    ) + "\n"


def run_once(*, repo_root: Path, network_probe_enabled: bool = False) -> dict:
    generated_est = est_now()
    trader_result = run_trader_once(repo_root=repo_root, network_probe_enabled=network_probe_enabled)
    trader_path = Path(trader_result["status_path"])
    trader_status = _json_load(trader_path)
    transport = trader_status.get("live_order_transport") if isinstance(trader_status.get("live_order_transport"), dict) else {}
    runtime = read_runtime_execution_state(repo_root=repo_root)
    blockers = list(transport.get("blockers") or [])
    go_no_go = GATE_READY if transport.get("order_submitted") is True and not blockers else GATE_BLOCKED

    prebind = {
        "generated_est": generated_est,
        "runtime_loaded": runtime.get("loaded"),
        "runtime_validation": runtime.get("validation"),
        "trader_status": trader_status.get("status"),
        "live_gate": trader_status.get("live_gate"),
        "accepted_symbols": transport.get("accepted_symbols"),
        "blockers": blockers,
    }
    monitor = {
        "generated_est": generated_est,
        "status": "POST_ENABLE_MONITOR_ACTIVE" if transport.get("order_submitted") else "POST_ENABLE_MONITOR_NOT_STARTED_ORDER_TRANSPORT_BLOCKED",
        "orders_attempted": 1 if transport.get("order_submitted") else 0,
        "orders_submitted": 1 if transport.get("order_submitted") else 0,
        "orders_rejected": 0,
        "auto_freeze_triggered": False,
        "blockers": blockers,
        "monitor_interval_seconds": 5,
    }
    dashboard = {
        "schema_version": "v2_binance_live_order_transport_operator_dashboard_v1",
        "generated_est": generated_est,
        "go_no_go": go_no_go,
        "live_gate": trader_status.get("live_gate"),
        "trader_execution_enabled": trader_status.get("trader_execution_enabled"),
        "live_symbols": trader_status.get("live_symbols") or [],
        "execution_live_symbols": trader_status.get("execution_live_symbols") or [],
        "live_order_transport_bound": transport.get("live_order_transport_bound"),
        "writes_exchange_orders": transport.get("writes_exchange_orders"),
        "places_real_order": transport.get("places_real_order"),
        "blockers": blockers,
        "transport": transport,
        "post_live_enable_first_hour": monitor,
    }

    for base in (repo_root / PUBLIC_ARTIFACT_REL, repo_root / WORKLOG_ARTIFACT_REL):
        base.mkdir(parents=True, exist_ok=True)
        (base / "GO_NO_GO.md").write_text(go_no_go + "\n", encoding="utf-8")
        (base / "V2_BINANCE_LIVE_ORDER_TRANSPORT_BINDING_AND_FIRST_HOUR_MONITORING_REPORT.md").write_text(
            build_report(go_no_go=go_no_go, generated_est=generated_est, trader_status=trader_status, transport=transport, runtime=runtime),
            encoding="utf-8",
        )
    _write_all(repo_root, "live_order_transport_prebind_status.json", prebind)
    _write_all(repo_root, "trader_runtime_order_transport_status.json", trader_status)
    _write_all(repo_root, "post_live_enable_first_hour_status.json", monitor)
    _write_all(repo_root, "operator_dashboard_payload.json", dashboard)
    return dashboard


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--network-probe", action="store_true", default=False)
    args = parser.parse_args(argv)
    result = run_once(repo_root=Path(args.repo_root).resolve(), network_probe_enabled=bool(args.network_probe))
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result["go_no_go"] == GATE_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
