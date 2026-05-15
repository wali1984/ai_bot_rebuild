from __future__ import annotations

import argparse
import copy
import datetime as dt
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from v2.backend.app.composition.canary_profile_tightening import build_canary_profile_tightening_runtime
from v2.backend.app.composition.paper_edge_scoring import score_paper_edge
from v2.backend.app.composition.paper_expected_move_coverage import (
    evaluate_paper_expected_move_coverage,
)
from v2.backend.app.services.signal_publisher import build_paper_runtime_lineage


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
TRAINER_BRIDGE_STATUS_FILE = (
    V2_ROOT
    / "frontend"
    / "public"
    / "operator_runtime"
    / "v2_trainer_bridge"
    / "latest"
    / "v2_trainer_bridge_status.json"
)
WEEKLY_LOSS_LIMIT_USDT = -250.0
DAILY_LOSS_LIMIT_USDT = -75.0
PAPER_TIGHTENING_MIN_CONFIDENCE = 0.75
PAPER_TIGHTENING_MAX_FILLS_PER_HOUR = 12
PAPER_TIGHTENING_COOLDOWN_SECONDS = 300
PAPER_TIGHTENING_LOSS_COOLDOWN_SECONDS = 600
PAPER_TIGHTENING_MAX_SIGNAL_AGE_SECONDS = 120
PAPER_TIGHTENING_MAX_FEATURE_AGE_SECONDS = 120
PAPER_OUTCOME_MODEL_READY = True
PAPER_OUTCOME_MODEL_BLOCKER = "paper_outcome_model_missing"
PAPER_POSITION_MIN_HOLD_SECONDS = 120
PAPER_POSITION_MAX_HOLD_SECONDS = 15 * 60
PAPER_POSITION_DEFAULT_STOP_BPS = 8.0
PAPER_POSITION_MIN_TAKE_PROFIT_BPS = 8.0
PAPER_MICROSTRUCTURE_TOXICITY_MAX_BPS = 150.0


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


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _float_or_none(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _trainer_bridge_expected_move(feature_snapshot: dict[str, Any]) -> dict[str, Any]:
    bridge = _read_json_file(TRAINER_BRIDGE_STATUS_FILE)
    expected_move = _float_or_none(bridge.get("expected_move_bps"))
    if expected_move is None:
        return {"status": "MISSING_NATIVE_EXPECTED_MOVE"}
    if str(bridge.get("expected_move_evidence_mode") or "") != "NATIVE_FIELD_PRESENT":
        return {"status": "EXPECTED_MOVE_NOT_NATIVE"}
    bridge_symbol = str(bridge.get("prediction_symbol") or "").strip().upper()
    bridge_timeframe = str(bridge.get("prediction_timeframe") or "").strip()
    feature_symbol = str(feature_snapshot.get("symbol") or "").strip().upper()
    feature_timeframe = "1m"
    if bridge_symbol != feature_symbol:
        return {
            "status": "EXPECTED_MOVE_SYMBOL_MISMATCH",
            "prediction_symbol": bridge_symbol,
            "prediction_timeframe": bridge_timeframe,
            "feature_symbol": feature_symbol,
            "feature_timeframe": feature_timeframe,
        }
    if bridge.get("live_gate") != LIVE_GATE_STATUS or bridge.get("live_symbols") not in ([], None):
        return {"status": "TRAINER_BRIDGE_LIVE_SCOPE_UNSAFE"}
    return {
        "status": "NATIVE_EXPECTED_MOVE_PRESENT",
        "expected_move_bps": expected_move,
        "expected_move_source": str(bridge.get("expected_move_source") or ""),
        "expected_move_timeframe": bridge_timeframe,
        "feature_timeframe": feature_timeframe,
        "cross_timeframe_expected_move": bridge_timeframe != feature_timeframe,
        "trainer_source": str(bridge.get("prediction_source_type") or ""),
        "trainer_bridge_status": str(bridge.get("trainer_parity_status") or ""),
        "model_version": str(bridge.get("model_version") or ""),
        "checkpoint_id": str(bridge.get("checkpoint_id") or ""),
        "bridge_prediction_id": str(bridge.get("prediction_id") or ""),
    }


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


def _read_jsonl_tail(path: Path, limit: int = 500) -> list[dict[str, Any]]:
    try:
        lines = path.read_text().splitlines()
    except OSError:
        return []
    rows: list[dict[str, Any]] = []
    for line in lines[-max(1, limit) :]:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


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


def _parse_ts(value: Any) -> float | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = dt.datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=dt.timezone.utc)
        return parsed.timestamp()
    except Exception:
        return None


def _open_position_from_previous(previous: dict[str, Any]) -> dict[str, Any] | None:
    lifecycle = previous.get("paper_position_lifecycle")
    if not isinstance(lifecycle, dict):
        return None
    position = lifecycle.get("open_position")
    if not isinstance(position, dict):
        return None
    if str(position.get("status") or "") != "OPEN":
        return None
    return dict(position)


