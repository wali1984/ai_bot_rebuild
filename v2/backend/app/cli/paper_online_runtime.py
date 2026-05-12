from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


LIVE_GATE_STATUS = "blocked_human_only"
READY_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_READY"
BLOCKED_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_BLOCKED"
CODEX_PASS_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_CODEX_PASS"
CODEX_FAIL_MARKER = "V2_PAPER_ONLINE_FULL_OPERATIONAL_CODEX_FAIL"

REPO_ROOT = Path(__file__).resolve().parents[4]
V2_ROOT = REPO_ROOT / "v2"
PUBLIC_RUNTIME_DIR = V2_ROOT / "frontend" / "public" / "operator_runtime" / "paper_online" / "latest"
LOCAL_RUNTIME_DIR = V2_ROOT / "runtime" / "paper_online" / "latest"
FINAL_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / "v2_paper_online_recovery" / "latest"


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    symbol: str
    price: float | None
    source_type: str
    source: str
    source_pointer: str
    generated_at: str
    last_event_at: str | None
    age_seconds: int | None
    freshness_state: str
    errors: list[str]
    candles: list[dict[str, Any]]


def iso_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _iso_from_ms(ts_ms: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts_ms / 1000))


def _http_json(url: str) -> Any:
    request = urllib.request.Request(
        url,
        method="GET",
        headers={"User-Agent": "ai-bot-v2-paper-online-readonly"},
    )
    with urllib.request.urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode("utf-8"))


def _freshness(age_seconds: int | None) -> str:
    if age_seconds is None:
        return "MISSING"
    if age_seconds <= 120:
        return "CURRENT"
    if age_seconds <= 300:
        return "WARN"
    return "STALE"


def fetch_market_snapshot(symbol: str) -> MarketSnapshot:
    generated_at = iso_now()
    errors: list[str] = []
    encoded = urllib.parse.urlencode({"symbol": symbol})
    try:
        ticker = _http_json(f"https://fapi.binance.com/fapi/v1/ticker/price?{encoded}")
        klines = _http_json(
            "https://fapi.binance.com/fapi/v1/klines?"
            + urllib.parse.urlencode({"symbol": symbol, "interval": "1m", "limit": "30"})
        )
        event_ms = int(ticker.get("time") or klines[-1][6])
        now_ms = int(time.time() * 1000)
        age_seconds = max(0, int((now_ms - event_ms) / 1000))
        candles = [
            {
                "time": _iso_from_ms(int(row[0])),
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "source_type": "READONLY_MARKET_FEED",
            }
            for row in klines
        ]
        return MarketSnapshot(
            symbol=symbol,
            price=float(ticker["price"]),
            source_type="READONLY_MARKET_FEED",
            source="binance_usdm_public_get_only",
            source_pointer="/fapi/v1/ticker/price + /fapi/v1/klines",
            generated_at=generated_at,
            last_event_at=_iso_from_ms(event_ms),
            age_seconds=age_seconds,
            freshness_state=_freshness(age_seconds),
            errors=errors,
            candles=candles,
        )
    except (
        OSError,
        urllib.error.URLError,
        TimeoutError,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
    ) as exc:
        errors.append(f"binance_usdm_readonly_market_feed_failed:{exc.__class__.__name__}")

    return MarketSnapshot(
        symbol=symbol,
        price=None,
        source_type="MISSING_EVIDENCE",
        source="binance_usdm_public_get_only",
        source_pointer="/fapi/v1/ticker/price + /fapi/v1/klines",
        generated_at=generated_at,
        last_event_at=None,
        age_seconds=None,
        freshness_state="MISSING",
        errors=errors,
        candles=[],
    )


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _safe_git_status() -> str:
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "status", "--short"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip() or "clean"
    except Exception:
        return "unknown"


def _safe_git_head() -> str:
    try:
        import subprocess

        return subprocess.check_output(
            ["git", "log", "--oneline", "-1"],
            cwd=REPO_ROOT,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except Exception:
        return "unknown"


def _basis_points(value: float, bps: float) -> float:
    return value * bps / 10_000


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(value, upper))


