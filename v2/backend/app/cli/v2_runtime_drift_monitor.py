"""Runtime/code drift monitor (F-0008).

Long-running V2 services keep executing the code they imported at start; when
closed-loop workers commit changes, producers and consumers silently diverge
(observed 2026-07-06: atr_percentile added at 22:07, pipeline process from
18:36 published without it while a freshly restarted consumer required it).

This monitor compares each running ai-bot-v2 service's process start time
against the repo's newest commit touching V2 backend sources and reports which
services predate it (restart candidates). Read-only except for one V2 Redis
status key and one status file. Never restarts anything itself.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
STATUS_KEY = "v2:monitor:runtime_drift"
STATUS_PATH = REPO_ROOT / "v2/frontend/public/operator_runtime/v2_runtime_drift/latest/status.json"


def _utc_iso() -> str:
    return datetime.now(tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:
        return ""


def _safe_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed or abs(parsed) == float("inf"):
        return None
    return parsed


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_json(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _nested(payload: dict[str, Any], *path: str) -> Any:
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _timestamp_lag_seconds(value: Any) -> int | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return max(0, int((datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()))


def _redis_client() -> Any | None:
    try:
        import redis

        return redis.Redis(decode_responses=True)
    except Exception:
        return None


def _redis_json(client: Any | None, key: str) -> dict[str, Any]:
    if client is None:
        return {}
    try:
        return _parse_json(client.get(key))
    except Exception:
        return {}


def _redis_scan_count(client: Any | None, pattern: str, *, limit: int = 10000) -> int:
    if client is None:
        return 0
    count = 0
    try:
        cursor = 0
        while True:
            cursor, keys = client.scan(cursor=cursor, match=pattern, count=500)
            count += len(keys)
            if cursor == 0 or count >= limit:
                return count
    except Exception:
        return count


def _read_status_file(relative: str) -> dict[str, Any]:
    path = REPO_ROOT / relative
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def newest_backend_commit_epoch() -> tuple[int, str]:
    out = _run(["git", "-C", str(REPO_ROOT), "log", "-1", "--format=%ct %h", "--", "v2/backend/app"])
    if not out:
        return 0, ""
    parts = out.split()
    try:
        return int(parts[0]), parts[1] if len(parts) > 1 else ""
    except ValueError:
        return 0, ""


def repo_head_commit() -> str:
    return _run(["git", "-C", str(REPO_ROOT), "rev-parse", "--short", "HEAD"])


def commit_before_epoch(epoch: int) -> str:
    if epoch <= 0:
        return ""
    before = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat(timespec="seconds")
    out = _run(["git", "-C", str(REPO_ROOT), "log", "-1", "--format=%h", f"--before={before}", "--", "v2/backend/app"])
    return out.splitlines()[0] if out else ""


def running_v2_services() -> list[dict[str, Any]]:
    listed = _run(["systemctl", "--user", "list-units", "--type=service", "--state=running",
                   "--no-legend", "--plain"])
    rows: list[dict[str, Any]] = []
    for line in listed.splitlines():
        unit = line.split()[0] if line.split() else ""
        if not unit.startswith("ai-bot-v2-"):
            continue
        pid_text = _run(["systemctl", "--user", "show", unit, "-p", "MainPID", "--value"])
        try:
            pid = int(pid_text)
        except ValueError:
            pid = 0
        start_epoch = 0
        if pid > 0:
            try:
                start_epoch = int(Path(f"/proc/{pid}").stat().st_mtime)
            except OSError:
                start_epoch = 0
        rows.append({"unit": unit, "pid": pid, "start_epoch": start_epoch})
    return rows


def build_status() -> dict[str, Any]:
    commit_epoch, commit_hash = newest_backend_commit_epoch()
    head_commit = repo_head_commit()
    services = running_v2_services()
    stale = [
        {
            **row,
            "started_utc": datetime.fromtimestamp(row["start_epoch"], tz=timezone.utc).isoformat(timespec="seconds")
            if row["start_epoch"]
            else None,
            "service_running_commit": commit_before_epoch(row["start_epoch"]),
            "repo_head_commit": head_commit,
            "repo_head_backend_commit": commit_hash,
            "service_restart_required": True,
            "schema_version_mismatch": True,
        }
        for row in services
        if row["start_epoch"] and commit_epoch and row["start_epoch"] < commit_epoch
    ]
    runtime_inputs = collect_runtime_inputs(stale_services=stale, repo_head=head_commit, backend_commit=commit_hash)
    required_alerts = evaluate_required_alerts(runtime_inputs)
    return {
        "schema_version": "v2_runtime_drift_status_v1",
        "generated_utc": _utc_iso(),
        "repo_head_commit": head_commit,
        "repo_head_backend_commit": commit_hash,
        "repo_head_backend_commit_epoch": commit_epoch,
        "services_running": len(services),
        "services_stale": len(stale),
        "stale_services": stale,
        "service_running_commit": stale[0]["service_running_commit"] if stale else head_commit,
        "service_restart_required": bool(stale),
        "schema_version_mismatch": bool(stale),
        "last_restart_utc": max(
            (
                datetime.fromtimestamp(row["start_epoch"], tz=timezone.utc).isoformat(timespec="seconds")
                for row in services
                if row.get("start_epoch")
            ),
            default=None,
        ),
        "alert": len(stale) > 0,
        "alert_name": "RUNTIME_CODE_DRIFT",
        "required_alerts": required_alerts,
        "required_alert_count": len(required_alerts),
        "firing_required_alert_count": sum(1 for alert in required_alerts if alert.get("fires") is True),
        "operator_action": "restart listed services at a safe moment (systemctl --user restart <unit>); never restart legacy or paper_online_runtime",
        "places_real_order": False,
        "old_redis_writes": False,
    }


def collect_runtime_inputs(*, stale_services: list[dict[str, Any]], repo_head: str, backend_commit: str) -> dict[str, Any]:
    client = _redis_client()
    governor = _redis_json(client, "v2:paper:performance_governor_status")
    halt = _redis_json(client, "v2:paper:new_entry_emergency_halt_status")
    ledger = _redis_json(client, "v2:paper:ledger")
    trainer_status = _redis_json(client, "v2:trainer:hybrid_cuda:status")
    trainer_metrics = _redis_json(client, "v2:trainer:hybrid_cuda:metrics")
    market_hb = _redis_json(client, "v2:market:coinapi:ohlcv:heartbeat")
    live_canary = _redis_json(client, "v2:live_canary:status")
    live_transport = _redis_json(client, "v2:live_order_transport:status")
    phase_i = _read_status_file(
        "goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/"
        "PHASE_I_FRONTEND_ROUTE_TRUTH_STATUS.json"
    )
    phase_j = _read_status_file(
        "goal_state/V2_CODEX_A_TO_Z_FABLE_PHASE_VALIDATION_FIX_RESOLUTION_AND_GO_LIVE_READINESS_COMPLETION/"
        "PHASE_J_IOS_RUNTIME_TRUTH_STATUS.json"
    )
    native_trainer_status = _read_status_file(
        "v2/frontend/public/operator_runtime/v2_native_trainer/latest/native_trainer_runtime_status.json"
    )
    microstructure_status = _read_status_file(
        "v2/frontend/public/operator_runtime/v2_microstructure_trust/latest/ios_trust_semantics_truth_status.json"
    )
    prediction_key_count = _redis_scan_count(client, "v2:prediction:*", limit=20000) + _redis_scan_count(
        client, "v2:predictions:*", limit=20000
    )
    paper_online_runtime_active = "active" == _run(
        ["systemctl", "--user", "is-active", "ai-bot-v2-paper-online-runtime.service"]
    ).strip()
    feedback_rows = _safe_int(
        trainer_status.get("feedback_rows")
        or trainer_status.get("trusted_rows_loaded")
        or _nested(trainer_metrics, "trusted_replay_scan", "trusted_rows_loaded")
        or ledger.get("outcome_label_count")
    )
    closed_trades = _safe_int(
        governor.get("closed_outcome_count")
        or ledger.get("closed_trade_count")
        or ledger.get("closed_outcome_count")
    )
    weights_status = str(trainer_status.get("online_learning_status") or "")
    market_generated_at = (
        market_hb.get("finished_utc")
        or market_hb.get("generated_at")
        or market_hb.get("generated_utc")
        or market_hb.get("ts")
    )
    micro_generated_at = microstructure_status.get("generated_at") or microstructure_status.get("generated_utc")
    trainer_generated_at = native_trainer_status.get("generated_at") or native_trainer_status.get("generated_utc")
    live_gate = (
        live_canary.get("live_gate")
        or live_canary.get("live_gate_status")
        or live_transport.get("live_gate")
        or "blocked_human_only"
    )
    exchange_mutation = any(
        value is True
        for value in (
            live_canary.get("order_submitted"),
            live_canary.get("test_order_submitted"),
            live_canary.get("exchange_action_taken"),
            live_canary.get("exchange_leverage_mutated"),
            live_canary.get("exchange_margin_mutated"),
            live_transport.get("order_submitted"),
            live_transport.get("test_order_submitted"),
            live_transport.get("leverage_changed"),
            live_transport.get("margin_mode_changed"),
        )
    )
    return {
        "repo_head_commit": repo_head,
        "repo_head_backend_commit": backend_commit,
        "stale_services": stale_services,
        "profit_factor": _safe_float(governor.get("profit_factor")),
        "expectancy_bps": _safe_float(governor.get("notional_weighted_expectancy_bps")),
        "closed_trades": closed_trades,
        "new_entries_allowed": halt.get("new_entries_allowed"),
        "halt_reasons": halt.get("halt_reasons") if isinstance(halt.get("halt_reasons"), list) else [],
        "trainer_feedback_rows": feedback_rows,
        "trainer_weights_status": weights_status,
        "prediction_key_count": prediction_key_count,
        "prediction_grid_age_seconds": _timestamp_lag_seconds(trainer_generated_at),
        "market_data_age_seconds": _timestamp_lag_seconds(market_generated_at),
        "orderbook_trust_age_seconds": _timestamp_lag_seconds(micro_generated_at),
        "outcome_memory_age_seconds": _timestamp_lag_seconds(ledger.get("generated_utc") or ledger.get("generated_at")),
        "paper_online_runtime_active": paper_online_runtime_active,
        "live_gate": live_gate,
        "exchange_mutation_detected": exchange_mutation,
        "website_truth_pass": phase_i.get("overall_pass") is True,
        "ios_truth_pass": phase_j.get("overall_pass") is True,
    }


def _alert(name: str, fires: bool, severity: str, evidence: dict[str, Any], operator_action: str) -> dict[str, Any]:
    return {
        "name": name,
        "fires": bool(fires),
        "status": "ALERT" if fires else "PASS",
        "severity": severity,
        "evidence": evidence,
        "operator_action": operator_action,
    }


def evaluate_required_alerts(runtime: dict[str, Any]) -> list[dict[str, Any]]:
    closed = _safe_int(runtime.get("closed_trades")) or 0
    pf = _safe_float(runtime.get("profit_factor"))
    expectancy = _safe_float(runtime.get("expectancy_bps"))
    feedback_rows = _safe_int(runtime.get("trainer_feedback_rows")) or 0
    halt_reasons = runtime.get("halt_reasons") if isinstance(runtime.get("halt_reasons"), list) else []
    stale_services = runtime.get("stale_services") if isinstance(runtime.get("stale_services"), list) else []
    return [
        _alert(
            "runtime code commit differs from repo/service commit",
            bool(stale_services),
            "critical",
            {
                "service_running_commit": (stale_services[0].get("service_running_commit") if stale_services else runtime.get("repo_head_commit")),
                "repo_head_commit": runtime.get("repo_head_commit"),
                "repo_head_backend_commit": runtime.get("repo_head_backend_commit"),
                "service_restart_required": bool(stale_services),
                "schema_version_mismatch": bool(stale_services),
                "stale_service_count": len(stale_services),
            },
            "Restart listed V2 services at a safe moment; never restart legacy or paper_online_runtime.",
        ),
        _alert(
            "feature schema changed but service not restarted",
            bool(stale_services),
            "critical",
            {"schema_version_mismatch": bool(stale_services), "stale_service_count": len(stale_services)},
            "Restart affected producers before consumers after schema-affecting code changes.",
        ),
        _alert(
            "PF < 1 after 5 trades",
            closed >= 5 and pf is not None and pf < 1.0,
            "warning",
            {"closed_trades": closed, "profit_factor": pf},
            "Keep new entries halted; inspect bucket quarantine and exit reasons.",
        ),
        _alert(
            "expectancy <= 0 after 5 trades",
            closed >= 5 and expectancy is not None and expectancy <= 0.0,
            "warning",
            {"closed_trades": closed, "expectancy_bps": expectancy},
            "Keep new entries halted until recovered expectancy is proven.",
        ),
        _alert(
            "new entries allowed while halted",
            bool(halt_reasons) and runtime.get("new_entries_allowed") is True,
            "critical",
            {"new_entries_allowed": runtime.get("new_entries_allowed"), "halt_reasons": halt_reasons},
            "Disable new entries immediately and inspect performance governor status.",
        ),
        _alert(
            "trainer feedback rows = 0 while closed trades > 0",
            closed > 0 and feedback_rows == 0,
            "critical",
            {"closed_trades": closed, "trainer_feedback_rows": feedback_rows},
            "Repair trainer feedback/outcome memory before trusting learning status.",
        ),
        _alert(
            "weights not updating",
            str(runtime.get("trainer_weights_status") or "").upper() != "WEIGHTS_UPDATING",
            "warning",
            {"trainer_weights_status": runtime.get("trainer_weights_status")},
            "Check native trainer replay scan, checkpoint writes, and optimizer steps.",
        ),
        _alert(
            "prediction grid stale",
            (runtime.get("prediction_grid_age_seconds") is not None and runtime["prediction_grid_age_seconds"] > 900)
            or (_safe_int(runtime.get("prediction_key_count")) or 0) == 0,
            "warning",
            {"prediction_key_count": runtime.get("prediction_key_count"), "age_seconds": runtime.get("prediction_grid_age_seconds")},
            "Restart/repair prediction publisher or native trainer feed.",
        ),
        _alert(
            "market data stale",
            runtime.get("market_data_age_seconds") is None or runtime["market_data_age_seconds"] > 600,
            "critical",
            {"age_seconds": runtime.get("market_data_age_seconds")},
            "Repair market ingestors before accepting new entries.",
        ),
        _alert(
            "orderbook/trust feed stale",
            runtime.get("orderbook_trust_age_seconds") is None or runtime["orderbook_trust_age_seconds"] > 900,
            "critical",
            {"age_seconds": runtime.get("orderbook_trust_age_seconds")},
            "Repair microstructure trust/orderbook runtime supervisor.",
        ),
        _alert(
            "outcome memory stale after restart",
            runtime.get("outcome_memory_age_seconds") is None or runtime["outcome_memory_age_seconds"] > 900,
            "warning",
            {"age_seconds": runtime.get("outcome_memory_age_seconds")},
            "Rebuild/check paper outcome memory before reading performance gates.",
        ),
        _alert(
            "paper_online_runtime active",
            runtime.get("paper_online_runtime_active") is True,
            "critical",
            {"paper_online_runtime_active": runtime.get("paper_online_runtime_active")},
            "Stop forbidden legacy paper_online_runtime writer; do not restart it.",
        ),
        _alert(
            "live gate changed",
            str(runtime.get("live_gate") or "") != "blocked_human_only",
            "critical",
            {"live_gate": runtime.get("live_gate")},
            "Freeze live path and require operator audit before proceeding.",
        ),
        _alert(
            "exchange mutation detected",
            runtime.get("exchange_mutation_detected") is True,
            "critical",
            {"exchange_mutation_detected": runtime.get("exchange_mutation_detected")},
            "Trigger kill-switch incident response and inspect exchange audit trail.",
        ),
        _alert(
            "website stale-current mismatch",
            runtime.get("website_truth_pass") is not True,
            "warning",
            {"website_truth_pass": runtime.get("website_truth_pass")},
            "Run Phase I route truth check and patch stale-current UI mismatch.",
        ),
        _alert(
            "iOS stale-current mismatch",
            runtime.get("ios_truth_pass") is not True,
            "warning",
            {"ios_truth_pass": runtime.get("ios_truth_pass")},
            "Run Phase J mobile API/source truth validation.",
        ),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_runtime_drift_monitor")
    parser.add_argument("--write-redis", action="store_true")
    parser.add_argument("--write-status", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval-seconds", type=float, default=300.0)
    args = parser.parse_args(argv)
    while True:
        status = build_status()
        print(json.dumps({k: status[k] for k in ("generated_utc", "services_running", "services_stale", "alert")}))
        if args.write_status:
            STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
            STATUS_PATH.write_text(json.dumps(status, indent=1), encoding="utf-8")
        if args.write_redis:
            try:
                import redis

                client = redis.Redis(decode_responses=True)
                client.set(STATUS_KEY, json.dumps(status), ex=900)
            except Exception:
                pass
        if not args.loop:
            return 0
        time.sleep(max(30.0, float(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