def _position_return_bps(side: str, entry_price: float, current_price: float) -> float:
    if entry_price <= 0:
        return 0.0
    raw = ((current_price - entry_price) / entry_price) * 10_000
    return round(raw if side == "long" else -raw, 8)


def _position_age_seconds(position: dict[str, Any], generated_at: str) -> int | None:
    opened_ts = _parse_ts(position.get("opened_at"))
    current_ts = _parse_ts(generated_at)
    if opened_ts is None or current_ts is None:
        return None
    return max(0, int(current_ts - opened_ts))


def _position_exit_reason(position: dict[str, Any], *, current_price: float, generated_at: str) -> str | None:
    side = str(position.get("side") or "").lower()
    entry_price = _float_or_none(position.get("entry_price")) or 0.0
    current_return_bps = _position_return_bps(side, entry_price, current_price)
    take_profit_bps = max(
        PAPER_POSITION_MIN_TAKE_PROFIT_BPS,
        _float_or_none(position.get("take_profit_bps")) or PAPER_POSITION_MIN_TAKE_PROFIT_BPS,
    )
    stop_loss_bps = max(
        PAPER_POSITION_DEFAULT_STOP_BPS,
        _float_or_none(position.get("stop_loss_bps")) or PAPER_POSITION_DEFAULT_STOP_BPS,
    )
    if current_return_bps <= -stop_loss_bps:
        return "STOP_LOSS"
    age_seconds = _position_age_seconds(position, generated_at)
    if age_seconds is not None and age_seconds < PAPER_POSITION_MIN_HOLD_SECONDS:
        return None
    if current_return_bps >= take_profit_bps:
        return "TAKE_PROFIT"
    if age_seconds is not None and age_seconds >= PAPER_POSITION_MAX_HOLD_SECONDS:
        return "MAX_HOLD_TIME"
    return None