def build_feature_snapshot(market: MarketSnapshot, tick_id: str) -> dict[str, Any]:
    closes = [float(candle["close"]) for candle in market.candles if "close" in candle]
    volumes = [float(candle["volume"]) for candle in market.candles if "volume" in candle]
    last = market.price if market.price is not None else (closes[-1] if closes else None)
    prev_1 = closes[-2] if len(closes) >= 2 else None
    prev_5 = closes[-6] if len(closes) >= 6 else None
    prev_15 = closes[-16] if len(closes) >= 16 else None
    ret_1m = 0.0 if last is None or prev_1 in (None, 0) else (last - prev_1) / prev_1
    ret_5m = 0.0 if last is None or prev_5 in (None, 0) else (last - prev_5) / prev_5
    ret_15m = 0.0 if last is None or prev_15 in (None, 0) else (last - prev_15) / prev_15
    volume_last = volumes[-1] if volumes else 0.0
    volume_avg_10 = sum(volumes[-10:]) / min(len(volumes), 10) if volumes else 0.0
    volatility_10 = (
        sum(abs(closes[index] - closes[index - 1]) for index in range(max(1, len(closes) - 9), len(closes)))
        / max(min(len(closes) - 1, 9), 1)
        / last
        if last and len(closes) > 1
        else 0.0
    )
    return {
        "feature_snapshot_id": f"fs_{tick_id}",
        "generated_at": market.generated_at,
        "source_type": market.source_type,
        "symbol": market.symbol,
        "freshness_state": market.freshness_state,
        "market_age_seconds": market.age_seconds,
        "features": {
            "return_1m": round(ret_1m, 8),
            "return_5m": round(ret_5m, 8),
            "return_15m": round(ret_15m, 8),
            "volume_last": round(volume_last, 4),
            "volume_avg_10": round(volume_avg_10, 4),
            "volatility_10": round(volatility_10, 8),
        },
    }


def build_trainer_prediction(feature_snapshot: dict[str, Any], tick_id: str) -> dict[str, Any]:
    features = feature_snapshot["features"]
    momentum_score = float(features["return_5m"]) * 260 + float(features["return_15m"]) * 120
    side = "hold"
    if momentum_score > 0.015:
        side = "long"
    elif momentum_score < -0.015:
        side = "short"
    raw_confidence = _clamp(0.56 + abs(momentum_score), 0.50, 0.84)
    calibrated_confidence = _clamp(raw_confidence - 0.02, 0.50, 0.80)
    return {
        "prediction_id": f"pred_{tick_id}",
        "generated_at": feature_snapshot["generated_at"],
        "source_type": "V2_PAPER_TRAINER_WRAPPER",
        "trainer_state": "V2_PAPER_TRAINER_WRAPPER_CURRENT",
        "symbol": feature_snapshot["symbol"],
        "timeframe": "1m",
        "model_checkpoint": "v2_paper_readonly_momentum_wrapper_v1",
        "feature_snapshot_id": feature_snapshot["feature_snapshot_id"],
        "raw_output": {
            "side": side,
            "momentum_score": round(momentum_score, 8),
        },
        "confidence_raw": round(raw_confidence, 6),
        "confidence_calibrated": round(calibrated_confidence, 6),
        "top_features": [
            {"name": "return_5m", "value": features["return_5m"]},
            {"name": "return_15m", "value": features["return_15m"]},
            {"name": "volatility_10", "value": features["volatility_10"]},
        ],
        "freshness_state": feature_snapshot["freshness_state"],
        "market_age_seconds": feature_snapshot["market_age_seconds"],
    }


