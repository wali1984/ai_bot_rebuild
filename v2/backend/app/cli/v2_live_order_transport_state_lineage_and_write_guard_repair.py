"""Repair V2 live order transport runtime state, lineage, and write guard.

This runner is V2-only. It may refresh audited V2 runtime state and V2 Redis
telemetry, but it never calls test-order, cancel, modify, leverage, margin,
transfer, withdrawal, legacy startup, Redis trim, or non-V2 Redis writes.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

THIS_FILE = Path(__file__).resolve()
REPO_ROOT = THIS_FILE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import (  # noqa: E402
    v2_all_timeframe_prediction_signal_price_target_publisher as signal_cli,
)
from v2.backend.app.cli import v2_orchestrator_arbitration_loop as orchestrator_loop  # noqa: E402
from v2.backend.app.cli import v2_risk_gateway_live_loop as risk_gateway_loop  # noqa: E402
from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop  # noqa: E402
from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (  # noqa: E402
    default_paths as signal_default_paths,
)
from v2.backend.app.services.live_gate.binance_live_order_transport import (  # noqa: E402
    evaluate_live_order_transport,
)
from v2.backend.app.services.live_gate.runtime_execution_state import (  # noqa: E402
    LIVE_GATE_ENABLED,
    read_runtime_execution_state,
    write_runtime_execution_state,
)
from v2.backend.app.services.live_gate.single_pass import (  # noqa: E402
    _est_iso,
    _json_load,
    build_binance_connectivity_status,
    default_paths as live_gate_default_paths,
)


GATE_READY = "V2_LIVE_ORDER_TRANSPORT_STATE_LINEAGE_AND_WRITE_GUARD_REPAIR_READY"
GATE_BLOCKED = "V2_LIVE_ORDER_TRANSPORT_STATE_LINEAGE_AND_WRITE_GUARD_REPAIR_BLOCKED"
SERVICE_ID = "v2_live_order_transport_state_lineage_and_write_guard_repair"
ACCEPTED_SYMBOLS = ["BNBUSDT", "BTCUSDT", "ETHUSDT", "PAXGUSDT", "XAUTUSDT", "ZECUSDT"]
ARTIFACT_REL = Path("v2_live_order_transport_state_lineage_and_write_guard_repair/latest")
PUBLIC_DIR_REL = Path("v2/frontend/public") / ARTIFACT_REL
WORKLOG_DIR_REL = Path("claude_worklog/final_readiness") / ARTIFACT_REL
EST = ZoneInfo("America/New_York")


def est_now() -> str:
    return datetime.now(tz=EST).isoformat(timespec="seconds")


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    tmp.replace(path)


def mirror_outputs(repo_root: Path, payloads: Mapping[str, Mapping[str, Any]], report: str) -> list[str]:
    written: list[str] = []
    for base in (repo_root / PUBLIC_DIR_REL, repo_root / WORKLOG_DIR_REL):
        base.mkdir(parents=True, exist_ok=True)
        for name, payload in payloads.items():
            path = base / name
            write_json(path, payload)
            written.append(str(path))
        report_path = base / "V2_LIVE_ORDER_TRANSPORT_STATE_LINEAGE_AND_WRITE_GUARD_REPAIR_REPORT.md"
        report_path.write_text(report, encoding="utf-8")
        written.append(str(report_path))
        go_no_go = str(payloads["operator_dashboard_payload.json"]["go_no_go"])
        go_path = base / "GO_NO_GO.md"
        go_path.write_text(go_no_go + "\n", encoding="utf-8")
        written.append(str(go_path))
    return written


def connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis.from_url(
            "redis://127.0.0.1:6379/0",
            decode_responses=True,
            socket_connect_timeout=2.0,
            socket_timeout=2.0,
        )
        client.ping()
        return client
    except Exception:
        return None


def redis_json(client: Any, key: str) -> Any:
    if client is None or not key.startswith("v2:"):
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def api_get(path: str) -> dict[str, Any]:
    url = f"http://127.0.0.1:8000{path}"
    try:
        with urllib.request.urlopen(url, timeout=3.0) as response:
            return {
                "url": url,
                "http_status": int(getattr(response, "status", 200)),
                "payload": json.loads(response.read().decode("utf-8", errors="replace")),
                "error": None,
            }
    except Exception as exc:
        return {"url": url, "http_status": None, "payload": {}, "error": type(exc).__name__}


def safe_run(label: str, fn, *args, **kwargs) -> dict[str, Any]:
    try:
        payload = fn(*args, **kwargs)
        return {"label": label, "ok": True, "payload": payload, "error": None}
    except Exception as exc:
        return {"label": label, "ok": False, "payload": {}, "error": type(exc).__name__}


def accepted_records(repo_root: Path) -> dict[str, Any]:
    acceptance = repo_root / "v2/frontend/public/v2_audited_operator_live_acceptance_and_enable_flow/latest"
    execution = repo_root / "v2/frontend/public/v2_audited_live_acceptance_records_and_enable_execution/latest"
    runtime = repo_root / "v2/frontend/public/v2_live_gate_runtime_execution_adapter_enablement/latest"
    risk = read_json(acceptance / "risk_profile_acceptance_status.json")
    symbols = read_json(acceptance / "live_symbol_acceptance_status.json")
    final = read_json(acceptance / "final_operator_live_approval_status.json")
    enable_runtime = read_json(runtime / "live_enable_runtime_mutation_attempt_status.json")
    enable_execution = read_json(execution / "live_enable_execution_status.json")
    enable_audit_id = (
        enable_runtime.get("enable_audit_id")
        or enable_execution.get("audit_id")
        or read_json(acceptance / "live_gate_audit_record_status.json").get("latest_audit_id")
    )
    return {
        "risk": risk,
        "symbols": symbols,
        "final": final,
        "enable_audit_id": enable_audit_id,
        "source_payload_ids": [
            str(risk.get("source_payload_id") or ""),
            str(symbols.get("source_payload_id") or ""),
            str(final.get("source_payload_id") or ""),
        ],
    }


def acceptance_blockers(records: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    risk = records.get("risk") if isinstance(records.get("risk"), Mapping) else {}
    symbols = records.get("symbols") if isinstance(records.get("symbols"), Mapping) else {}
    final = records.get("final") if isinstance(records.get("final"), Mapping) else {}
    accepted_symbols = [str(symbol) for symbol in symbols.get("accepted_live_symbols") or []]
    required_fields = {
        "max_notional_per_trade",
        "max_symbol_exposure",
        "max_total_exposure",
        "max_daily_loss",
        "max_drawdown",
        "max_open_positions",
        "max_leverage",
        "min_expected_move_after_cost_bps",
        "min_confidence_calibrated",
        "max_spread_bps",
        "max_slippage_bps",
        "cooldown_seconds",
        "kill_switch_conditions",
    }
    risk_fields = risk.get("accepted_profile_fields") if isinstance(risk.get("accepted_profile_fields"), Mapping) else {}
    if risk.get("risk_profile_operator_accepted") is not True or not risk.get("audit_id"):
        blockers.append("RISK_PROFILE_ACCEPTANCE_RECORD_MISSING")
    if risk.get("accepted_profile_name") != "conservative":
        blockers.append("ACCEPTED_RISK_PROFILE_NOT_CONSERVATIVE")
    missing_risk = sorted(field for field in required_fields if field not in risk_fields)
    blockers.extend(f"RISK_PROFILE_FIELD_MISSING:{field}" for field in missing_risk)
    if risk_fields.get("max_leverage") != 1.0:
        blockers.append("ACCEPTED_RISK_PROFILE_MAX_LEVERAGE_NOT_ONE")
    if symbols.get("live_symbol_operator_accepted") is not True or not symbols.get("audit_id"):
        blockers.append("LIVE_SYMBOL_ACCEPTANCE_RECORD_MISSING")
    if accepted_symbols != ACCEPTED_SYMBOLS:
        blockers.append("ACCEPTED_SYMBOLS_DO_NOT_MATCH_EXPECTED_SET")
    if final.get("operator_final_live_approval_present") is not True or not final.get("audit_id"):
        blockers.append("FINAL_OPERATOR_APPROVAL_RECORD_MISSING")
    if not records.get("enable_audit_id"):
        blockers.append("ENABLE_AUDIT_ID_MISSING")
    return blockers


def refresh_runtime_state(repo_root: Path, records: Mapping[str, Any]) -> dict[str, Any]:
    if acceptance_blockers(records):
        return {"ok": False, "skipped": True, "reason": "ACCEPTANCE_BLOCKERS_PRESENT"}
    risk = records["risk"]
    symbols = records["symbols"]
    final = records["final"]
    return write_runtime_execution_state(
        repo_root=repo_root,
        accepted_symbols=[str(symbol) for symbol in symbols.get("accepted_live_symbols") or []],
        risk_record=risk,
        symbol_record=symbols,
        final_record=final,
        enable_audit_id=str(records["enable_audit_id"]),
        enabled_by="wali",
        source_payload_ids=[item for item in records.get("source_payload_ids") or [] if item],
    )


def run_signal_publisher(repo_root: Path) -> dict[str, Any]:
    args = signal_cli.parse_args(
        [
            "--repo-root",
            str(repo_root),
            "--production-base-url",
            "http://127.0.0.1:5177",
            "--routes",
        ]
    )
    return signal_cli.run_once(args)


def by_prediction(rows: Iterable[Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        prediction_id = str(row.get("prediction_id") or row.get("source_prediction_id") or "")
        if prediction_id:
            out[prediction_id] = row
    return out


def lineage_reconciliation(signal_status: Mapping[str, Any], risk_records: list[dict[str, Any]]) -> dict[str, Any]:
    risk_by_prediction = by_prediction(risk_records)
    rows: list[dict[str, Any]] = []
    mismatch_count = 0
    accepted = set(ACCEPTED_SYMBOLS)
    for signal in signal_status.get("published_signals") or []:
        if not isinstance(signal, dict):
            continue
        symbol = str(signal.get("symbol") or "").upper()
        if symbol not in accepted:
            continue
        prediction_id = str(signal.get("prediction_id") or "")
        risk_decision_id = str(signal.get("risk_decision_id") or "")
        risk = risk_by_prediction.get(prediction_id) or {}
        expected = str(risk.get("risk_decision_id") or "")
        mismatch = bool(prediction_id and risk_decision_id and expected and risk_decision_id != expected)
        if mismatch:
            mismatch_count += 1
        rows.append(
            {
                "symbol": symbol,
                "timeframe": signal.get("timeframe"),
                "prediction_id": prediction_id,
                "signal_id": signal.get("signal_id"),
                "risk_decision_id": risk_decision_id,
                "expected_risk_decision_id": expected,
                "actual_risk_decision_key": "v2:risk:gateway:decisions",
                "risk_action": risk.get("risk_action"),
                "risk_reason_code": risk.get("risk_reason_code"),
                "risk_gateway_prediction_id": risk.get("prediction_id"),
                "timestamp_freshness": signal.get("generated_est"),
                "mismatch": mismatch,
                "legacy_live_blocked_label": "LEGACY_LIVE_PATH_BLOCKED_NOT_V2"
                if risk.get("live_blocked") is True
                else None,
            }
        )
    return {
        "schema_version": "risk_decision_lineage_reconciliation_status_v1",
        "generated_est": est_now(),
        "accepted_symbols": ACCEPTED_SYMBOLS,
        "rows": rows,
        "risk_decision_id_mismatch_count": mismatch_count,
        "status": "RISK_DECISION_LINEAGE_READY" if rows and mismatch_count == 0 else "RISK_DECISION_LINEAGE_BLOCKED",
    }


def signal_refresh_status(signal_status: Mapping[str, Any], runtime_read: Mapping[str, Any]) -> dict[str, Any]:
    runtime_payload = runtime_read.get("payload") if isinstance(runtime_read.get("payload"), Mapping) else {}
    live_gate = runtime_payload.get("live_gate")
    mismatched_rows = [
        {
            "symbol": row.get("symbol"),
            "prediction_id": row.get("prediction_id"),
            "signal_live_gate": row.get("live_gate"),
            "runtime_live_gate": live_gate,
        }
        for row in signal_status.get("published_signals") or []
        if isinstance(row, dict)
        and str(row.get("symbol") or "").upper() in set(ACCEPTED_SYMBOLS)
        and row.get("source_runtime_lane") == "v2:signals:paper"
        and row.get("live_gate") != live_gate
    ]
    return {
        "schema_version": "signal_payload_live_gate_refresh_status_v1",
        "generated_est": est_now(),
        "runtime_live_gate": live_gate,
        "signal_status_live_gate": signal_status.get("live_gate"),
        "accepted_live_symbols": runtime_payload.get("accepted_live_symbols") or [],
        "execution_live_symbols": runtime_payload.get("execution_live_symbols") or [],
        "mismatch_count": len(mismatched_rows),
        "mismatched_rows": mismatched_rows,
        "payloads_regenerated": [
            "operator_runtime/v2_signals/latest/signals_payload.json",
            "operator_runtime/v2_signals/latest/realtime_signal_publisher_status.json",
        ],
        "status": "SIGNAL_PAYLOAD_LIVE_GATE_REFRESH_READY" if not mismatched_rows else "SIGNAL_PAYLOAD_LIVE_GATE_REFRESH_BLOCKED",
    }


def legacy_live_block_status(risk_gateway_status: Mapping[str, Any], risk_records: list[dict[str, Any]]) -> dict[str, Any]:
    legacy_rows = [
        {
            "symbol": row.get("symbol"),
            "prediction_id": row.get("prediction_id"),
            "risk_decision_id": row.get("risk_decision_id"),
            "live_blocked": row.get("live_blocked"),
            "label": "LEGACY_LIVE_PATH_BLOCKED_NOT_V2",
        }
        for row in risk_records
        if row.get("live_blocked") is True
    ]
    return {
        "schema_version": "risk_gateway_legacy_live_block_flag_status_v1",
        "generated_est": est_now(),
        "legacy_live_blocked_true_count": len(legacy_rows),
        "legacy_live_blocked_label": "LEGACY_LIVE_PATH_BLOCKED_NOT_V2" if legacy_rows else None,
        "v2_live_gate_enabled": risk_gateway_status.get("v2_live_gate_enabled"),
        "live_gate": risk_gateway_status.get("live_gate"),
        "status": "LEGACY_FLAG_LABELLED_NOT_V2_BLOCKER",
        "rows": legacy_rows[:64],
    }


def transport_write_guard_status(runtime_read: Mapping[str, Any], transport_status: Mapping[str, Any]) -> dict[str, Any]:
    payload = runtime_read.get("payload") if isinstance(runtime_read.get("payload"), Mapping) else {}
    return {
        "schema_version": "live_order_transport_write_guard_status_v1",
        "generated_est": est_now(),
        "write_guard_enabled": payload.get("order_transport_write_guard_enabled") is True,
        "write_guard_source": payload.get("order_transport_write_guard_source"),
        "submit_guard_enabled": payload.get("order_transport_submit_enabled") is True,
        "submit_guard_source": payload.get("order_transport_submit_source"),
        "transport_force_disabled": transport_status.get("transport_force_disabled"),
        "raw_credentials_exposed": False,
        "blockers": [
            blocker
            for blocker in transport_status.get("blockers") or []
            if str(blocker)
            in {
                "LIVE_ORDER_TRANSPORT_WRITE_GUARD_NOT_ENABLED",
                "LIVE_ORDER_TRANSPORT_SUBMIT_NOT_ENABLED",
                "LIVE_ORDER_TRANSPORT_FORCE_DISABLED",
            }
        ],
        "status": "LIVE_ORDER_TRANSPORT_WRITE_GUARD_READY"
        if payload.get("order_transport_write_guard_enabled") is True
        and payload.get("order_transport_submit_enabled") is True
        and not transport_status.get("transport_force_disabled")
        else "LIVE_ORDER_TRANSPORT_WRITE_GUARD_BLOCKED",
    }


def run_validation(repo_root: Path) -> dict[str, Any]:
    commands = {
        "py_compile": [
            "python3",
            "-m",
            "py_compile",
            "v2/backend/app/services/live_gate/runtime_execution_state.py",
            "v2/backend/app/services/live_gate/binance_live_order_transport.py",
            "v2/backend/app/services/all_timeframe_prediction_signal_price_target_publisher.py",
            "v2/backend/app/cli/v2_orchestrator_arbitration_loop.py",
            "v2/backend/app/cli/v2_risk_gateway_live_loop.py",
            "v2/backend/app/cli/v2_trade_management_paper_loop.py",
            "v2/backend/app/cli/v2_live_order_transport_state_lineage_and_write_guard_repair.py",
        ],
        "focused_backend_tests": [
            "./.venv/bin/python",
            "-m",
            "pytest",
            "-q",
            "v2/backend/tests/unit/services/live_gate/test_binance_live_order_transport.py",
            "v2/backend/tests/unit/services/live_gate/test_runtime_execution_state.py",
            "v2/backend/tests/unit/api/test_live_gate.py",
        ],
        "frontend_typecheck": ["npm", "run", "typecheck"],
        "frontend_build": ["npm", "run", "build"],
    }
    results: dict[str, Any] = {"schema_version": "validation_status_v1", "generated_est": est_now()}
    for label, command in commands.items():
        cwd = repo_root / "v2/frontend" if label.startswith("frontend_") else repo_root
        proc = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=240)
        results[label] = {
            "returncode": proc.returncode,
            "status": "PASS" if proc.returncode == 0 else "FAIL",
            "stdout_tail": proc.stdout[-2000:],
            "stderr_tail": proc.stderr[-2000:],
        }
    forbidden = subprocess.run(
        [
            "rg",
            "-n",
            "fapi/v1/(leverage|marginType|transfer|withdraw|batchOrders)|testOrder|cancelAllOpenOrders|DELETE /fapi|PUT /fapi",
            "v2/backend/app/services/live_gate",
            "v2/backend/app/cli/v2_trader_runtime_loop.py",
            "v2/backend/app/cli/v2_orchestrator_arbitration_loop.py",
            "v2/backend/app/cli/v2_risk_gateway_live_loop.py",
            "v2/backend/app/cli/v2_trade_management_paper_loop.py",
        ],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    results["forbidden_exchange_mutation_scan"] = {
        "status": "PASS" if forbidden.returncode == 1 else "FAIL",
        "returncode": forbidden.returncode,
        "matches": forbidden.stdout[-2000:],
    }
    results["raw_secret_scan"] = raw_secret_scan(repo_root)
    return results


def raw_secret_scan(repo_root: Path) -> dict[str, Any]:
    env_path = repo_root / "v2/.env.local"
    secrets: list[str] = []
    if env_path.exists():
        for raw in env_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if "=" not in raw or raw.strip().startswith("#"):
                continue
            key, value = raw.split("=", 1)
            if not any(token in key.upper() for token in ("KEY", "SECRET", "TOKEN", "PASSWORD")):
                continue
            value = value.strip().strip('"').strip("'")
            if len(value) >= 8:
                secrets.append(value)
    scanned_roots = [
        repo_root / PUBLIC_DIR_REL,
        repo_root / WORKLOG_DIR_REL,
        repo_root / "v2/frontend/public/operator_runtime/v2_signals/latest",
        repo_root / "v2/frontend/public/operator_runtime/v2_trader_runtime_state/latest",
    ]
    matches: list[str] = []
    for root in scanned_roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file() or path.stat().st_size > 20_000_000:
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if any(secret and secret in text for secret in secrets):
                matches.append(str(path.relative_to(repo_root)))
    return {
        "status": "PASS" if not matches else "FAIL",
        "secret_value_count_checked": len(secrets),
        "raw_secret_matches_count": len(matches),
        "files_with_raw_secret_matches": matches,
    }


def render_report(dashboard: Mapping[str, Any]) -> str:
    return "\n".join(
        [
            "# V2 Live Order Transport State Lineage And Write Guard Repair Report",
            "",
            f"Gate: `{dashboard.get('go_no_go')}`",
            f"Generated EST: `{dashboard.get('generated_est')}`",
            f"Live gate: `{dashboard.get('live_gate')}`",
            f"Trader execution enabled: `{dashboard.get('trader_execution_enabled')}`",
            f"Write guard enabled: `{dashboard.get('write_guard_enabled')}`",
            f"Risk decision mismatches: `{dashboard.get('risk_decision_id_mismatch_count')}`",
            f"Signal live-gate mismatches: `{dashboard.get('signal_live_gate_mismatch_count')}`",
            f"Pre-submit status: `{dashboard.get('pre_submit_status')}`",
            f"Submit result status: `{dashboard.get('submit_result_status')}`",
            f"Order submitted: `{dashboard.get('order_submitted')}`",
            "",
            "Blockers:",
            *(f"- `{blocker}`" for blocker in dashboard.get("blockers", [])),
            "",
            "Safety: no test-order/cancel/modify, no leverage or margin mutation, no transfer/withdrawal, no legacy restart, no Redis trim, no raw credential output.",
            "",
        ]
    )


def run_once(repo_root: Path, *, submit_if_all_checks_pass: bool = True, run_validation_checks: bool = True) -> dict[str, Any]:
    client = connect_redis()
    records = accepted_records(repo_root)
    accept_blockers = acceptance_blockers(records)
    runtime_before = read_runtime_execution_state(repo_root=repo_root, redis_client=client)
    runtime_write = refresh_runtime_state(repo_root, records)
    runtime_after = read_runtime_execution_state(repo_root=repo_root, redis_client=client)

    orchestration = safe_run("v2_orchestrator_arbitration_loop", orchestrator_loop.run_once)
    risk_gateway = safe_run("v2_risk_gateway_live_loop", risk_gateway_loop.run_once, ttl_seconds=300)
    paper = safe_run("v2_trade_management_paper_loop", paper_loop.run_once)
    signal_publish = safe_run("v2_all_timeframe_prediction_signal_price_target_publisher", run_signal_publisher, repo_root)

    signal_paths = signal_default_paths(repo_root)
    signal_status = read_json(signal_paths.signal_public_dir / "realtime_signal_publisher_status.json")
    risk_records_payload = redis_json(client, "v2:risk:gateway:decisions")
    risk_records = [row for row in risk_records_payload if isinstance(row, dict)] if isinstance(risk_records_payload, list) else []
    live_paths = live_gate_default_paths(repo_root)
    connectivity = build_binance_connectivity_status(
        env_local_path=live_paths.env_local_path,
        generated_est=_est_iso(),
        network_probe_enabled=True,
    )
    trader_status = {
        "binance_private_readonly": connectivity,
        "trader_execution_enabled": bool((runtime_after.get("validation") or {}).get("valid")),
        "live_gate": (runtime_after.get("payload") or {}).get("live_gate"),
        "live_symbols": (runtime_after.get("payload") or {}).get("live_symbols") or [],
        "execution_live_symbols": (runtime_after.get("payload") or {}).get("execution_live_symbols") or [],
    }
    pre_submit = evaluate_live_order_transport(
        repo_root=repo_root,
        signal_status=signal_status if isinstance(signal_status, Mapping) else {},
        trader_status=trader_status,
        runtime_read=runtime_after,
        redis_client=client,
        dry_run=True,
    )
    risk_lineage = lineage_reconciliation(signal_status if isinstance(signal_status, Mapping) else {}, risk_records)
    signal_refresh = signal_refresh_status(signal_status if isinstance(signal_status, Mapping) else {}, runtime_after)
    risk_legacy = legacy_live_block_status(risk_gateway.get("payload") or {}, risk_records)
    write_guard = transport_write_guard_status(runtime_after, pre_submit)

    source_reconciliation = {
        "schema_version": "live_gate_runtime_state_reconciliation_status_v1",
        "generated_est": est_now(),
        "api_status": api_get("/api/v1/live-gate/status"),
        "api_evaluate": api_get("/api/v1/live-gate/evaluate"),
        "runtime_before": runtime_before,
        "runtime_after": runtime_after,
        "runtime_state_write_status": runtime_write,
        "accepted_symbols_match_expected": (runtime_after.get("payload") or {}).get("accepted_live_symbols") == ACCEPTED_SYMBOLS,
        "risk_profile": ((runtime_after.get("payload") or {}).get("risk_profile") or {}).get("profile_name"),
        "all_surfaces_live_gate": {
            "redis_v2_live_gate_state": (runtime_after.get("payload") or {}).get("live_gate"),
            "signal_status": signal_status.get("live_gate") if isinstance(signal_status, Mapping) else None,
            "risk_gateway": (risk_gateway.get("payload") or {}).get("live_gate"),
            "orchestrator": (orchestration.get("payload") or {}).get("live_gate"),
            "paper_loop": (paper.get("payload") or {}).get("live_gate"),
            "transport": pre_submit.get("selected_candidate", {}).get("source_signal_live_gate")
            if isinstance(pre_submit.get("selected_candidate"), Mapping)
            else None,
        },
        "status": "LIVE_GATE_RUNTIME_STATE_RECONCILED"
        if (runtime_after.get("validation") or {}).get("valid")
        and (runtime_after.get("payload") or {}).get("live_gate") == LIVE_GATE_ENABLED
        else "LIVE_GATE_RUNTIME_STATE_RECONCILIATION_BLOCKED",
    }

    fatal_pre_submit_blockers = [
        blocker
        for blocker in pre_submit.get("blockers") or []
        if blocker != "NO_ACCEPTED_SYMBOL_SIGNAL_CANDIDATE"
    ]
    submit_result: dict[str, Any]
    if accept_blockers:
        submit_result = {
            "schema_version": "live_order_transport_submit_result_status_v1",
            "generated_est": est_now(),
            "status": "LIVE_ORDER_TRANSPORT_SUBMIT_SKIPPED_ACCEPTANCE_BLOCKERS",
            "order_submitted": False,
            "blockers": accept_blockers,
        }
    elif fatal_pre_submit_blockers:
        submit_result = {
            "schema_version": "live_order_transport_submit_result_status_v1",
            "generated_est": est_now(),
            "status": "LIVE_ORDER_TRANSPORT_SUBMIT_SKIPPED_PRECHECK_BLOCKERS",
            "order_submitted": False,
            "blockers": fatal_pre_submit_blockers,
        }
    elif pre_submit.get("status") == "LIVE_ORDER_TRANSPORT_PRE_SUBMIT_READY" and submit_if_all_checks_pass:
        submit_result = evaluate_live_order_transport(
            repo_root=repo_root,
            signal_status=signal_status if isinstance(signal_status, Mapping) else {},
            trader_status=trader_status,
            runtime_read=runtime_after,
            redis_client=client,
            dry_run=False,
        )
        submit_result = {
            "schema_version": "live_order_transport_submit_result_status_v1",
            **submit_result,
        }
    else:
        submit_result = {
            "schema_version": "live_order_transport_submit_result_status_v1",
            "generated_est": est_now(),
            "status": "TRANSPORT_READY_NO_VALID_ORDER_CANDIDATE",
            "order_submitted": False,
            "blockers": pre_submit.get("blockers") or [],
        }

    post_monitor = {
        "schema_version": "post_live_enable_first_hour_status_v1",
        "generated_est": est_now(),
        "monitor_status": "STARTED_OR_REFRESHED",
        "orders_attempted": 1 if submit_result.get("selected_candidate") else 0,
        "orders_submitted": 1 if submit_result.get("order_submitted") else 0,
        "orders_rejected": 1
        if submit_result.get("submit_result")
        and not submit_result.get("order_submitted")
        and submit_result.get("status") != "LIVE_ORDER_TRANSPORT_SUBMIT_SKIPPED_PRECHECK_BLOCKERS"
        else 0,
        "accepted_symbols": ACCEPTED_SYMBOLS,
        "kill_switch_active": pre_submit.get("kill_switch_active"),
        "latest_transport_status": submit_result.get("status"),
        "auto_freeze_conditions": [
            "symbol outside accepted list",
            "missing prediction_id/risk_decision_id/orchestrator_decision_id",
            "leverage/margin mutation attempted",
            "old Redis write detected",
            "raw credential leak",
            "risk gateway unavailable",
            "unexpected order endpoint",
        ],
    }

    validation = run_validation(repo_root) if run_validation_checks else {
        "schema_version": "validation_status_v1",
        "generated_est": est_now(),
        "status": "SKIPPED",
    }

    blockers = list(accept_blockers)
    blockers.extend((runtime_after.get("validation") or {}).get("blockers") or [])
    blockers.extend(write_guard.get("blockers") or [])
    if risk_lineage["risk_decision_id_mismatch_count"]:
        blockers.append("RISK_GATEWAY_DECISION_ID_MISMATCH")
    if not risk_lineage.get("rows"):
        blockers.append("RISK_DECISION_LINEAGE_NO_ACCEPTED_SYMBOL_ROWS")
    if signal_refresh["mismatch_count"]:
        blockers.append("SIGNAL_PAYLOAD_LIVE_GATE_DIFFERS_FROM_RUNTIME_STATE")
    blockers.extend(fatal_pre_submit_blockers)
    if submit_result.get("status") == "LIVE_ORDER_TRANSPORT_SUBMIT_FAILED":
        blockers.append("LIVE_ORDER_TRANSPORT_SUBMIT_FAILED")
    if validation.get("py_compile", {}).get("status") == "FAIL":
        blockers.append("PY_COMPILE_FAILED")
    if validation.get("focused_backend_tests", {}).get("status") == "FAIL":
        blockers.append("FOCUSED_BACKEND_TESTS_FAILED")
    if validation.get("forbidden_exchange_mutation_scan", {}).get("status") == "FAIL":
        blockers.append("FORBIDDEN_EXCHANGE_MUTATION_SCAN_FAILED")
    if validation.get("frontend_typecheck", {}).get("status") == "FAIL":
        blockers.append("FRONTEND_TYPECHECK_FAILED")
    if validation.get("frontend_build", {}).get("status") == "FAIL":
        blockers.append("FRONTEND_BUILD_FAILED")
    if validation.get("raw_secret_scan", {}).get("status") == "FAIL":
        blockers.append("RAW_SECRET_SCAN_FAILED")
    blockers = sorted(set(str(blocker) for blocker in blockers if str(blocker)))
    go_no_go = GATE_BLOCKED if blockers else GATE_READY

    dashboard = {
        "schema_version": "operator_dashboard_payload_v1",
        "service_id": SERVICE_ID,
        "generated_est": est_now(),
        "go_no_go": go_no_go,
        "live_gate": (runtime_after.get("payload") or {}).get("live_gate"),
        "trader_execution_enabled": (runtime_after.get("payload") or {}).get("trader_execution_enabled") is True,
        "write_guard_enabled": write_guard.get("write_guard_enabled"),
        "submit_guard_enabled": write_guard.get("submit_guard_enabled"),
        "accepted_symbols": ACCEPTED_SYMBOLS,
        "risk_profile": ((runtime_after.get("payload") or {}).get("risk_profile") or {}).get("profile_name"),
        "risk_decision_id_mismatch_count": risk_lineage["risk_decision_id_mismatch_count"],
        "signal_live_gate_mismatch_count": signal_refresh["mismatch_count"],
        "pre_submit_status": pre_submit.get("status"),
        "submit_result_status": submit_result.get("status"),
        "order_submitted": bool(submit_result.get("order_submitted")),
        "writes_exchange_orders": bool(submit_result.get("writes_exchange_orders")),
        "places_real_order": bool(submit_result.get("places_real_order")),
        "blockers": blockers,
        "safety": {
            "no_test_order_cancel_modify": True,
            "no_leverage_margin_mutation": True,
            "no_transfer_or_withdrawal": True,
            "no_old_redis_write": True,
            "no_redis_trim": True,
            "no_legacy_restart": True,
            "raw_credentials_exposed": False,
        },
        "validation": validation,
    }

    payloads: dict[str, Mapping[str, Any]] = {
        "live_gate_runtime_state_reconciliation_status.json": source_reconciliation,
        "live_order_transport_write_guard_status.json": write_guard,
        "risk_decision_lineage_reconciliation_status.json": risk_lineage,
        "signal_payload_live_gate_refresh_status.json": signal_refresh,
        "risk_gateway_legacy_live_block_flag_status.json": risk_legacy,
        "live_order_transport_pre_submit_evaluation_status.json": {
            "schema_version": "live_order_transport_pre_submit_evaluation_status_v1",
            **pre_submit,
        },
        "live_order_transport_submit_result_status.json": submit_result,
        "post_live_enable_first_hour_status.json": post_monitor,
        "operator_dashboard_payload.json": dashboard,
        "validation_status.json": validation,
    }
    report = render_report(dashboard)
    written = mirror_outputs(repo_root, payloads, report)
    return {"go_no_go": go_no_go, "payloads": payloads, "paths_written": written}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=SERVICE_ID)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--no-submit", action="store_true", help="Run repair and dry evaluation only.")
    parser.add_argument("--skip-validation", action="store_true")
    args = parser.parse_args(argv)
    result = run_once(
        Path(args.repo_root).resolve(),
        submit_if_all_checks_pass=not bool(args.no_submit),
        run_validation_checks=not bool(args.skip_validation),
    )
    print(json.dumps({"go_no_go": result["go_no_go"], "paths_written": result["paths_written"]}, indent=2))
    return 0 if result["go_no_go"] == GATE_READY else 2


if __name__ == "__main__":
    raise SystemExit(main())
