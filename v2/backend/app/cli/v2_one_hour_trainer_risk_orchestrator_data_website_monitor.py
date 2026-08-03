"""One-hour V2 trainer/risk/orchestrator/data/website monitor.

Read-only monitor except for V2-owned filesystem artifacts. It never places
orders, calls test-order, changes leverage/margin, writes Redis, restarts
services, or touches legacy Redis namespaces.
"""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

try:
    from v2.backend.app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol
except ImportError:  # Uvicorn/backend PYTHONPATH style.
    from app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol


REPO = Path("/home/wali/Desktop/AI BOT REBUILD")
PUBLIC_DIR = (
    REPO
    / "v2/frontend/public/v2_one_hour_trainer_risk_orchestrator_data_website_monitor/latest"
)
WORKLOG_DIR = (
    REPO
    / "claude_worklog/final_readiness/v2_one_hour_trainer_risk_orchestrator_data_website_monitor/latest"
)
EST = ZoneInfo("America/New_York")

SERVICE_NAMES = (
    "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.service",
    "ai-bot-v2-native-rl-masa-ppo-cuda-trainer-loop.timer",
    "ai-bot-v2-trainer-training-live-loop.service",
    "ai-bot-v2-orchestrator-arbitration-loop.service",
    "ai-bot-v2-risk-gateway-live-loop.service",
    "ai-bot-v2-trade-management-paper-loop.service",
    "ai-bot-v2-portfolio-state-publisher.service",
    "ai-bot-v2-feature-pipeline-native-loop.service",
    "ai-bot-v2-binance-kline-wss-loop.service",
    "ai-bot-v2-coinapi-wsds-loop.service",
    "ai-bot-v2-coinank-live-direct.service",
    "ai-bot-v2-coinank-global-aggregator-direct.service",
    "ai-bot-v2-liquidation-levels-engine.service",
    "ai-bot-v2-public-website-backend.service",
)


def _est_now() -> str:
    return datetime.now(EST).isoformat(timespec="seconds")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _connect_redis() -> Any:
    try:
        import redis  # type: ignore

        client = redis.Redis(
            host="127.0.0.1",
            port=6379,
            db=0,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=3,
        )
        client.ping()
        return client
    except Exception:
        return None


def _json(raw: Any, default: Any = None) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:
        return default


def _redis_json(r: Any, key: str, default: Any = None) -> Any:
    if r is None:
        return default
    try:
        return _json(r.get(key), default)
    except Exception:
        return default


def _scan_json(r: Any, pattern: str, limit: int = 5000) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if r is None:
        return rows
    try:
        for key in r.scan_iter(match=pattern, count=500):
            payload = _json(r.get(str(key)))
            if isinstance(payload, dict):
                row = dict(payload)
                row["_redis_key"] = str(key)
                rows.append(row)
            elif isinstance(payload, list):
                for item in payload:
                    if isinstance(item, dict):
                        row = dict(item)
                        row["_redis_key"] = str(key)
                        rows.append(row)
            if len(rows) >= limit:
                break
    except Exception:
        return rows
    return rows


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v if v == v and v not in (float("inf"), float("-inf")) else None
    if isinstance(value, str):
        try:
            v = float(value)
        except ValueError:
            return None
        return v if v == v else None
    return None