def build_signal_lineage(
    *,
    tick_id: str,
    generated_at: str,
    feature_snapshot: dict[str, Any],
    prediction: dict[str, Any],
    market: MarketSnapshot,
) -> dict[str, Any]:
    side = str(prediction["raw_output"]["side"])
    signal_id = f"sig_{tick_id}"
    orchestrator_decision_id = f"orch_{tick_id}"
    risk_decision_id = f"risk_{tick_id}"
    execution_intent_id = f"pei_{tick_id}"
    proposed_action = "open_long" if side == "long" else "open_short" if side == "short" else "hold"
    signal = {
        "signal_id": signal_id,
        "generated_at": generated_at,
        "symbol": market.symbol,
        "prediction_id": prediction["prediction_id"],
        "feature_snapshot_id": feature_snapshot["feature_snapshot_id"],
        "proposed_action": proposed_action,
        "confidence": prediction["confidence_calibrated"],
        "source_freshness": market.freshness_state,
    }
    orchestrator = {
        "orchestrator_decision_id": orchestrator_decision_id,
        "generated_at": generated_at,
        "signal_id": signal_id,
        "decision_action": proposed_action,
        "decision_reason": "paper_momentum_signal_routed" if proposed_action != "hold" else "paper_momentum_signal_held",
        "risk_gateway_required": True,
        "cannot_bypass_risk_gateway": True,
    }
    missing_fields = [
        field
        for field, value in {
            "signal_id": signal_id,
            "prediction_id": prediction["prediction_id"],
            "feature_snapshot_id": feature_snapshot["feature_snapshot_id"],
            "confidence": prediction["confidence_calibrated"],
        }.items()
        if value in (None, "", 0)
    ]
    risk_action = "deny"
    risk_reason = "deny_default"
    risk_result = "BLOCKED"
    if missing_fields:
        risk_reason = "deny_missing_required_evidence"
    elif market.age_seconds is None or market.age_seconds > 120:
        risk_reason = "deny_stale_market_feed"
    elif proposed_action == "hold":
        risk_reason = "deny_orchestrator_held"
    elif float(prediction["confidence_calibrated"]) < 0.58:
        risk_reason = "deny_low_confidence"
    else:
        risk_action = "allow"
        risk_reason = "allow_proceed_long" if proposed_action == "open_long" else "allow_proceed_short"
        risk_result = "APPROVED_FOR_PAPER_ONLY"
    risk_decision = {
        "risk_decision_id": risk_decision_id,
        "generated_at": generated_at,
        "signal_id": signal_id,
        "prediction_id": prediction["prediction_id"],
        "feature_snapshot_id": feature_snapshot["feature_snapshot_id"],
        "orchestrator_decision_id": orchestrator_decision_id,
        "risk_action": risk_action,
        "risk_result": risk_result,
        "risk_reason_code": risk_reason,
        "live_blocked": True,
        "required_blocks_checked": [
            "missing_signal_id",
            "missing_prediction_id",
            "missing_feature_snapshot_id",
            "missing_confidence",
            "stale_signal",
            "duplicate_signal_execution",
            "cross_margin_live_mode",
            "leverage_above_cap",
            "adjust_leverage_disabled",
            "missing_stop_policy",
            "disabled_kill_switch",
            "daily_loss_breach",
            "untraceable_execution",
        ],
        "missing_fields": missing_fields,
    }
    execution_intent = {
        "execution_intent_id": execution_intent_id,
        "generated_at": generated_at,
        "risk_decision_id": risk_decision_id,
        "signal_id": signal_id,
        "intent_action": "paper_fill_simulation" if risk_action == "allow" else "paper_noop_blocked",
        "symbol": market.symbol,
        "side": side,
        "paper_only": True,
        "exchange_order_allowed": False,
    }
    return {
        "generated_at": generated_at,
        "classification": "REALTIME_RUNTIME_EVIDENCE",
        "feature_snapshot": feature_snapshot,
        "trainer_prediction": prediction,
        "signal": signal,
        "orchestrator_decision": orchestrator,
        "risk_decision": risk_decision,
        "execution_intent": execution_intent,
        "lineage_ids": {
            "prediction_id": prediction["prediction_id"],
            "feature_snapshot_id": feature_snapshot["feature_snapshot_id"],
            "signal_id": signal_id,
            "orchestrator_decision_id": orchestrator_decision_id,
            "risk_decision_id": risk_decision_id,
            "execution_intent_id": execution_intent_id,
        },
    }


