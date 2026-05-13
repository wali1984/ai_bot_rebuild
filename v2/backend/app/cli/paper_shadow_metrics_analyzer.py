from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[4]
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "codex_independent_v2_support" / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "codex_independent_v2_support" / "latest"
PUBLIC_RUNTIME_DIR = REPO_ROOT / "v2" / "frontend" / "public" / "operator_runtime"


def _iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _read_json(path: Path, fallback: Any | None = None) -> Any:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {} if fallback is None else fallback


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _write_text(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body if body.endswith("\n") else body + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True))


def _num(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _pnl_value(event: dict[str, Any]) -> float | None:
    for key in ("paper_pnl_delta", "paper_realized_pnl", "paper_pnl_delta_usdt", "realized_pnl", "pnl"):
        value = _num(event.get(key))
        if value is not None:
            return value
    return None


def _is_fill(event: dict[str, Any]) -> bool:
    text = " ".join(str(event.get(key, "")) for key in ("paper_result", "ledger_action", "result", "status")).lower()
    return "fill" in text and "block" not in text


def _is_blocked(event: dict[str, Any]) -> bool:
    text = " ".join(str(event.get(key, "")) for key in ("paper_result", "ledger_action", "risk_action", "status", "reason")).lower()
    return "block" in text or "deny" in text


def _confidence_bucket(value: Any) -> str:
    confidence = _num(value)
    if confidence is None:
        return "missing"
    if confidence >= 0.8:
        return "0.80_plus"
    if confidence >= 0.7:
        return "0.70_to_0.80"
    if confidence >= 0.6:
        return "0.60_to_0.70"
    return "below_0.60"


def _action(event: dict[str, Any]) -> str:
    for key in ("action", "side", "risk_reason_code", "ledger_action"):
        value = event.get(key)
        if value:
            return str(value)
    return "missing"


def _symbol(event: dict[str, Any]) -> str:
    return str(event.get("symbol") or event.get("pair") or "missing")


def _distribution(events: list[dict[str, Any]], key_fn) -> dict[str, int]:
    return dict(Counter(key_fn(event) for event in events))


def _sum_by(events: list[dict[str, Any]], key_fn) -> dict[str, float]:
    totals: defaultdict[str, float] = defaultdict(float)
    for event in events:
        value = _pnl_value(event)
        if value is not None:
            totals[key_fn(event)] += value
    return {key: round(value, 8) for key, value in sorted(totals.items())}


def _elapsed_seconds(now: datetime, observation: dict[str, Any], events: list[dict[str, Any]]) -> int | None:
    explicit = _num(observation.get("elapsed_observation_seconds"))
    if explicit is not None:
        return int(explicit)
    started = _parse_ts(observation.get("observation_started_at") or observation.get("started_at"))
    if started is not None:
        return max(0, int((now - started).total_seconds()))
    timestamps = sorted(ts for event in events if (ts := _parse_ts(event.get("generated_at") or event.get("timestamp"))) is not None)
    if len(timestamps) >= 2:
        return max(0, int((timestamps[-1] - timestamps[0]).total_seconds()))
    return None


def analyze_metrics(
    observation: dict[str, Any],
    runtime_status: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    fills = [event for event in events if _is_fill(event)]
    blocked = [event for event in events if _is_blocked(event)]
    pnl_values = [value for event in fills if (value := _pnl_value(event)) is not None]
    wins = [value for value in pnl_values if value > 0]
    losses = [value for value in pnl_values if value < 0]
    total_pnl = _num(observation.get("paper_pnl_current_usdt"))
    if total_pnl is None and pnl_values:
        total_pnl = sum(pnl_values)
    fee_drag = sum(_num(event.get("fee_usdt")) or 0.0 for event in fills)
    slippage_drag = sum(_num(event.get("slippage_usdt")) or 0.0 for event in fills)
    elapsed = _elapsed_seconds(now, observation, events)
    elapsed_hours = elapsed / 3600 if elapsed and elapsed > 0 else None
    fill_rate = len(fills) / len(events) if events else None
    fills_per_hour = len(fills) / elapsed_hours if elapsed_hours else None
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None

    missing_evidence: list[str] = []
    if elapsed is None:
        missing_evidence.append("elapsed_observation_time")
    if total_pnl is None:
        missing_evidence.append("paper_pnl")
    if not events:
        missing_evidence.append("paper_event_stream")
    if not runtime_status:
        missing_evidence.append("paper_runtime_status")

    classifications: list[str] = []
    if elapsed is None or elapsed < 6 * 3600:
        classifications.append("PAPER_SHADOW_6H_PENDING")
    else:
        classifications.append("PAPER_SHADOW_6H_COMPLETE")
    if elapsed is None or elapsed < 24 * 3600:
        classifications.append("PAPER_SHADOW_24H_PENDING")
    else:
        classifications.append("PAPER_SHADOW_24H_COMPLETE")
    if total_pnl is None:
        classifications.append("PAPER_PNL_INSUFFICIENT_EVIDENCE")
    elif total_pnl < 0:
        classifications.append("PAPER_PNL_NEGATIVE_BLOCKS_CANARY")
    elif elapsed is None or elapsed < 24 * 3600:
        classifications.append("PAPER_PNL_POSITIVE_BUT_NEEDS_24H")
    if fills_per_hour is not None and fills_per_hour > 60:
        classifications.append("PAPER_FILL_RATE_TOO_HIGH")
    if profit_factor is None or profit_factor <= 1.0 or elapsed is None or elapsed < 24 * 3600:
        classifications.append("PAPER_EDGE_UNPROVEN")

    canary_blockers = [
        classification
        for classification in classifications
        if classification
        in {
            "PAPER_SHADOW_6H_PENDING",
            "PAPER_SHADOW_24H_PENDING",
            "PAPER_PNL_NEGATIVE_BLOCKS_CANARY",
            "PAPER_PNL_INSUFFICIENT_EVIDENCE",
            "PAPER_FILL_RATE_TOO_HIGH",
            "PAPER_EDGE_UNPROVEN",
        }
    ]

    return {
        "generated_at": _iso_now(),
        "source_paths": [
            "v2/frontend/public/operator_runtime/paper_shadow_observation/latest/paper_shadow_observation_status.json",
            "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
            "v2/frontend/public/operator_runtime/paper_online/latest/paper_events.jsonl",
        ],
        "live_gate": "blocked_human_only",
        "elapsed_observation_seconds": elapsed,
        "status_1h": "COMPLETE" if elapsed is not None and elapsed >= 3600 else "PENDING",
        "status_6h": "COMPLETE" if elapsed is not None and elapsed >= 6 * 3600 else "PENDING",
        "status_24h": "COMPLETE" if elapsed is not None and elapsed >= 24 * 3600 else "PENDING",
        "events": len(events),
        "fills": len(fills),
        "blocked_intents": len(blocked),
        "pnl": round(total_pnl, 8) if total_pnl is not None else None,
        "win_rate": round(len(wins) / len(pnl_values), 8) if pnl_values else None,
        "profit_factor": round(profit_factor, 8) if profit_factor is not None else None,
        "average_win": round(statistics.mean(wins), 8) if wins else None,
        "average_loss": round(statistics.mean(losses), 8) if losses else None,
        "fill_rate": round(fill_rate, 8) if fill_rate is not None else None,
        "fills_per_hour": round(fills_per_hour, 8) if fills_per_hour is not None else None,
        "churn_risk": "HIGH" if fills_per_hour is not None and fills_per_hour > 30 else "UNKNOWN" if fills_per_hour is None else "LOW",
        "fee_slippage_drag": round(fee_drag + slippage_drag, 8),
        "confidence_bucket_performance": _sum_by(fills, lambda event: _confidence_bucket(event.get("confidence"))),
        "symbol_distribution": _distribution(events, _symbol),
        "action_distribution": _distribution(events, _action),
        "missing_evidence": missing_evidence,
        "canary_blockers": sorted(set(canary_blockers)),
        "classifications": sorted(set(classifications)),
        "paper_runtime_called": False,
        "profitability_faked": False,
    }


def build_analysis(root: Path = REPO_ROOT) -> dict[str, Any]:
    observation = _read_json(PUBLIC_RUNTIME_DIR / "paper_shadow_observation" / "latest" / "paper_shadow_observation_status.json", {})
    runtime_status = _read_json(PUBLIC_RUNTIME_DIR / "paper_online" / "latest" / "paper_runtime_status.json", {})
    events = _read_jsonl(PUBLIC_RUNTIME_DIR / "paper_online" / "latest" / "paper_events.jsonl")
    return analyze_metrics(observation, runtime_status, events)


def build_report(payload: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Paper-Shadow Metrics Analyzer Report",
            "",
            f"Generated: {payload['generated_at']}",
            f"Live gate: `{payload['live_gate']}`",
            f"Elapsed seconds: `{payload['elapsed_observation_seconds']}`",
            f"Events: `{payload['events']}`",
            f"Fills: `{payload['fills']}`",
            f"Blocked intents: `{payload['blocked_intents']}`",
            f"PnL: `{payload['pnl']}`",
            f"Win rate: `{payload['win_rate']}`",
            f"Profit factor: `{payload['profit_factor']}`",
            "",
            "Classifications:",
            *(f"- `{item}`" for item in payload["classifications"]),
            "",
            "Canary blockers:",
            *(f"- `{item}`" for item in payload["canary_blockers"]),
            "",
            "Missing evidence:",
            *(f"- `{item}`" for item in payload["missing_evidence"] or ["none"]),
            "",
            "This analyzer is read-only and does not call the paper runtime.",
        ]
    )


def write_outputs(payload: dict[str, Any]) -> None:
    _write_json(FINAL_DIR / "paper_shadow_metrics_analysis.json", payload)
    _write_json(PUBLIC_DIR / "paper_shadow_metrics_analysis.json", payload)
    _write_text(FINAL_DIR / "PAPER_SHADOW_METRICS_ANALYZER_REPORT.md", build_report(payload))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze paper-shadow metrics without enabling live.")
    parser.add_argument("--write", action="store_true", help="write analyzer artifacts")
    args = parser.parse_args(argv)
    payload = build_analysis(REPO_ROOT)
    if args.write:
        write_outputs(payload)
    else:
        print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