def _parse_time(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _age_seconds(value: Any) -> float | None:
    dt = _parse_time(value)
    if dt is None:
        return None
    return max(0.0, datetime.now(timezone.utc).timestamp() - dt.timestamp())


def _service_status() -> dict[str, Any]:
    cmd = [
        "systemctl",
        "--user",
        "show",
        "-p",
        "ActiveState",
        "-p",
        "SubState",
        "-p",
        "Result",
        "-p",
        "NRestarts",
        *SERVICE_NAMES,
    ]
    try:
        proc = subprocess.run(cmd, text=True, capture_output=True, timeout=8, check=False)
    except Exception as exc:
        return {"error": str(exc), "services": {}}
    blocks = proc.stdout.strip().split("\n\n")
    services: dict[str, Any] = {}
    for name, block in zip(SERVICE_NAMES, blocks):
        row: dict[str, str] = {}
        for line in block.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                row[k] = v
        services[name] = row
    failed = [
        name
        for name, row in services.items()
        if row.get("ActiveState") == "failed" or row.get("Result") == "failed"
    ]
    inactive_critical = [
        name
        for name, row in services.items()
        if name.endswith(".service")
        and "trainer-loop.service" not in name
        and row.get("ActiveState") not in {"active", "activating"}
    ]
    return {
        "services": services,
        "failed_services": failed,
        "inactive_critical_services": inactive_critical,
    }


def _http_json(url: str) -> dict[str, Any]:
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            body = resp.read(1_500_000)
            payload = json.loads(body.decode("utf-8"))
            return {"ok": True, "http_status": resp.status, "payload": payload}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _prediction_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [row for row in rows if ":rl_core:" not in str(row.get("_redis_key", ""))]
    invalid_symbols = sorted(
        {
            str(row.get("symbol"))
            for row in primary
            if row.get("symbol") and not is_valid_runtime_symbol(str(row.get("symbol")))
        }
    )
    actions = Counter(str(row.get("selected_action") or row.get("action") or "unknown") for row in primary)
    sources = Counter(str(row.get("trainer_source") or row.get("model_source") or "unknown") for row in primary)
    timeframes = Counter(str(row.get("timeframe") or "unknown") for row in primary)
    expected = [
        v
        for row in primary
        for v in [_coerce_float(row.get("expected_move_after_cost_bps"))]
        if v is not None
    ]
    confidence = [
        v
        for row in primary
        for v in [_coerce_float(row.get("confidence_calibrated") or row.get("confidence"))]
        if v is not None
    ]
    ages = [
        age
        for row in primary
        for age in [_age_seconds(row.get("generated_utc") or row.get("generated_at"))]
        if age is not None
    ]
    return {
        "total_rows": len(rows),
        "primary_rows": len(primary),
        "rl_core_sidecar_rows": len(rows) - len(primary),
        "invalid_symbols": invalid_symbols,
        "trainer_sources": dict(sources.most_common(8)),
        "timeframes": dict(timeframes.most_common()),
        "action_counts": dict(actions.most_common()),
        "expected_move_after_cost_bps": {
            "count": len(expected),
            "min": min(expected) if expected else None,
            "max": max(expected) if expected else None,
            "mean": statistics.fmean(expected) if expected else None,
        },
        "confidence": {
            "count": len(confidence),
            "min": min(confidence) if confidence else None,
            "max": max(confidence) if confidence else None,
            "mean": statistics.fmean(confidence) if confidence else None,
        },
        "freshness": {
            "rows_with_age": len(ages),
            "max_age_seconds": max(ages) if ages else None,
            "stale_over_10m": sum(1 for age in ages if age > 600),
        },
    }


def _signal_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    primary = [row for row in rows if isinstance(row, dict)]
    allowed = [row for row in primary if row.get("paper_fill_allowed") is True]
    reasons = Counter()
    for row in primary:
        for reason in row.get("paper_fill_gate_block_reasons") or row.get("market_state_reject_reasons") or []:
            reasons[str(reason)] += 1
    return {
        "rows": len(primary),
        "paper_fill_allowed": len(allowed),
        "paper_fill_blocked": len(primary) - len(allowed),
        "top_block_reasons": dict(reasons.most_common(12)),
    }


def _data_summary(r: Any) -> dict[str, Any]:
    price_rows = _scan_json(r, "v2:market:prices:*", limit=2000)
    feature_rows = _scan_json(r, "v2:features:latest:*", limit=5000)
    ta_rows = _scan_json(r, "v2:features:ta:*", limit=5000)
    price_ages = [
        age
        for row in price_rows
        for age in [_age_seconds(row.get("fetched_utc") or row.get("generated_utc"))]
        if age is not None
    ]
    feature_states = Counter(str(row.get("feature_freshness_state") or "unknown") for row in feature_rows)
    return {
        "prices": {
            "count": len(price_rows),
            "rows_with_age": len(price_ages),
            "max_age_seconds": max(price_ages) if price_ages else None,
            "stale_over_2m": sum(1 for age in price_ages if age > 120),
        },
        "features_latest_count": len(feature_rows),
        "features_freshness_states": dict(feature_states.most_common()),
        "ta_count": len(ta_rows),
        "coinank_samples": {
            "funding": len(_scan_json(r, "latest:coinank:funding:*", limit=2000)),
            "open_interest": len(_scan_json(r, "latest:coinank:open_interest:*", limit=2000)),
            "long_short": len(_scan_json(r, "latest:coinank:long_short:*", limit=2000)),
            "liquidations": len(_scan_json(r, "latest:coinank:liquidations:*", limit=2000)),
        },
        "liquidation_levels_count": len(_scan_json(r, "v2:liquidations:levels:*", limit=5000)),
    }


def sample_runtime() -> dict[str, Any]:
    r = _connect_redis()
    predictions = _scan_json(r, "v2:prediction:*", limit=5000)
    signals = _scan_json(r, "v2:signals:paper*", limit=5000)
    risk = _redis_json(r, "v2:risk:decisions", []) or []
    orchestrator = _redis_json(r, "v2:orchestrator:decisions", {}) or {}
    ledger = _redis_json(r, "v2:paper:ledger", {}) or {}
    portfolio = _redis_json(r, "v2:portfolio:state", {}) or {}
    runtime_truth = _http_json("http://127.0.0.1:5173/api/v1/operator-runtime/truth")
    pipeline_status = _http_json("http://127.0.0.1:5173/api/v2/pipeline/status?symbols=BTCUSDT,HYPEUSDT&timeframes=1m,5m")
    pipeline_payload = pipeline_status.get("payload") if pipeline_status.get("ok") else {}
    runtime_payload = runtime_truth.get("payload") if runtime_truth.get("ok") else {}
    risk_rows = risk if isinstance(risk, list) else [risk] if isinstance(risk, dict) else []
    accepted = ledger.get("accepted") if isinstance(ledger, dict) else []
    held = ledger.get("held_by_paper_fill_gate") if isinstance(ledger, dict) else []
    blocked = ledger.get("blocked") if isinstance(ledger, dict) else []
    issues: list[str] = []
    pred_summary = _prediction_summary(predictions)
    if pred_summary["invalid_symbols"]:
        issues.append("INVALID_SYMBOLS_IN_PREDICTION_GRID")
    if pred_summary["primary_rows"] == 0:
        issues.append("NO_PRIMARY_PREDICTIONS")
    if pred_summary["freshness"]["stale_over_10m"]:
        issues.append("STALE_PREDICTIONS_OVER_10M")
    if runtime_payload.get("trainer_status") in {None, "MISSING"}:
        issues.append("RUNTIME_TRUTH_TRAINER_STATUS_MISSING")
    if pipeline_payload and pipeline_payload.get("live_gate") == "blocked_human_only":
        issues.append("PIPELINE_STATUS_LIVE_GATE_STALE_BLOCKED")
    if any(not is_valid_runtime_symbol(str(sym)) for sym in pipeline_payload.get("symbols", []) if sym):
        issues.append("PIPELINE_STATUS_INVALID_SYMBOLS")
    data_summary = _data_summary(r)
    if data_summary["prices"]["stale_over_2m"]:
        issues.append("STALE_PRICE_ROWS_OVER_2M")
    paper_block_reason_counts = Counter()
    if isinstance(blocked, list):
        for row in blocked:
            if not isinstance(row, dict):
                continue
            for reason in row.get("paper_fill_gate_block_reasons") or row.get("market_state_reject_reasons") or []:
                paper_block_reason_counts[str(reason)] += 1
    if paper_block_reason_counts.get("MARKET_STATE_ID_MISSING") or paper_block_reason_counts.get("VALID_FOR_PAPER_NOT_TRUE"):
        issues.append("PAPER_CANDIDATES_BLOCKED_BY_MARKET_STATE_LINEAGE")
    return {
        "schema_version": "v2_one_hour_monitor_sample_v1",
        "generated_est": _est_now(),
        "generated_utc": _utc_now(),
        "redis_connected": r is not None,
        "services": _service_status(),
        "api": {
            "operator_runtime_truth_ok": runtime_truth.get("ok", False),
            "pipeline_status_ok": pipeline_status.get("ok", False),
            "pipeline_status_live_gate": pipeline_payload.get("live_gate"),
            "pipeline_symbol_count": len(pipeline_payload.get("symbols") or []),
        },
        "runtime_truth": {
            "classification": runtime_payload.get("classification"),
            "live_gate": runtime_payload.get("live_gate"),
            "trader_state": runtime_payload.get("trader_state"),
            "trainer_status": runtime_payload.get("trainer_status"),
            "cuda_trainer_status": runtime_payload.get("cuda_trainer_status"),
            "risk_status": runtime_payload.get("risk_status"),
            "orchestrator_status": runtime_payload.get("orchestrator_status"),
            "paper_trader_status": runtime_payload.get("paper_trader_status"),
            "live_order_submit_blocker": runtime_payload.get("live_order_submit_blocker"),
        },
        "predictions": pred_summary,
        "signals": _signal_summary(signals),
        "risk": {
            "rows": len(risk_rows),
            "decision_ids_present": sum(1 for row in risk_rows if isinstance(row, dict) and row.get("risk_decision_id")),
            "actions": dict(Counter(str(row.get("risk_action") or row.get("action") or "unknown") for row in risk_rows if isinstance(row, dict)).most_common()),
        },
        "orchestrator": {
            "classification": orchestrator.get("classification") if isinstance(orchestrator, dict) else None,
            "winner_count": len(orchestrator.get("winners") or orchestrator.get("latest_winners") or []) if isinstance(orchestrator, dict) else 0,
            "held_by_paper_fill_gate_count": len(orchestrator.get("held_by_paper_fill_gate") or []) if isinstance(orchestrator, dict) else 0,
        },
        "paper": {
            "accepted_count": len(accepted) if isinstance(accepted, list) else ledger.get("accepted_count"),
            "held_count": len(held) if isinstance(held, list) else ledger.get("held_by_paper_fill_gate_count"),
            "blocked_count": len(blocked) if isinstance(blocked, list) else ledger.get("blocked_count"),
            "top_block_reasons": dict(paper_block_reason_counts.most_common(10)),
            "equity": portfolio.get("equity"),
            "pnl": portfolio.get("total_pnl_usd"),
            "open_positions_count": portfolio.get("open_positions_count"),
            "economic_fill_total": portfolio.get("economic_fill_total"),
        },
        "data": data_summary,
        "issues": sorted(set(issues)),
        "safety": {
            "real_order_mutation": False,
            "test_order_called": False,
            "leverage_or_margin_mutation": False,
            "old_redis_write": False,
            "legacy_restart": False,
            "raw_credentials_emitted": False,
        },
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _append_jsonl(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def _rollup(samples: list[dict[str, Any]], *, finished: bool) -> dict[str, Any]:
    issue_counts = Counter(issue for sample in samples for issue in sample.get("issues", []))
    latest = samples[-1] if samples else {}
    return {
        "schema_version": "v2_one_hour_monitor_rollup_v1",
        "gate": (
            "V2_ONE_HOUR_TRAINER_RISK_ORCHESTRATOR_DATA_WEBSITE_MONITOR_READY"
            if finished
            else "V2_ONE_HOUR_TRAINER_RISK_ORCHESTRATOR_DATA_WEBSITE_MONITOR_RUNNING"
        ),
        "generated_est": _est_now(),
        "started_est": samples[0].get("generated_est") if samples else None,
        "latest_est": latest.get("generated_est"),
        "sample_count": len(samples),
        "monitor_finished": finished,
        "issue_counts": dict(issue_counts.most_common()),
        "latest": latest,
        "strategy_diagnosis": {
            "prediction_generation": "Native predictions are read from v2:prediction:{symbol}:{timeframe}; orchestrator picks scored proposal winners; risk loop independently records risk decisions; paper loop accepts only signals with paper_fill_allowed and complete lineage.",
            "current_strategy_inputs": [
                "OHLCV and current price",
                "TA feature rows",
                "funding/open interest/orderbook/liquidation optional features",
                "CoinAnk long-short/funding/OI where current",
                "market-state integrity masks optional/event-dependent gaps",
            ],
            "improvement_candidates": [
                "Fix any runtime truth source still reading old trainer bridge status.",
                "Remove invalid non-runtime symbols from website/API control grids.",
                "Keep liquidity/liquidation levels as optional but scored features for training and paper actionability.",
                "Use paper mark-to-market outcomes to downrank strategies whose expected_move_after_cost fails after fees/slippage.",
            ],
        },
    }


def _publish(samples: list[dict[str, Any]], *, finished: bool) -> None:
    rollup = _rollup(samples, finished=finished)
    for base in (PUBLIC_DIR, WORKLOG_DIR):
        _write_json(base / "monitor_latest_sample.json", samples[-1] if samples else {})
        _write_json(base / "one_hour_monitor_rollup.json", rollup)
        _write_json(base / "operator_dashboard_payload.json", rollup)
        (base / "GO_NO_GO.md").write_text(rollup["gate"] + "\n")
        lines = [
            "# V2 One Hour Trainer Risk Orchestrator Data Website Monitor Report",
            "",
            f"Gate: `{rollup['gate']}`",
            f"Generated EST: `{rollup['generated_est']}`",
            f"Sample count: `{rollup['sample_count']}`",
            f"Monitor finished: `{rollup['monitor_finished']}`",
            "",
            "## Latest",
            "",
            f"- live_gate: `{latest_value(rollup, 'runtime_truth.live_gate')}`",
            f"- trainer_status: `{latest_value(rollup, 'runtime_truth.trainer_status')}`",
            f"- prediction_primary_rows: `{latest_value(rollup, 'predictions.primary_rows')}`",
            f"- signal_rows: `{latest_value(rollup, 'signals.rows')}`",
            f"- risk_rows: `{latest_value(rollup, 'risk.rows')}`",
            f"- paper_equity: `{latest_value(rollup, 'paper.equity')}`",
            "",
            "## Issues",
            "",
            *(f"- `{key}`: {value}" for key, value in rollup["issue_counts"].items()),
            "",
            "Safety: monitor-only; no real order/test-order/cancel/modify, no leverage or margin mutation, no old Redis write, no legacy restart, and no raw credential output.",
        ]
        (base / "V2_ONE_HOUR_TRAINER_RISK_ORCHESTRATOR_DATA_WEBSITE_MONITOR_REPORT.md").write_text("\n".join(lines) + "\n")


def latest_value(rollup: dict[str, Any], dotted: str) -> Any:
    value: Any = rollup.get("latest") or {}
    for part in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="v2_one_hour_trainer_risk_orchestrator_data_website_monitor")
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args(argv)

    samples: list[dict[str, Any]] = []
    deadline = time.monotonic() + max(1, int(args.duration_seconds))
    while True:
        sample = sample_runtime()
        samples.append(sample)
        for base in (PUBLIC_DIR, WORKLOG_DIR):
            _append_jsonl(base / "monitor_samples.jsonl", sample)
        finished = args.once or time.monotonic() >= deadline
        _publish(samples, finished=finished)
        print(json.dumps({
            "generated_est": sample["generated_est"],
            "sample": len(samples),
            "issues": sample["issues"],
            "finished": finished,
        }, sort_keys=True), flush=True)
        if finished:
            return 0
        time.sleep(max(1, int(args.interval_seconds)))


if __name__ == "__main__":
    raise SystemExit(main())