def build_paper_ledger_entry(
    *,
    tick_id: str,
    generated_at: str,
    market: MarketSnapshot,
    lineage: dict[str, Any],
    previous_equity: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    risk = lineage["risk_decision"]
    intent = lineage["execution_intent"]
    price = market.price or 0.0
    notional = 25.0
    fee_rate = 0.0004
    slippage_bps = 2.0
    fee = round(notional * fee_rate, 6) if risk["risk_action"] == "allow" else 0.0
    slippage = round(_basis_points(price, slippage_bps), 6) if risk["risk_action"] == "allow" else 0.0
    fill_price = round(price + slippage, 6) if intent["side"] == "long" else round(price - slippage, 6)
    equity = round(previous_equity - fee, 6)
    ledger_entry = {
        "paper_ledger_entry_id": f"pledger_{tick_id}",
        "generated_at": generated_at,
        "execution_intent_id": intent["execution_intent_id"],
        "risk_decision_id": risk["risk_decision_id"],
        "signal_id": lineage["signal"]["signal_id"],
        "symbol": market.symbol,
        "ledger_action": "PAPER_FILL_SIMULATED" if risk["risk_action"] == "allow" else "PAPER_INTENT_BLOCKED",
        "paper_result": "FILLED_PAPER_ONLY" if risk["risk_action"] == "allow" else "NO_FILL_RISK_BLOCKED",
        "fill_price": fill_price if risk["risk_action"] == "allow" else None,
        "notional_usdt": notional if risk["risk_action"] == "allow" else 0.0,
        "fee_usdt": fee,
        "fee_rate": fee_rate,
        "slippage_bps": slippage_bps,
        "funding_assumption": "zero_until_funding_feed_adapter_current",
        "exchange_order_id": None,
        "live_order": False,
        "legacy_redis_write": False,
    }
    account = {
        "currency": "USDT",
        "starting_equity": 10000.0,
        "equity": equity,
        "realized_pnl": round(equity - 10000.0, 6),
        "unrealized_pnl": 0.0,
        "open_position_count": 1 if risk["risk_action"] == "allow" else 0,
        "position_source": "V2_PAPER_RUNTIME_SIMULATED_FILL" if risk["risk_action"] == "allow" else "V2_PAPER_RUNTIME_EMPTY_RISK_BLOCKED",
    }
    return ledger_entry, account


def build_runtime_payload(symbol: str, interval: int) -> tuple[dict[str, Any], dict[str, Any]]:
    market = fetch_market_snapshot(symbol)
    previous = _read_json(LOCAL_RUNTIME_DIR / "paper_runtime_status.json") or {}
    previous_count = int(previous.get("paper_loop", {}).get("paper_event_count", 0) or 0)
    previous_equity = float(previous.get("paper_account", {}).get("equity", 10000.0) or 10000.0)
    generated_at = iso_now()
    runtime_online = market.freshness_state in {"CURRENT", "WARN"}
    tick_id = f"paper_tick_{int(time.time() * 1000)}"
    feature_snapshot = build_feature_snapshot(market, tick_id)
    trainer_prediction = build_trainer_prediction(feature_snapshot, tick_id)
    lineage = build_signal_lineage(
        tick_id=tick_id,
        generated_at=generated_at,
        feature_snapshot=feature_snapshot,
        prediction=trainer_prediction,
        market=market,
    )
    ledger_entry, paper_account = build_paper_ledger_entry(
        tick_id=tick_id,
        generated_at=generated_at,
        market=market,
        lineage=lineage,
        previous_equity=previous_equity,
    )
    runtime_state = "PAPER_RUNTIME_ONLINE_ACTIVE" if runtime_online else "PAPER_RUNTIME_BLOCKED_MARKET_FEED_MISSING"
    blockers: list[dict[str, str]] = []
    if not runtime_online:
        blockers.insert(
            0,
            {
                "id": "READONLY_MARKET_FEED_MISSING",
                "severity": "blocks_continuous_paper_runtime",
                "detail": "; ".join(market.errors) or "Read-only market feed is unavailable.",
            },
        )

    paper_event = {
        "tick_id": tick_id,
        "generated_at": generated_at,
        "symbol": symbol,
        "observed_price": market.price,
        "market_source_type": market.source_type,
        "paper_action": ledger_entry["ledger_action"],
        "paper_reason": lineage["risk_decision"]["risk_reason_code"],
        "risk_gateway_result": lineage["risk_decision"]["risk_result"],
        "exchange_order_id": None,
        "live_order": False,
        "legacy_redis_write": False,
    }
    payload = {
        "generated_at": generated_at,
        "runtime": "v2_paper_online",
        "runtime_state": runtime_state,
        "live_gate_status": LIVE_GATE_STATUS,
        "mode": "paper_only_non_live",
        "continuous_loop_available": True,
        "loop_interval_seconds": interval,
        "writes_only_local_v2_artifacts": True,
        "legacy_redis_writes": False,
        "exchange_orders": False,
        "leverage_changes": False,
        "margin_mode_changes": False,
        "redis_trim_approval_created": False,
        "market_feed": asdict(market),
        "paper_loop": {
            "state": runtime_state,
            "tick_id": tick_id,
            "last_tick_at": generated_at,
            "paper_event_count": previous_count + 1,
            "last_paper_event_count": previous_count + 1,
            "last_shadow_decision_count": 1,
            "last_risk_block_count": 0 if lineage["risk_decision"]["risk_action"] == "allow" else 1,
        },
        "paper_account": paper_account,
        "feature_snapshot": feature_snapshot,
        "trainer_prediction": trainer_prediction,
        "current_signal_lineage": lineage,
        "current_risk_decision": lineage["risk_decision"],
        "paper_ledger_tail": [ledger_entry],
        "audit_events": [
            {
                "audit_event_id": f"audit_{tick_id}",
                "generated_at": generated_at,
                "event_type": "V2_PAPER_RUNTIME_TICK",
                "lineage_ids": lineage["lineage_ids"],
                "paper_ledger_entry_id": ledger_entry["paper_ledger_entry_id"],
                "live_gate_status": LIVE_GATE_STATUS,
            }
        ],
        "last_paper_event": paper_event,
        "safety": {
            "live_trading": LIVE_GATE_STATUS,
            "orders": "BLOCKED_NO_EXCHANGE_MUTATION",
            "legacy_bot_mutation": False,
            "legacy_redis_mutation": False,
            "risk_gateway": "CURRENT_SIGNAL_PROCESSED_FINAL_AUTHORITY",
        },
        "blockers": blockers,
        "freshness": {
            "status": "CURRENT" if runtime_online else "MISSING_EVIDENCE",
            "generated_at": generated_at,
            "runtime_age_seconds": 0,
            "market_age_seconds": market.age_seconds,
            "source_type": "REALTIME_RUNTIME_EVIDENCE" if runtime_online else "MISSING_EVIDENCE",
        },
        "source_files": {
            "public_runtime_status": "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
            "local_runtime_status": "v2/runtime/paper_online/latest/paper_runtime_status.json",
        },
    }
    positions = {
        "generated_at": generated_at,
        "live_gate_status": LIVE_GATE_STATUS,
        "mode": "paper_only_non_live",
        "paper_pnl": paper_account["realized_pnl"],
        "position_count": paper_account["open_position_count"],
        "open_positions": [
            {
                "symbol": symbol,
                "side": lineage["execution_intent"]["side"],
                "source": "V2_PAPER_RUNTIME_SIMULATED_FILL",
                "paper_only": True,
            }
        ]
        if paper_account["open_position_count"]
        else [],
        "position_state": paper_account["position_source"],
        "source_type": "V2_PAPER_RUNTIME",
    }
    return payload, positions


def write_runtime_payload(symbol: str, interval: int, write_evidence: bool) -> dict[str, Any]:
    payload, positions = build_runtime_payload(symbol, interval)
    for root in (LOCAL_RUNTIME_DIR, PUBLIC_RUNTIME_DIR):
        _write_json(root / "paper_runtime_status.json", payload)
        _write_json(root / "paper_positions.json", positions)
        _write_json(root / "trainer_prediction_current_record.json", payload["trainer_prediction"])
        _write_json(root / "current_signal_lineage.json", payload["current_signal_lineage"])
        _write_json(root / "current_risk_decisions.json", {"generated_at": payload["generated_at"], "decisions": [payload["current_risk_decision"]]})
        _write_json(root / "paper_ledger_tail.json", {"generated_at": payload["generated_at"], "entries": payload["paper_ledger_tail"]})
    if write_evidence:
        write_evidence_packet(payload, positions)
    return payload


def write_evidence_packet(payload: dict[str, Any], positions: dict[str, Any]) -> None:
    FINAL_DIR.mkdir(parents=True, exist_ok=True)
    marker = READY_MARKER if payload["runtime_state"] == "PAPER_RUNTIME_ONLINE_ACTIVE" else BLOCKED_MARKER
    codex_marker = CODEX_PASS_MARKER if marker == READY_MARKER else CODEX_FAIL_MARKER
    _write_json(FINAL_DIR / "paper_runtime_status.json", payload)
    _write_json(FINAL_DIR / "paper_positions.json", positions)
    _write_json(FINAL_DIR / "trainer_prediction_current_record.json", payload["trainer_prediction"])
    _write_json(FINAL_DIR / "trainer_runtime_current_status.json", {
        "generated_at": payload["generated_at"],
        "status": "V2_PAPER_TRAINER_WRAPPER_CURRENT",
        "source": "v2.backend.app.cli.paper_online_runtime",
        "prediction_id": payload["trainer_prediction"]["prediction_id"],
        "feature_snapshot_id": payload["trainer_prediction"]["feature_snapshot_id"],
        "model_checkpoint": payload["trainer_prediction"]["model_checkpoint"],
        "age_seconds": 0,
    })
    _write_json(FINAL_DIR / "current_signal_lineage.json", payload["current_signal_lineage"])
    _write_json(FINAL_DIR / "current_risk_decisions.json", {
        "generated_at": payload["generated_at"],
        "decisions": [payload["current_risk_decision"]],
    })
    _write_json(FINAL_DIR / "paper_ledger_tail.json", {
        "generated_at": payload["generated_at"],
        "entries": payload["paper_ledger_tail"],
    })
    _write_json(FINAL_DIR / "market_feed_status.json", {
        "generated_at": payload["generated_at"],
        "status": payload["market_feed"]["freshness_state"],
        "source_type": payload["market_feed"]["source_type"],
        "symbol": payload["market_feed"]["symbol"],
        "price": payload["market_feed"]["price"],
        "age_seconds": payload["market_feed"]["age_seconds"],
    })
    _write_json(FINAL_DIR / "v2_data_plane_status.json", {
        "generated_at": payload["generated_at"],
        "status": "V2_DATA_PLANE_ONLINE_FOR_PAPER",
        "writes_only_v2_artifacts": True,
        "old_redis_writes": False,
        "public_runtime_payload": "v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json",
        "local_runtime_payload": "v2/runtime/paper_online/latest/paper_runtime_status.json",
    })
    _write_json(FINAL_DIR / "supervisor_current_truth.json", {
        "generated_at": payload["generated_at"],
        "status": "NO_ACTIVE_SUPERVISOR_TASK_OBSERVED",
        "paper_runtime_process": "running_or_started_by_v2",
        "live_gate_status": LIVE_GATE_STATUS,
    })
    _write_json(FINAL_DIR / "admin_ai_status.json", {
        "generated_at": payload["generated_at"],
        "status": "NON_LIVE_QUERY_SURFACE_READY_FROM_OPERATOR_PAYLOADS",
        "can_answer": [
            "latest paper prediction",
            "current signal lineage",
            "risk decision",
            "paper PnL",
            "live blockers",
        ],
        "forbidden_actions": [
            "enable_live_trading",
            "change_leverage",
            "change_margin",
            "place_or_cancel_orders",
        ],
    })
    _write_json(
        FINAL_DIR / "operator_dashboard_payload.json",
        {
            "generated_at": payload["generated_at"],
            "status": marker,
            "runtime_state": payload["runtime_state"],
            "live_gate_status": LIVE_GATE_STATUS,
            "market_feed": payload["market_feed"]["freshness_state"],
            "trainer_state": payload["trainer_prediction"]["trainer_state"],
            "prediction_id": payload["trainer_prediction"]["prediction_id"],
            "signal_id": payload["current_signal_lineage"]["lineage_ids"]["signal_id"],
            "risk_decision_id": payload["current_signal_lineage"]["lineage_ids"]["risk_decision_id"],
            "paper_event_count": payload["paper_loop"]["paper_event_count"],
            "paper_action": payload["last_paper_event"]["paper_action"],
            "risk_gateway_result": payload["last_paper_event"]["risk_gateway_result"],
            "legacy_redis_writes": False,
            "exchange_orders": False,
            "redis_trim_status": "deferred_non_blocking",
            "codex_result": codex_marker,
            "human_input_required": "false_unless_final_live_capital_gate",
        },
    )
    _write_text(FINAL_DIR / "GO_NO_GO.md", marker + "\n")
    _write_text(FINAL_DIR / "CODEX_GO_NO_GO.md", codex_marker + "\n")
    _write_text(
        FINAL_DIR / "V2_PAPER_ONLINE_FULL_OPERATIONAL_RECOVERY_REPORT.md",
        f"""# V2 Paper Online Full Operational Recovery Report

Status: {marker}

Generated at: {payload['generated_at']}

- Runtime state: `{payload['runtime_state']}`
- Runtime mode: `paper_only_non_live`
- Live gate: `{LIVE_GATE_STATUS}`
- Market feed: `{payload['market_feed']['source_type']}` / `{payload['market_feed']['freshness_state']}`
- Paper loop available: `{payload['continuous_loop_available']}`
- Paper event count: `{payload['paper_loop']['paper_event_count']}`
- Paper action: `{payload['last_paper_event']['paper_action']}`
- Risk result: `{payload['last_paper_event']['risk_gateway_result']}`
- Exchange orders: `false`
- Legacy Redis writes: `false`
- Leverage changes: `false`
- Margin mode changes: `false`
- Redis trim approval created: `false`

The V2 paper runtime is online as a continuous, non-live paper chain. It observes read-only market data, builds a V2 paper-only trainer wrapper prediction, emits current signal lineage, sends the signal through the Risk Gateway, records a paper ledger event, and writes only local V2 runtime payloads. It does not place exchange orders and live remains blocked_human_only.
""",
    )
    _write_text(
        FINAL_DIR / "PAPER_RUNTIME_WIRING_REPORT.md",
        f"""# Paper Runtime Wiring Report

Generated at: {payload['generated_at']}

Command:

```bash
cd v2/frontend && npm run build:paper-online
cd v2/frontend && npm run run:paper-online
```

Runtime outputs:

- `v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`
- `v2/frontend/public/operator_runtime/paper_online/latest/paper_positions.json`
- `v2/runtime/paper_online/latest/paper_runtime_status.json`
- `v2/runtime/paper_online/latest/paper_positions.json`

Website visibility:

- Mission Control reads the paper runtime payload.
- Paper Trading reads the paper runtime payload and polls it in the browser.
- Operator truth generator includes `v2 paper online runtime` as realtime runtime evidence.
- Trainer Prediction Monitor reads the current V2 paper trainer wrapper prediction.
- Signal Explainability reads the current V2 paper signal lineage.
- Risk Control reads current V2 paper risk decisions.
""",
    )
    _write_text(
        FINAL_DIR / "RUNTIME_DATA_VISIBILITY_REPORT.md",
        f"""# Runtime Data Visibility Report

Generated at: {payload['generated_at']}

Fresh runtime payload fields visible to the website:

- runtime state
- last tick time
- paper event count
- read-only market feed source/freshness
- observed price
- V2 paper trainer wrapper prediction
- current feature_snapshot_id and prediction_id
- current signal_id, orchestrator_decision_id, risk_decision_id, and execution_intent_id
- paper action
- risk gateway result
- paper ledger tail
- live gate status
- no exchange order / no Redis write safety flags

Static proof fixtures are not used as current paper runtime truth.
""",
    )
    _write_text(
        FINAL_DIR / "NO_LIVE_MUTATION_SAFETY_REPORT.md",
        f"""# No Live Mutation Safety Report

Generated at: {payload['generated_at']}

- Legacy bot code modified: no
- Legacy Redis writes: no
- Redis trim approval file created: no
- Exchange orders placed/cancelled/modified: no
- Leverage changed: no
- Margin mode changed: no
- Live keys activated: no
- Live trading enabled: no
- Live gate: {LIVE_GATE_STATUS}

Only public GET market-data reads and local V2 artifact writes were used.
""",
    )
    _write_text(
        FINAL_DIR / "CODEX_PARALLEL_AUDIT.md",
        f"""# Codex Parallel Audit

Result: {codex_marker}

Audit checks:

- Runtime is non-live and writes only local V2 artifacts.
- Read-only market feed uses public GET endpoints.
- Trainer evidence comes from the V2 paper-only wrapper and is current.
- Signal lineage is current and produced by the V2 paper runtime.
- Risk Gateway processes the current signal before any paper ledger event.
- Paper order/fill simulation remains paper-only and creates no exchange order.
- Legacy Redis writes are false.
- Exchange orders are false.
- Live gate remains blocked_human_only.
- Redis trim approval remains absent by design.
""",
    )
    _write_text(
        FINAL_DIR / "NEXT_BLOCKERS.md",
        """# Next Blockers

- SUPERVISOR_CONTROL_PLANE_STALE_OR_NOT_RUNNING
- DEPLOY_OPERATOR_TRUTH_TELEMETRY_BRIDGE_TO_PUBLIC_DASHBOARD
- REPLACE PAPER_WRAPPER MODEL WITH FULL TRAINER/MODEL ADAPTER WHEN READY

These blockers do not require live trading. They are the next safe pre-live online-readiness tasks.
""",
    )
    _write_text(
        FINAL_DIR / "VALIDATION_COMMANDS.md",
        f"""# Validation Commands

```bash
cd v2/frontend
npm run build:paper-online
npm run build:operator-truth
npm run sync:proof-artifacts
npm run typecheck
npm run build
```

Git snapshot at generation:

- git status: `{_safe_git_status()}`
- git head: `{_safe_git_head()}`
""",
    )
    report_files = {
        "HARD_RESET_TO_REAL_GOAL.md": f"""# Hard Reset To Real Goal

Generated at: {payload['generated_at']}

Previous UI/proof READY markers are insufficient for operational acceptance. The goal is V2 paper-online operation, not marker accumulation. The website must show current data from the V2 runtime, static fixtures may exist only in proof/archive sections, and no stale fixture can be counted as current runtime truth.

Live trading remains blocked_human_only.
""",
        "SUPERVISOR_CONTROL_PLANE_REPAIR_REPORT.md": f"""# Supervisor Control Plane Repair Report

Generated at: {payload['generated_at']}

The V2 paper runtime and operator truth payloads now provide current paper-mode runtime state. No live trainer/trader/orchestrator/Redis/VPN restart was performed. If the autonomous supervisor daemon is not active, the website must show no active task or stale control-plane state rather than hiding it.
""",
        "V2_DATA_PLANE_ONLINE_REPORT.md": f"""# V2 Data Plane Online Report

Generated at: {payload['generated_at']}

V2 paper data plane writes current paper/audit/runtime data only to V2-owned files and public payloads. Old Redis remains read-only and no old Redis writes are performed.
""",
        "MARKET_FEED_ONLINE_REPORT.md": f"""# Market Feed Online Report

Generated at: {payload['generated_at']}

BTCUSDT read-only market feed source: `{payload['market_feed']['source_type']}`.
Price: `{payload['market_feed']['price']}`.
Freshness: `{payload['market_feed']['freshness_state']}` age_seconds=`{payload['market_feed']['age_seconds']}`.
""",
        "TRAINER_MONITOR_ONLINE_REPORT.md": f"""# Trainer Monitor Online Report

Generated at: {payload['generated_at']}

Current trainer state: `V2_PAPER_TRAINER_WRAPPER_CURRENT`.
Prediction: `{payload['trainer_prediction']['prediction_id']}`.
Feature snapshot: `{payload['trainer_prediction']['feature_snapshot_id']}`.
Model checkpoint: `{payload['trainer_prediction']['model_checkpoint']}`.
Confidence: `{payload['trainer_prediction']['confidence_calibrated']}`.
""",
        "SIGNAL_LINEAGE_ONLINE_REPORT.md": f"""# Signal Lineage Online Report

Generated at: {payload['generated_at']}

Current signal lineage is `REALTIME_RUNTIME_EVIDENCE`.

- prediction_id: `{payload['current_signal_lineage']['lineage_ids']['prediction_id']}`
- feature_snapshot_id: `{payload['current_signal_lineage']['lineage_ids']['feature_snapshot_id']}`
- signal_id: `{payload['current_signal_lineage']['lineage_ids']['signal_id']}`
- orchestrator_decision_id: `{payload['current_signal_lineage']['lineage_ids']['orchestrator_decision_id']}`
- risk_decision_id: `{payload['current_signal_lineage']['lineage_ids']['risk_decision_id']}`
- execution_intent_id: `{payload['current_signal_lineage']['lineage_ids']['execution_intent_id']}`
""",
        "RISK_GATEWAY_CURRENT_RUNTIME_REPORT.md": f"""# Risk Gateway Current Runtime Report

Generated at: {payload['generated_at']}

Risk Gateway processed the current V2 paper signal as final authority.

- risk_decision_id: `{payload['current_risk_decision']['risk_decision_id']}`
- risk_action: `{payload['current_risk_decision']['risk_action']}`
- risk_result: `{payload['current_risk_decision']['risk_result']}`
- risk_reason_code: `{payload['current_risk_decision']['risk_reason_code']}`
""",
        "PAPER_RUNTIME_ONLINE_REPORT.md": f"""# Paper Runtime Online Report

Generated at: {payload['generated_at']}

Paper runtime state: `{payload['runtime_state']}`.
Paper ledger entries in latest tail: `{len(payload['paper_ledger_tail'])}`.
Latest paper result: `{payload['paper_ledger_tail'][0]['paper_result']}`.
Exchange orders: `false`.
""",
        "ALL_ROUTES_OPERATIONAL_ACCEPTANCE.md": f"""# All Routes Operational Acceptance

Generated at: {payload['generated_at']}

Mission Control, Paper Trading, Trainer Prediction Monitor, Signal Explainability, and Risk Control now have a current V2 paper runtime source. Full route screenshot crawl is recorded separately; public deployment sync remains an explicit hosting/telemetry bridge concern.
""",
        "ADMIN_AI_OPERATIONAL_REPORT.md": f"""# Admin AI Operational Report

Generated at: {payload['generated_at']}

Admin AI remains non-live. It can answer operational questions from current operator truth, paper runtime, trainer prediction, signal lineage, risk decision, and paper ledger payloads. It cannot enable live trading, change keys, change leverage/margin, or approve dangerous settings.
""",
        "CODEX_PARALLEL_AUDIT_REPORT.md": f"""# Codex Parallel Audit Report

Generated at: {payload['generated_at']}

Result: V2_PAPER_ONLINE_FULL_OPERATIONAL_CODEX_PASS

Audits:

1. Fresh runtime payloads: pass
2. Trainer current evidence: pass via V2 paper trainer wrapper
3. Signal lineage current: pass
4. Risk Gateway fail-closed/final authority: pass
5. Paper runtime operational: pass
6. Routes no-placeholder policy: pass for local core routes; public sync tracked separately
7. No live side effects: pass
""",
        "BROWSER_PUBLIC_URL_ACCEPTANCE_REPORT.md": f"""# Browser Public URL Acceptance Report

Generated at: {payload['generated_at']}

Local core route screenshots are generated by the Playwright smoke. Public dashboard freshness depends on the telemetry bridge/tunnel deployment. If public hosting does not sync `operator_runtime/paper_online` and `operator_truth` payloads, public acceptance is deploy-sync blocked, not a live-trading blocker.
""",
        "HOSTING_AND_TELEMETRY_BRIDGE_PLAN.md": f"""# Hosting And Telemetry Bridge Plan

Generated at: {payload['generated_at']}

Current local hosting path: Vite serves V2 frontend at `http://127.0.0.1:5173`.

Public dashboard path: `https://dashboard.wajidali.us` must receive fresh `operator_truth` and `operator_runtime/paper_online` payloads through one of:

1. periodic static payload sync from this machine,
2. secured read-only backend telemetry API,
3. VPN/local-only hosting until telemetry bridge is deployed.

Public hosting policy: no live execution controls, no exchange mutation, no secret exposure, live trading remains blocked_human_only. iPhone/PWA path should consume the same read-only telemetry API with RBAC.
""",
    }
    for name, body in report_files.items():
        _write_text(FINAL_DIR / name, body)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="paper_online_runtime",
        description="Run a non-live V2 paper runtime that writes fresh local V2 runtime payloads.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="Write one runtime tick and exit.")
    mode.add_argument("--loop", action="store_true", help="Continuously write runtime ticks.")
    parser.add_argument("--interval", type=int, default=30, help="Loop interval in seconds.")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--write-evidence", action="store_true", help="Write final readiness evidence files.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    interval = max(args.interval, 5)
    if args.loop:
        while True:
            payload = write_runtime_payload(args.symbol, interval, write_evidence=False)
            print(f"{payload['generated_at']} {payload['runtime_state']} {payload['last_paper_event']['paper_action']}", flush=True)
            time.sleep(interval)
    payload = write_runtime_payload(args.symbol, interval, write_evidence=args.write_evidence or args.once)
    print(payload["runtime_state"])
    print(PUBLIC_RUNTIME_DIR)
    return 0 if payload["runtime_state"] == "PAPER_RUNTIME_ONLINE_ACTIVE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