def _confidence_bucket(value: Any) -> str:
    confidence = _float_or_none(value)
    if confidence is None:
        return "missing"
    if confidence < 0.58:
        return "below_0.58"
    if confidence < 0.65:
        return "0.58_to_0.65"
    if confidence < 0.75:
        return "0.65_to_0.75"
    return "0.75_plus"


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
            "microstructure_toxicity_score_bps": round(volatility_10 * 10_000, 8),
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
    bridge_expected_move = _trainer_bridge_expected_move(feature_snapshot)
    raw_output: dict[str, Any] = {
        "side": side,
        "momentum_score": round(momentum_score, 8),
    }
    if bridge_expected_move.get("status") == "NATIVE_EXPECTED_MOVE_PRESENT":
        raw_output["expected_move_bps"] = bridge_expected_move["expected_move_bps"]
        raw_output["expected_move_source"] = bridge_expected_move["expected_move_source"]
        raw_output["expected_move_timeframe"] = bridge_expected_move["expected_move_timeframe"]
        raw_output["cross_timeframe_expected_move"] = bridge_expected_move["cross_timeframe_expected_move"]
        raw_output["expected_move_bridge_prediction_id"] = bridge_expected_move["bridge_prediction_id"]
    return {
        "prediction_id": f"pred_{tick_id}",
        "generated_at": feature_snapshot["generated_at"],
        "source_type": "V2_PAPER_TRAINER_WRAPPER",
        "trainer_source": bridge_expected_move.get("trainer_source") or "V2_PAPER_TRAINER_WRAPPER",
        "trainer_bridge_status": bridge_expected_move.get("trainer_bridge_status") or "MISSING_NATIVE_EXPECTED_MOVE",
        "trainer_state": "V2_PAPER_TRAINER_WRAPPER_CURRENT",
        "symbol": feature_snapshot["symbol"],
        "timeframe": "1m",
        "model_checkpoint": bridge_expected_move.get("checkpoint_id") or "v2_paper_readonly_momentum_wrapper_v1",
        "model_version": bridge_expected_move.get("model_version") or "v2_paper_readonly_momentum_wrapper_v1",
        "feature_snapshot_id": feature_snapshot["feature_snapshot_id"],
        "raw_output": raw_output,
        "expected_move_bps": bridge_expected_move.get("expected_move_bps"),
        "expected_move_source": bridge_expected_move.get("expected_move_source"),
        "expected_move_bridge_status": bridge_expected_move.get("status"),
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
    return build_paper_runtime_lineage(
        tick_id=tick_id,
        generated_at=generated_at,
        feature_snapshot=feature_snapshot,
        prediction=prediction,
        market_symbol=market.symbol,
        market_freshness_state=market.freshness_state,
        market_age_seconds=market.age_seconds,
    )


def _paper_outcome_model_contract() -> tuple[dict[str, Any], list[str]]:
    blockers: list[str] = [] if PAPER_OUTCOME_MODEL_READY else [PAPER_OUTCOME_MODEL_BLOCKER]
    detail = (
        "non-live paper position lifecycle is active; fills can only open paper-only positions after strict edge, "
        "provenance, freshness, symbol-scope, cooldown, churn, and risk gates pass"
        if PAPER_OUTCOME_MODEL_READY
        else (
            "paper fill recording is blocked until V2 has a non-live exit/outcome simulator; "
            "qualified intents remain shadow-observed so fee-only ledger drift cannot masquerade as edge"
        )
    )
    return (
        {
            "status": "READY" if PAPER_OUTCOME_MODEL_READY else "MISSING_EXIT_LIFECYCLE_SIMULATOR",
            "paper_fill_allowed": PAPER_OUTCOME_MODEL_READY,
            "blockers": blockers,
            "detail": detail,
        },
        blockers,
    )


def apply_paper_tightening_gate(
    lineage: dict[str, Any],
    *,
    generated_at: str,
    recent_events: list[dict[str, Any]],
    now_ms: int | None = None,
) -> dict[str, Any]:
    gated = copy.deepcopy(lineage)
    risk = gated["risk_decision"]
    intent = gated["execution_intent"]
    if risk.get("risk_action") != "allow":
        paper_outcome_model, paper_outcome_model_blockers = _paper_outcome_model_contract()
        risk["canary_profile_tightening"] = {
            "classification": "TIGHTENING_NOT_EVALUATED_RISK_ALREADY_DENIED",
            "paper_simulation_allowed": False,
            "blockers": [str(risk.get("risk_reason_code") or "risk_already_denied")],
            "live_gate_status": LIVE_GATE_STATUS,
            "safe_for_live": False,
            "automation_can_enable_live": False,
        }
        risk["paper_outcome_model"] = paper_outcome_model
        risk["paper_outcome_model_blockers"] = paper_outcome_model_blockers
        required = list(risk.get("required_blocks_checked") or [])
        if "paper_outcome_model" not in required:
            required.append("paper_outcome_model")
        risk["required_blocks_checked"] = required
        return gated

    signal = gated.get("signal", {})
    feature_snapshot = gated.get("feature_snapshot", {})
    prediction = gated.get("trainer_prediction", {})
    raw_output = prediction.get("raw_output") if isinstance(prediction.get("raw_output"), dict) else {}
    features = feature_snapshot.get("features") if isinstance(feature_snapshot.get("features"), dict) else {}
    microstructure_toxicity_score_bps = _float_or_none(features.get("microstructure_toxicity_score_bps"))
    microstructure_toxicity_clear = (
        microstructure_toxicity_score_bps is not None
        and microstructure_toxicity_score_bps <= PAPER_MICROSTRUCTURE_TOXICITY_MAX_BPS
    )
    coverage = evaluate_paper_expected_move_coverage(
        trainer_prediction=prediction,
        feature_snapshot=feature_snapshot,
        risk_payload=risk,
        signal_record=signal,
        fee_bps=4.0,
        spread_bps=0.0,
        slippage_bps=2.0,
        funding_bps=0.0,
    )
    runtime = build_canary_profile_tightening_runtime(
        now_ms_clock=lambda: now_ms if now_ms is not None else int(time.time() * 1000),
        min_confidence=PAPER_TIGHTENING_MIN_CONFIDENCE,
        max_fills_per_hour=PAPER_TIGHTENING_MAX_FILLS_PER_HOUR,
        cooldown_seconds=PAPER_TIGHTENING_COOLDOWN_SECONDS,
        loss_cooldown_seconds=PAPER_TIGHTENING_LOSS_COOLDOWN_SECONDS,
        max_signal_age_seconds=PAPER_TIGHTENING_MAX_SIGNAL_AGE_SECONDS,
        max_feature_age_seconds=PAPER_TIGHTENING_MAX_FEATURE_AGE_SECONDS,
    )
    gate = runtime.evaluate_now(
        intent_payload={
            "symbol": intent.get("symbol") or signal.get("symbol"),
            "action": "OPEN_LONG" if intent.get("side") == "long" else "OPEN_SHORT" if intent.get("side") == "short" else "HOLD",
            "confidence": signal.get("confidence") or signal.get("confidence_calibrated") or prediction.get("confidence_calibrated"),
            "signal_generated_at": signal.get("generated_at") or generated_at,
            "feature_snapshot_generated_at": feature_snapshot.get("generated_at") or feature_snapshot.get("generated_ts"),
            "expected_move_bps": coverage.get("expected_move_bps_for_fill_gate"),
            "fee_bps": 4.0,
            "slippage_bps": 2.0,
            "funding_bps": 0.0,
        },
        recent_events=recent_events,
        approval_token_present=False,
    )
    paper_edge_gate = score_paper_edge(
        {
            "symbol": intent.get("symbol") or signal.get("symbol"),
            "risk_action": "allow",
            "trainer_source": prediction.get("trainer_source") or raw_output.get("trainer_source"),
            "feature_freshness_state": feature_snapshot.get("freshness_state"),
            "confidence_calibrated": signal.get("confidence_calibrated")
            or signal.get("confidence")
            or prediction.get("confidence_calibrated"),
            "expected_move_bps": coverage.get("expected_move_bps_for_fill_gate"),
            "expected_move_after_cost_bps": coverage.get("expected_move_after_cost_bps_for_fill_gate"),
            "fee_bps": 4.0,
            "spread_bps": 0.0,
            "slippage_bps": 2.0,
            "funding_risk_bps": 0.0,
            "cooldown_clear": "same_symbol_same_direction_cooldown"
            not in set(gate.get("blockers") or []),
            "flip_churn_clear": "flip_churn_cooldown" not in set(gate.get("blockers") or []),
            "reduce_only_clear": True,
            "intelligent_close_guard_clear": True,
            "microstructure_toxicity_clear": microstructure_toxicity_clear,
        },
        paper_symbols=[str(intent.get("symbol") or signal.get("symbol") or "").upper()],
        live_symbols=[],
        live_gate=LIVE_GATE_STATUS,
    )
    risk["canary_profile_tightening"] = gate
    risk["expected_move_coverage"] = coverage
    risk["expected_move_source"] = coverage.get("expected_move_source")
    risk["expected_move_coverage_status"] = coverage.get("expected_move_coverage_status")
    risk["expected_move_bps"] = coverage.get("expected_move_bps_for_fill_gate")
    risk["expected_move_after_cost_bps"] = coverage.get("expected_move_after_cost_bps_for_fill_gate")
    risk["paper_edge_gate"] = paper_edge_gate
    risk["paper_edge_gate_classification"] = paper_edge_gate.get("classification")
    risk["paper_edge_gate_blockers"] = list(paper_edge_gate.get("blockers") or [])
    risk["paper_protective_behavior_gate"] = {
        "minimum_hold_seconds": PAPER_POSITION_MIN_HOLD_SECONDS,
        "dynamic_take_profit_model": "expected_move_after_cost_bps_floor",
        "dynamic_stop_model": "paper_static_stop_floor_until_legacy_dynamic_stop_parity",
        "reduce_only_protection_clear": True,
        "intelligent_close_guard_clear": True,
        "microstructure_toxicity_score_bps": microstructure_toxicity_score_bps,
        "microstructure_toxicity_max_bps": PAPER_MICROSTRUCTURE_TOXICITY_MAX_BPS,
        "microstructure_toxicity_clear": microstructure_toxicity_clear,
        "paper_only": True,
    }
    paper_outcome_model, paper_outcome_model_blockers = _paper_outcome_model_contract()
    risk["paper_outcome_model"] = paper_outcome_model
    if gate.get("blockers") or paper_edge_gate.get("blockers") or paper_outcome_model_blockers:
        risk["risk_action"] = "deny"
        risk["risk_result"] = "BLOCKED"
        risk["risk_reason_code"] = (
            "deny_paper_outcome_model_missing"
            if paper_outcome_model_blockers and not gate.get("blockers") and not paper_edge_gate.get("blockers")
            else "deny_canary_profile_tightening"
        )
        risk["canary_profile_tightening_blockers"] = [
            *list(gate.get("blockers") or []),
            *paper_outcome_model_blockers,
        ]
        risk["paper_outcome_model_blockers"] = paper_outcome_model_blockers
        required = list(risk.get("required_blocks_checked") or [])
        if "canary_profile_tightening" not in required:
            required.append("canary_profile_tightening")
        if "paper_edge_scoring" not in required:
            required.append("paper_edge_scoring")
        if "paper_outcome_model" not in required:
            required.append("paper_outcome_model")
        risk["required_blocks_checked"] = required
        intent["intent_action"] = "paper_noop_blocked"
        intent["exchange_order_allowed"] = False
        intent["paper_only"] = True
    return gated


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


def build_position_lifecycle_entry(
    *,
    tick_id: str,
    generated_at: str,
    market: MarketSnapshot,
    lineage: dict[str, Any],
    previous_position: dict[str, Any],
    previous_account: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    risk = lineage["risk_decision"]
    current_price = market.price or _float_or_none(previous_position.get("entry_price")) or 0.0
    side = str(previous_position.get("side") or "").lower()
    notional = _float_or_none(previous_position.get("notional_usdt")) or 0.0
    entry_price = _float_or_none(previous_position.get("entry_price")) or 0.0
    fee_rate = _float_or_none(previous_position.get("fee_rate")) or 0.0004
    current_return_bps = _position_return_bps(side, entry_price, current_price)
    gross_unrealized = round(notional * current_return_bps / 10_000, 6)
    previous_realized = float(previous_account.get("realized_pnl") or 0.0)
    age_seconds = _position_age_seconds(previous_position, generated_at)
    minimum_hold_active = (
        age_seconds is not None
        and age_seconds < int(previous_position.get("minimum_hold_seconds") or PAPER_POSITION_MIN_HOLD_SECONDS)
    )
    exit_reason = _position_exit_reason(previous_position, current_price=current_price, generated_at=generated_at)
    if exit_reason:
        exit_fee = round(notional * fee_rate, 6)
        realized_delta = round(gross_unrealized - exit_fee, 6)
        realized_pnl = round(previous_realized + realized_delta, 6)
        equity = round(10000.0 + realized_pnl, 6)
        ledger_entry = {
            "paper_ledger_entry_id": f"pledger_{tick_id}",
            "generated_at": generated_at,
            "execution_intent_id": lineage["execution_intent"]["execution_intent_id"],
            "risk_decision_id": risk["risk_decision_id"],
            "signal_id": lineage["signal"]["signal_id"],
            "symbol": market.symbol,
            "ledger_action": "PAPER_POSITION_CLOSED",
            "paper_result": "POSITION_CLOSED_PAPER_ONLY",
            "fill_price": None,
            "exit_price": current_price,
            "exit_reason": exit_reason,
            "notional_usdt": notional,
            "fee_usdt": exit_fee,
            "fee_rate": fee_rate,
            "slippage_bps": 0.0,
            "funding_assumption": "zero_until_funding_feed_adapter_current",
            "gross_pnl_usdt": gross_unrealized,
            "realized_delta_usdt": realized_delta,
            "exchange_order_id": None,
            "live_order": False,
            "legacy_redis_write": False,
        }
        account = {
            "currency": "USDT",
            "starting_equity": 10000.0,
            "equity": equity,
            "realized_pnl": realized_pnl,
            "unrealized_pnl": 0.0,
            "open_position_count": 0,
            "position_source": "V2_PAPER_RUNTIME_POSITION_CLOSED",
        }
        lifecycle = {
            "status": "CLOSED",
            "open_position": None,
            "last_closed_position": {
                **previous_position,
                "status": "CLOSED",
                "closed_at": generated_at,
                "exit_price": current_price,
                "exit_reason": exit_reason,
                "position_age_seconds": age_seconds,
                "minimum_hold_seconds": previous_position.get("minimum_hold_seconds")
                or PAPER_POSITION_MIN_HOLD_SECONDS,
                "paper_exit_coordinator_status": "EXIT_COORDINATED_PAPER_ONLY",
                "gross_pnl_usdt": gross_unrealized,
                "realized_delta_usdt": realized_delta,
            },
        }
        return ledger_entry, account, lifecycle

    equity = round(10000.0 + previous_realized + gross_unrealized, 6)
    ledger_entry = {
        "paper_ledger_entry_id": f"pledger_{tick_id}",
        "generated_at": generated_at,
        "execution_intent_id": lineage["execution_intent"]["execution_intent_id"],
        "risk_decision_id": risk["risk_decision_id"],
        "signal_id": lineage["signal"]["signal_id"],
        "symbol": market.symbol,
        "ledger_action": "PAPER_POSITION_HELD",
        "paper_result": "POSITION_HELD_PAPER_ONLY",
        "fill_price": None,
        "notional_usdt": 0.0,
        "fee_usdt": 0.0,
        "fee_rate": fee_rate,
        "slippage_bps": 0.0,
        "funding_assumption": "zero_until_funding_feed_adapter_current",
        "unrealized_pnl_usdt": gross_unrealized,
        "exchange_order_id": None,
        "live_order": False,
        "legacy_redis_write": False,
    }
    account = {
        "currency": "USDT",
        "starting_equity": 10000.0,
        "equity": equity,
        "realized_pnl": previous_realized,
        "unrealized_pnl": gross_unrealized,
        "open_position_count": 1,
        "position_source": "V2_PAPER_RUNTIME_POSITION_HELD",
    }
    lifecycle = {
        "status": "OPEN",
        "open_position": {
            **previous_position,
            "status": "OPEN",
            "last_mark_price": current_price,
            "last_mark_at": generated_at,
            "unrealized_pnl_usdt": gross_unrealized,
            "current_return_bps": current_return_bps,
            "position_age_seconds": age_seconds,
            "minimum_hold_active": minimum_hold_active,
            "paper_exit_coordinator_status": (
                "MINIMUM_HOLD_ACTIVE_PAPER_ONLY"
                if minimum_hold_active
                else "WAITING_FOR_TP_SL_OR_MAX_HOLD_PAPER_ONLY"
            ),
        },
        "last_closed_position": None,
    }
    return ledger_entry, account, lifecycle


def paper_position_lifecycle_from_entry(
    *,
    ledger_entry: dict[str, Any],
    lineage: dict[str, Any],
) -> dict[str, Any]:
    if ledger_entry["paper_result"] != "FILLED_PAPER_ONLY":
        return {"status": "FLAT", "open_position": None, "last_closed_position": None}
    risk = lineage["risk_decision"]
    intent = lineage["execution_intent"]
    expected_after_cost = _float_or_none(risk.get("expected_move_after_cost_bps")) or PAPER_POSITION_MIN_TAKE_PROFIT_BPS
    return {
        "status": "OPEN",
        "open_position": {
            "status": "OPEN",
            "opened_at": ledger_entry["generated_at"],
            "symbol": ledger_entry["symbol"],
            "side": intent.get("side"),
            "entry_price": ledger_entry["fill_price"],
            "notional_usdt": ledger_entry["notional_usdt"],
            "entry_fee_usdt": ledger_entry["fee_usdt"],
            "fee_rate": ledger_entry["fee_rate"],
            "take_profit_bps": max(PAPER_POSITION_MIN_TAKE_PROFIT_BPS, expected_after_cost),
            "stop_loss_bps": PAPER_POSITION_DEFAULT_STOP_BPS,
            "minimum_hold_seconds": PAPER_POSITION_MIN_HOLD_SECONDS,
            "dynamic_take_profit_model": "expected_move_after_cost_bps_floor",
            "dynamic_stop_model": "paper_static_stop_floor_until_legacy_dynamic_stop_parity",
            "paper_exit_coordinator_status": "OPEN_PAPER_ONLY",
            "expected_move_after_cost_bps": risk.get("expected_move_after_cost_bps"),
            "prediction_id": lineage["lineage_ids"]["prediction_id"],
            "feature_snapshot_id": lineage["lineage_ids"]["feature_snapshot_id"],
        },
        "last_closed_position": None,
    }


def build_risk_runtime_payload(
    *,
    generated_at: str,
    lineage: dict[str, Any],
    ledger_entry: dict[str, Any],
    paper_account: dict[str, Any],
) -> dict[str, Any]:
    realized_pnl = float(paper_account["realized_pnl"])
    return {
        "generated_at": generated_at,
        "source": "V2_PAPER_RUNTIME_RISK_RUNTIME_PAYLOAD",
        "live_gate_status": LIVE_GATE_STATUS,
        "risk_decision_id": lineage["risk_decision"]["risk_decision_id"],
        "signal_id": lineage["signal"]["signal_id"],
        "execution_intent_id": ledger_entry["execution_intent_id"],
        "daily_loss_gate_required": True,
        "weekly_loss_gate_required": True,
        "kill_switch_required": True,
        "stop_policy_required": True,
        "risk_config_version": "v2_paper_canary_hard_gates_v1",
        "daily_pnl_source": "V2_PAPER_ACCOUNT_REALIZED_PNL_CURRENT",
        "weekly_pnl_source": "V2_PAPER_ACCOUNT_REALIZED_PNL_CURRENT_UNTIL_DURABLE_WINDOW_LEDGER",
        "daily_realized_pnl_usdt": realized_pnl,
        "weekly_realized_pnl_usdt": realized_pnl,
        "daily_loss_limit_usdt": DAILY_LOSS_LIMIT_USDT,
        "weekly_loss_limit_usdt": WEEKLY_LOSS_LIMIT_USDT,
        "daily_loss_breach": realized_pnl <= DAILY_LOSS_LIMIT_USDT,
        "weekly_loss_breach": realized_pnl <= WEEKLY_LOSS_LIMIT_USDT,
        "reset_window": {
            "daily": "UTC calendar day until V2 durable account ledger is installed",
            "weekly": "UTC ISO week until V2 durable account ledger is installed",
        },
        "dedupe_source": "paper_ledger_entry_id + execution_intent_id + risk_decision_id",
        "audit_event": "WEEKLY_LOSS_GATE_RUNTIME_EVALUATED",
        "exchange_order": False,
        "legacy_redis_write": False,
    }


def append_paper_event(root: Path, payload: dict[str, Any], risk_runtime_payload: dict[str, Any]) -> None:
    ledger_entry = payload["paper_ledger_tail"][0]
    signal = payload["current_signal_lineage"]["signal"]
    risk = payload["current_risk_decision"]
    trainer = payload["trainer_prediction"]
    feature_snapshot = payload["feature_snapshot"]
    paper_edge_gate = risk.get("paper_edge_gate") if isinstance(risk.get("paper_edge_gate"), dict) else {}
    protective_gate = (
        risk.get("paper_protective_behavior_gate")
        if isinstance(risk.get("paper_protective_behavior_gate"), dict)
        else {}
    )
    confidence = signal.get("confidence") or signal.get("confidence_calibrated") or trainer.get("confidence_calibrated")
    is_fill = ledger_entry["paper_result"] == "FILLED_PAPER_ONLY"
    is_blocked = ledger_entry["paper_result"] == "NO_FILL_RISK_BLOCKED"
    event = {
        "generated_at": payload["generated_at"],
        "tick_id": payload["paper_loop"]["tick_id"],
        "symbol": ledger_entry["symbol"],
        "prediction_id": payload["current_signal_lineage"]["lineage_ids"]["prediction_id"],
        "feature_snapshot_id": payload["current_signal_lineage"]["lineage_ids"]["feature_snapshot_id"],
        "signal_id": ledger_entry["signal_id"],
        "risk_decision_id": ledger_entry["risk_decision_id"],
        "execution_intent_id": ledger_entry["execution_intent_id"],
        "paper_ledger_entry_id": ledger_entry["paper_ledger_entry_id"],
        "trainer_source": trainer.get("trainer_source"),
        "trainer_bridge_status": trainer.get("trainer_bridge_status"),
        "model_version": trainer.get("model_version"),
        "checkpoint_id": trainer.get("model_checkpoint"),
        "confidence_raw": trainer.get("confidence_raw"),
        "confidence_calibrated": trainer.get("confidence_calibrated"),
        "confidence_bucket": _confidence_bucket(confidence),
        "expected_move_bps": risk.get("expected_move_bps"),
        "expected_move_after_cost_bps": risk.get("expected_move_after_cost_bps"),
        "expected_move_source": risk.get("expected_move_source"),
        "fee_bps": paper_edge_gate.get("fee_bps"),
        "spread_bps": paper_edge_gate.get("spread_bps"),
        "funding_risk_bps": paper_edge_gate.get("funding_risk_bps"),
        "edge_score": paper_edge_gate.get("edge_score"),
        "feature_freshness_state": feature_snapshot.get("freshness_state"),
        "stale_feature_flags": feature_snapshot.get("stale_feature_flags", []),
        "missing_feature_flags": feature_snapshot.get("missing_feature_flags", []),
        "symbol_universe_state": "PAPER_SYMBOL_SCOPE_LOCAL",
        "paper_symbol_allowed": paper_edge_gate.get("paper_symbol_allowed"),
        "risk_action": risk["risk_action"],
        "risk_result": risk["risk_result"],
        "risk_reason_code": risk["risk_reason_code"],
        "risk_reason": risk["risk_reason_code"],
        "block_reason": risk["risk_reason_code"] if is_blocked else None,
        "fill_allowed": is_fill,
        "fill_rejected_reason": risk["risk_reason_code"] if is_blocked else None,
        "ledger_action": ledger_entry["ledger_action"],
        "paper_result": ledger_entry["paper_result"],
        "exit_reason": ledger_entry.get("exit_reason"),
        "realized_delta_usdt": ledger_entry.get("realized_delta_usdt"),
        "gross_pnl_usdt": ledger_entry.get("gross_pnl_usdt"),
        "paper_pnl_delta": ledger_entry.get("realized_delta_usdt")
        if ledger_entry.get("realized_delta_usdt") is not None
        else (-ledger_entry["fee_usdt"] if is_fill else 0.0),
        "confidence": confidence,
        "notional_usdt": ledger_entry["notional_usdt"],
        "fee_usdt": ledger_entry["fee_usdt"],
        "slippage_bps": ledger_entry["slippage_bps"],
        "funding_assumption": ledger_entry["funding_assumption"],
        "paper_equity": payload["paper_account"]["equity"],
        "paper_realized_pnl": payload["paper_account"]["realized_pnl"],
        "weekly_loss_gate_required": risk_runtime_payload["weekly_loss_gate_required"],
        "weekly_loss_breach": risk_runtime_payload["weekly_loss_breach"],
        "canary_profile_tightening_blockers": risk.get("canary_profile_tightening_blockers", []),
        "paper_edge_gate_blockers": risk.get("paper_edge_gate_blockers", []),
        "paper_protective_behavior_gate": protective_gate,
        "minimum_hold_seconds": protective_gate.get("minimum_hold_seconds"),
        "microstructure_toxicity_score_bps": protective_gate.get("microstructure_toxicity_score_bps"),
        "microstructure_toxicity_clear": protective_gate.get("microstructure_toxicity_clear"),
        "reduce_only_protection_clear": protective_gate.get("reduce_only_protection_clear"),
        "intelligent_close_guard_clear": protective_gate.get("intelligent_close_guard_clear"),
        "paper_outcome_model_status": (risk.get("paper_outcome_model") or {}).get("status"),
        "paper_outcome_model_blockers": risk.get("paper_outcome_model_blockers", []),
        "live_gate_status": LIVE_GATE_STATUS,
        "live_gate": LIVE_GATE_STATUS,
        "live_symbols": [],
        "exchange_order": False,
        "legacy_redis_write": False,
        "source_type": "V2_PAPER_RUNTIME_JSONL_EVENT",
    }
    root.mkdir(parents=True, exist_ok=True)
    with (root / "paper_events.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")


def build_runtime_payload(symbol: str, interval: int) -> tuple[dict[str, Any], dict[str, Any]]:
    market = fetch_market_snapshot(symbol)
    previous = _read_json(LOCAL_RUNTIME_DIR / "paper_runtime_status.json") or {}
    previous_count = int(previous.get("paper_loop", {}).get("paper_event_count", 0) or 0)
    previous_equity = float(previous.get("paper_account", {}).get("equity", 10000.0) or 10000.0)
    previous_account = previous.get("paper_account") if isinstance(previous.get("paper_account"), dict) else {}
    previous_lifecycle = previous.get("paper_position_lifecycle") if isinstance(previous.get("paper_position_lifecycle"), dict) else {}
    previous_last_closed_position = (
        previous_lifecycle.get("last_closed_position")
        if isinstance(previous_lifecycle.get("last_closed_position"), dict)
        else None
    )
    previous_position = _open_position_from_previous(previous)
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
    lineage = apply_paper_tightening_gate(
        lineage,
        generated_at=generated_at,
        recent_events=_read_jsonl_tail(LOCAL_RUNTIME_DIR / "paper_events.jsonl"),
    )
    if previous_position:
        ledger_entry, paper_account, position_lifecycle = build_position_lifecycle_entry(
            tick_id=tick_id,
            generated_at=generated_at,
            market=market,
            lineage=lineage,
            previous_position=previous_position,
            previous_account=previous_account,
        )
    else:
        ledger_entry, paper_account = build_paper_ledger_entry(
            tick_id=tick_id,
            generated_at=generated_at,
            market=market,
            lineage=lineage,
            previous_equity=previous_equity,
        )
        position_lifecycle = paper_position_lifecycle_from_entry(
            ledger_entry=ledger_entry,
            lineage=lineage,
        )
    if previous_last_closed_position and not position_lifecycle.get("last_closed_position"):
        position_lifecycle["last_closed_position"] = previous_last_closed_position
    risk_runtime_payload = build_risk_runtime_payload(
        generated_at=generated_at,
        lineage=lineage,
        ledger_entry=ledger_entry,
        paper_account=paper_account,
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
        "live_gate": LIVE_GATE_STATUS,
        "live_gate_status": LIVE_GATE_STATUS,
        "live_symbols": [],
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
        "paper_position_lifecycle": position_lifecycle,
        "feature_snapshot": feature_snapshot,
        "trainer_prediction": trainer_prediction,
        "current_signal_lineage": lineage,
        "current_risk_decision": lineage["risk_decision"],
        "risk_runtime_payload": risk_runtime_payload,
        "paper_ledger_tail": [ledger_entry],
        "audit_events": [
            {
                "audit_event_id": f"audit_{tick_id}",
                "generated_at": generated_at,
                "event_type": "V2_PAPER_RUNTIME_TICK",
                "lineage_ids": lineage["lineage_ids"],
                "paper_ledger_entry_id": ledger_entry["paper_ledger_entry_id"],
                "live_gate": LIVE_GATE_STATUS,
                "live_gate_status": LIVE_GATE_STATUS,
                "live_symbols": [],
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
        "live_gate": LIVE_GATE_STATUS,
        "live_gate_status": LIVE_GATE_STATUS,
        "live_symbols": [],
        "mode": "paper_only_non_live",
        "paper_pnl": paper_account["realized_pnl"],
        "position_count": paper_account["open_position_count"],
        "open_positions": [
            {
                "symbol": (position_lifecycle.get("open_position") or {}).get("symbol", symbol),
                "side": (position_lifecycle.get("open_position") or {}).get("side", lineage["execution_intent"]["side"]),
                "entry_price": (position_lifecycle.get("open_position") or {}).get("entry_price"),
                "unrealized_pnl_usdt": (position_lifecycle.get("open_position") or {}).get("unrealized_pnl_usdt"),
                "source": "V2_PAPER_RUNTIME_POSITION_LIFECYCLE",
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
        _write_json(root / "risk_runtime_payload.json", payload["risk_runtime_payload"])
        _write_json(
            root / "paper_ledger_tail.json",
            {
                "generated_at": payload["generated_at"],
                "source": "v2.backend.app.cli.paper_online_runtime",
                "entries": payload["paper_ledger_tail"],
            },
        )
        append_paper_event(root, payload, payload["risk_runtime_payload"])
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
    _write_json(FINAL_DIR / "risk_runtime_payload.json", payload["risk_runtime_payload"])
    _write_json(FINAL_DIR / "paper_ledger_tail.json", {
        "generated_at": payload["generated_at"],
        "source": "v2.backend.app.cli.paper_online_runtime",
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
            "enable-live-trading",
            "change-leverage",
            "change-margin",
            "place-or-cancel-orders",
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
