from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.feature_pipeline_native.service import (
    FeaturePipelineNativeService,
    NativeFeatureInputs,
)
from v2.backend.app.services.market_state_integrity.replay_snapshot import (
    build_replay_snapshot,
)
from v2.backend.app.services.market_state_integrity.scoring import score_market_state
from v2.backend.app.services.market_state_integrity import TrustGateRejectedError
from v2.backend.app.services.market_state_integrity.trust import (
    build_market_state_envelope_from_snapshot,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.masa import (
    V2MASAAdapter as HybridMASAAdapter,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import (
    V2HybridPolicyModel,
)
from v2.backend.app.services.orchestrator_decision.service import (
    assemble_orchestrator_decision_record,
)
from v2.backend.app.services.risk_gateway.service import assemble_risk_decision_record
from v2.backend.app.services.rl_core.observation_builder import (
    build_observation_from_snapshot,
)
from v2.backend.app.services.strategy_router import route_strategy
from v2.backend.app.services.trainer_prediction_output.service import (
    assemble_prediction_record,
)

DEFAULT_OUTPUT_DIR = Path(
    "v2/frontend/public/operator_runtime/run_e2e_verification/latest"
)

TIMEFRAME_SECONDS = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
}
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h")


@dataclass(frozen=True)
class ScenarioDefinition:
    name: str
    expected_result: str
    expected_actual_results: tuple[str, ...]
    expect_trade_approved: bool | None
    expect_training_sample_accepted: bool
    trend: str
    current_position_state: str = "FLAT"
    execution_success_probability: float = 0.95
    source_disagreement_bps: float = 2.0
    latency_ms: int = 200
    duplicate_timeframe: str | None = None
    missing_timeframe: str | None = None
    unfinished_timeframe: str | None = None
    masa_age_seconds: int = 0
    masa_feature_cutoff_offset_seconds: int = 0
    execution_slippage_bps: float = 1.0
    max_execution_slippage_bps: float = 8.0
    inject_backfill: bool = False


@dataclass(frozen=True)
class SyntheticCandle:
    exchange: str
    symbol: str
    timeframe: str
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_final: bool
    available_at: datetime
    ingested_at: datetime
    source_provider: str = "synthetic_ingestor"
    source_sequence_id: int = 0

    def as_feature_ohlcv(self) -> dict[str, float]:
        return {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@dataclass(frozen=True)
class ScenarioRun:
    scenario_name: str
    expected_result: str
    actual_result: str
    passed: bool
    critical: bool
    decision_id: str
    data_quality_flags: list[str]
    masa_ppo_cutoff: dict[str, Any]
    risk_decision: dict[str, Any]
    trade_approved: bool
    training_sample_accepted: bool
    strategy_mode: str
    replay_snapshot: dict[str, Any]


@dataclass(frozen=True)
class VerificationReport:
    generated_at: str
    output_dir: str
    scenarios: list[ScenarioRun]
    summary: dict[str, Any]
    replay_records: dict[str, dict[str, Any]]

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "output_dir": self.output_dir,
            "summary": dict(self.summary),
            "scenarios": [asdict(item) for item in self.scenarios],
            "replay_records": dict(self.replay_records),
        }


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _coerce_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    if isinstance(value, str):
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) else None
    return None


def _hash_payload(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _decision_id_for(name: str, decision_time: datetime) -> str:
    seed = f"{name}|{_iso(decision_time)}"
    return "e2e_" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]


def _expected_direction(trend: str) -> str:
    if trend == "up":
        return "long"
    if trend == "down":
        return "short"
    return "hold"


def _build_scenarios(now: datetime) -> list[ScenarioDefinition]:
    return [
        ScenarioDefinition(
            name="clean_trending_up_market",
            expected_result="clean data should produce an approved or otherwise valid long-biased decision",
            expected_actual_results=("APPROVED_TRADE", "VALID_DECISION_NO_TRADE"),
            expect_trade_approved=True,
            expect_training_sample_accepted=True,
            trend="up",
        ),
        ScenarioDefinition(
            name="clean_trending_down_market",
            expected_result="clean data should produce an approved or otherwise valid short-biased decision",
            expected_actual_results=("APPROVED_TRADE", "VALID_DECISION_NO_TRADE"),
            expect_trade_approved=True,
            expect_training_sample_accepted=True,
            trend="down",
        ),
        ScenarioDefinition(
            name="choppy_ranging_market",
            expected_result="clean ranging data should stay valid and avoid unsafe execution",
            expected_actual_results=("VALID_DECISION_NO_TRADE", "APPROVED_TRADE"),
            expect_trade_approved=None,
            expect_training_sample_accepted=True,
            trend="range",
        ),
        ScenarioDefinition(
            name="sudden_volatility_spike",
            expected_result="volatility spike should reduce size or block while remaining replayable",
            expected_actual_results=("APPROVED_TRADE", "BLOCKED_BY_RISK_MANAGER", "VALID_DECISION_NO_TRADE"),
            expect_trade_approved=None,
            expect_training_sample_accepted=True,
            trend="spike",
            execution_slippage_bps=4.0,
            max_execution_slippage_bps=8.0,
            latency_ms=600,
        ),
        ScenarioDefinition(
            name="missing_candle_scenario",
            expected_result="missing required candles must be blocked before execution and training",
            expected_actual_results=("BLOCKED_BY_DATA_GATE",),
            expect_trade_approved=False,
            expect_training_sample_accepted=False,
            trend="up",
            missing_timeframe="5m",
        ),
        ScenarioDefinition(
            name="duplicate_candle_scenario",
            expected_result="duplicate candles must be blocked before execution and training",
            expected_actual_results=("BLOCKED_BY_DATA_GATE",),
            expect_trade_approved=False,
            expect_training_sample_accepted=False,
            trend="up",
            duplicate_timeframe="1m",
        ),
        ScenarioDefinition(
            name="unfinished_higher_timeframe_candle_scenario",
            expected_result="unfinished higher timeframe candles must be blocked before execution and training",
            expected_actual_results=("BLOCKED_BY_DATA_GATE",),
            expect_trade_approved=False,
            expect_training_sample_accepted=False,
            trend="up",
            unfinished_timeframe="15m",
        ),
        ScenarioDefinition(
            name="stale_masa_prediction_scenario",
            expected_result="stale MASA predictions must be detected and blocked before execution and training",
            expected_actual_results=("BLOCKED_BY_RISK_MANAGER",),
            expect_trade_approved=False,
            expect_training_sample_accepted=False,
            trend="up",
            masa_age_seconds=3_600,
        ),
        ScenarioDefinition(
            name="future_leaking_masa_prediction_scenario",
            expected_result="future-leaking MASA predictions must be detected and blocked before execution and training",
            expected_actual_results=("BLOCKED_BY_RISK_MANAGER",),
            expect_trade_approved=False,
            expect_training_sample_accepted=False,
            trend="up",
            masa_feature_cutoff_offset_seconds=120,
        ),
        ScenarioDefinition(
            name="poor_execution_slippage_scenario",
            expected_result="poor slippage must prevent execution acceptance and keep the training sample dirty",
            expected_actual_results=("BLOCKED_BY_EXECUTION_SIMULATOR",),
            expect_trade_approved=False,
            expect_training_sample_accepted=False,
            trend="up",
            execution_slippage_bps=25.0,
            max_execution_slippage_bps=8.0,
        ),
        ScenarioDefinition(
            name="invalid_position_transition_scenario",
            expected_result="invalid position transitions must be blocked and replayable",
            expected_actual_results=("BLOCKED_BY_RISK_MANAGER",),
            expect_trade_approved=False,
            expect_training_sample_accepted=False,
            trend="down",
            current_position_state="LONG",
        ),
    ]


def _base_price_for_trend(trend: str) -> float:
    if trend == "down":
        return 120.0
    return 100.0


def _price_move(index: int, count: int, trend: str, timeframe: str) -> float:
    if trend == "up":
        return 0.18 * index
    if trend == "down":
        return -0.18 * index
    if trend == "range":
        return 0.9 * math.sin(index / 2.0)
    if trend == "spike":
        if index < count - 4:
            return 0.08 * index
        spike_index = index - (count - 4)
        return 0.08 * (count - 4) + (2.0 * ((-1) ** spike_index)) + (1.4 * spike_index)
    return 0.0


def _generate_candles_for_timeframe(
    *,
    symbol: str,
    exchange: str,
    timeframe: str,
    count: int,
    decision_time: datetime,
    trend: str,
) -> list[SyntheticCandle]:
    tf_seconds = TIMEFRAME_SECONDS[timeframe]
    candles: list[SyntheticCandle] = []
    base_price = _base_price_for_trend(trend)
    for index in range(count):
        close_time = decision_time - timedelta(seconds=tf_seconds * (count - index - 1))
        open_time = close_time - timedelta(seconds=tf_seconds)
        move = _price_move(index, count, trend, timeframe)
        center = base_price + move
        body = 0.25 if trend != "spike" else 0.9
        wick = 0.35 if trend != "spike" else 1.6
        close_price = round(center, 6)
        open_price = round(center - body if trend != "down" else center + body, 6)
        high_price = round(max(open_price, close_price) + wick, 6)
        low_price = round(min(open_price, close_price) - wick, 6)
        available_at = close_time
        ingested_at = available_at + timedelta(milliseconds=120)
        candles.append(
            SyntheticCandle(
                exchange=exchange,
                symbol=symbol,
                timeframe=timeframe,
                open_time=open_time,
                close_time=close_time,
                open=open_price,
                high=high_price,
                low=low_price,
                close=close_price,
                volume=1000.0 + index * 3.0,
                is_final=True,
                available_at=available_at,
                ingested_at=ingested_at,
                source_sequence_id=index + 1,
            )
        )
    return candles


def _build_candles_by_timeframe(
    *,
    symbol: str,
    exchange: str,
    decision_time: datetime,
    scenario: ScenarioDefinition,
) -> dict[str, list[SyntheticCandle]]:
    candles_by_timeframe = {
        timeframe: _generate_candles_for_timeframe(
            symbol=symbol,
            exchange=exchange,
            timeframe=timeframe,
            count=60,
            decision_time=decision_time,
            trend=scenario.trend,
        )
        for timeframe in REQUIRED_TIMEFRAMES
    }
    if scenario.missing_timeframe and candles_by_timeframe.get(scenario.missing_timeframe):
        candles_by_timeframe[scenario.missing_timeframe] = candles_by_timeframe[
            scenario.missing_timeframe
        ][:-1]
    if scenario.duplicate_timeframe and candles_by_timeframe.get(scenario.duplicate_timeframe):
        duplicate_source = candles_by_timeframe[scenario.duplicate_timeframe][-1]
        candles_by_timeframe[scenario.duplicate_timeframe].append(duplicate_source)
    if scenario.unfinished_timeframe and candles_by_timeframe.get(scenario.unfinished_timeframe):
        unfinished = candles_by_timeframe[scenario.unfinished_timeframe][-1]
        candles_by_timeframe[scenario.unfinished_timeframe][-1] = SyntheticCandle(
            exchange=unfinished.exchange,
            symbol=unfinished.symbol,
            timeframe=unfinished.timeframe,
            open_time=unfinished.open_time,
            close_time=unfinished.close_time + timedelta(seconds=TIMEFRAME_SECONDS[unfinished.timeframe]),
            open=unfinished.open,
            high=unfinished.high,
            low=unfinished.low,
            close=unfinished.close,
            volume=unfinished.volume,
            is_final=False,
            available_at=unfinished.available_at + timedelta(seconds=TIMEFRAME_SECONDS[unfinished.timeframe]),
            ingested_at=unfinished.ingested_at + timedelta(seconds=TIMEFRAME_SECONDS[unfinished.timeframe]),
            source_provider=unfinished.source_provider,
            source_sequence_id=unfinished.source_sequence_id,
        )
    return candles_by_timeframe


def _latest_closed_candle(
    candles: list[SyntheticCandle],
    decision_time: datetime,
) -> SyntheticCandle | None:
    eligible = [
        candle
        for candle in candles
        if candle.is_final and candle.close_time <= decision_time and candle.available_at <= decision_time
    ]
    if not eligible:
        return None
    eligible.sort(key=lambda candle: candle.close_time)
    return eligible[-1]


def _align_timeframes(
    *,
    candles_by_timeframe: Mapping[str, list[SyntheticCandle]],
    decision_time: datetime,
) -> tuple[dict[str, SyntheticCandle | None], dict[str, Any]]:
    aligned: dict[str, SyntheticCandle | None] = {}
    missing_required: list[str] = []
    duplicate_count = 0
    out_of_order_count = 0
    unfinished_higher_timeframes: list[str] = []
    for timeframe, candles in candles_by_timeframe.items():
        aligned[timeframe] = _latest_closed_candle(candles, decision_time)
        tf_seconds = TIMEFRAME_SECONDS[timeframe]
        if aligned[timeframe] is None:
            missing_required.append(timeframe)
        elif (decision_time - aligned[timeframe].close_time).total_seconds() >= tf_seconds:
            missing_required.append(timeframe)
        seen_open_times: set[datetime] = set()
        previous_open_time: datetime | None = None
        previous_sequence: int | None = None
        for candle in candles:
            if candle.open_time in seen_open_times:
                duplicate_count += 1
            seen_open_times.add(candle.open_time)
            if previous_open_time is not None and candle.open_time < previous_open_time:
                out_of_order_count += 1
            if previous_sequence is not None and candle.source_sequence_id < previous_sequence:
                out_of_order_count += 1
            previous_open_time = candle.open_time
            previous_sequence = candle.source_sequence_id
        if timeframe != "1m":
            last_candle = candles[-1] if candles else None
            if (
                last_candle is not None
                and (
                    not last_candle.is_final
                    or last_candle.close_time > decision_time
                    or last_candle.available_at > decision_time
                )
            ):
                unfinished_higher_timeframes.append(timeframe)
    return aligned, {
        "missing_required_timeframes": missing_required,
        "duplicate_candle_count": duplicate_count,
        "out_of_order_event_count": out_of_order_count,
        "unfinished_higher_timeframes": unfinished_higher_timeframes,
    }


def _next_higher_timeframe(timeframe: str) -> str | None:
    mapping = {
        "1m": "15m",
        "5m": "1h",
        "15m": "1h",
        "1h": None,
    }
    return mapping.get(timeframe)


def _feature_input_for_timeframe(
    *,
    scenario: ScenarioDefinition,
    decision_time: datetime,
    timeframe: str,
    candles_by_timeframe: Mapping[str, list[SyntheticCandle]],
    current_position_state: str,
) -> NativeFeatureInputs:
    candles = candles_by_timeframe[timeframe]
    latest = candles[-1]
    higher_tf = _next_higher_timeframe(timeframe)
    higher_window = tuple(
        candle.close for candle in candles_by_timeframe.get(higher_tf or "", [])[-20:]
    )
    spread_bps = 6.0 if scenario.trend != "spike" else 16.0
    last_price = latest.close
    bid_price = last_price * (1.0 - spread_bps / 20_000.0)
    ask_price = last_price * (1.0 + spread_bps / 20_000.0)
    position_notional = 150.0 if current_position_state in {"LONG", "SHORT"} else None
    entry_price = last_price - 1.0 if current_position_state == "LONG" else (
        last_price + 1.0 if current_position_state == "SHORT" else None
    )
    return NativeFeatureInputs(
        symbol=latest.symbol,
        timeframe=timeframe,
        generated_utc=_iso(decision_time),
        ohlcv_window=tuple(candle.as_feature_ohlcv() for candle in candles[-60:]),
        ohlcv_window_age_seconds=max(0, int((decision_time - latest.close_time).total_seconds())),
        bid_price=bid_price,
        ask_price=ask_price,
        bid_size=5.0,
        ask_size=4.5,
        orderbook_age_seconds=1,
        higher_tf_label=higher_tf,
        higher_tf_close_window=higher_window,
        higher_tf_age_seconds=1 if higher_tf else None,
        funding_rate=0.0001,
        funding_age_seconds=15,
        open_interest=1_050_000.0,
        open_interest_prior=1_000_000.0,
        open_interest_age_seconds=15,
        last_liquidation_notional_24h=40_000.0 if scenario.trend != "spike" else 180_000.0,
        liquidation_age_seconds=20,
        paper_position_notional=position_notional,
        paper_position_entry_price=entry_price,
        paper_position_age_seconds=180 if position_notional is not None else None,
    )


def _direction_from_expected_move(value_bps: float) -> str:
    if value_bps >= 2.0:
        return "long"
    if value_bps <= -2.0:
        return "short"
    return "hold"


def _build_market_state_row(
    *,
    snapshot: dict[str, Any],
    selected_candle: SyntheticCandle | None,
    scenario: ScenarioDefinition,
    decision_time: datetime,
) -> dict[str, Any]:
    row = {
        "symbol": snapshot.get("symbol"),
        "timeframe": snapshot.get("timeframe"),
        "feature_snapshot_id": snapshot.get("feature_snapshot_id"),
        "generated_utc": snapshot.get("generated_at") or _iso(decision_time),
        "generated_at": snapshot.get("generated_at") or _iso(decision_time),
        "decision_time_est": _iso(decision_time),
        "feature_freshness_state": snapshot.get("feature_freshness_state"),
        "missing_feature_count": len(snapshot.get("missing_feature_flags") or []),
        "missing_feature_flags": list(snapshot.get("missing_feature_flags") or []),
        "stale_feature_count": len(snapshot.get("stale_feature_flags") or []),
        "stale_feature_flags": list(snapshot.get("stale_feature_flags") or []),
        "latency_ms": scenario.latency_ms,
        "price_disagreement_bps": scenario.source_disagreement_bps,
        "backfilled": scenario.inject_backfill,
        "trainer_consumable": True,
        "features": snapshot.get("features") or {},
    }
    if selected_candle is not None:
        row.update(
            {
                "source_event_time_utc": _iso(selected_candle.close_time),
                "candle_closed_confirmed": selected_candle.is_final,
                "candle_open_time": _iso(selected_candle.open_time),
                "candle_close_time": _iso(selected_candle.close_time),
            }
        )
    return row


def _build_envelope(
    *,
    snapshot: dict[str, Any],
    aligned: Mapping[str, SyntheticCandle | None],
    scenario: ScenarioDefinition,
    decision_time: datetime,
    gate_flags: list[str],
    gate_score: float,
    alignment_stats: Mapping[str, Any],
) -> dict[str, Any]:
    selected = aligned.get("1m")
    feature_hash = _hash_payload(snapshot.get("features") or {})
    timeframe_cutoffs = {
        timeframe: (_iso(candle.close_time) if candle is not None else None)
        for timeframe, candle in aligned.items()
    }
    source_sequence_id = selected.source_sequence_id if selected is not None else None
    return {
        "symbol": snapshot.get("symbol"),
        "exchange": "binance",
        "decision_time": _iso(decision_time),
        "event_time": _iso(selected.close_time) if selected is not None else None,
        "available_at": _iso(selected.available_at) if selected is not None else None,
        "ingested_at": _iso(selected.ingested_at) if selected is not None else None,
        "source_provider": selected.source_provider if selected is not None else "synthetic_ingestor",
        "source_sequence_id": source_sequence_id,
        "timeframe_cutoffs": timeframe_cutoffs,
        "feature_version": snapshot.get("schema_version"),
        "feature_hash": feature_hash,
        "data_quality_score": gate_score,
        "data_quality_flags": list(gate_flags),
        "is_backfilled": bool(scenario.inject_backfill),
        "is_final_candle": bool(selected.is_final) if selected is not None else False,
        "missing_candle_count": len(alignment_stats.get("missing_required_timeframes") or []),
        "duplicate_event_count": int(alignment_stats.get("duplicate_candle_count") or 0),
        "out_of_order_event_count": int(alignment_stats.get("out_of_order_event_count") or 0),
        "source_disagreement_score": max(0.0, 100.0 - float(scenario.source_disagreement_bps)),
        "latency_ms": scenario.latency_ms,
        "confidence_calibrated": None,
        "expected_move_after_cost_bps": None,
    }


def _evaluate_data_gate(
    *,
    snapshot: dict[str, Any],
    aligned: Mapping[str, SyntheticCandle | None],
    alignment_stats: Mapping[str, Any],
    scenario: ScenarioDefinition,
    decision_time: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    score = score_market_state(
        _build_market_state_row(
            snapshot=snapshot,
            selected_candle=aligned.get("1m"),
            scenario=scenario,
            decision_time=decision_time,
        )
    )
    flags = list(score.reject_reasons)
    if alignment_stats["missing_required_timeframes"]:
        flags.append("missing_required_candles")
    if alignment_stats["duplicate_candle_count"]:
        flags.append("duplicate_candles_detected")
    if alignment_stats["out_of_order_event_count"]:
        flags.append("out_of_order_events_detected")
    if alignment_stats["unfinished_higher_timeframes"]:
        flags.append("unfinished_higher_timeframe_candle")
    flags = sorted(set(flags))
    penalty = 15.0 * len([flag for flag in flags if flag not in score.reject_reasons])
    gate_score = max(0.0, score.market_state_integrity_score - penalty)
    valid = (
        score.valid_for_prediction
        and not alignment_stats["missing_required_timeframes"]
        and alignment_stats["duplicate_candle_count"] == 0
        and alignment_stats["out_of_order_event_count"] == 0
        and not alignment_stats["unfinished_higher_timeframes"]
    )
    envelope = _build_envelope(
        snapshot=snapshot,
        aligned=aligned,
        scenario=scenario,
        decision_time=decision_time,
        gate_flags=flags,
        gate_score=gate_score,
        alignment_stats=alignment_stats,
    )
    return {
        "valid": valid,
        "score": gate_score,
        "flags": flags,
        "market_state_score": score.to_dict(),
        "envelope": envelope,
    }, envelope


def _build_masa_predictions(
    *,
    snapshots_by_timeframe: Mapping[str, dict[str, Any]],
    aligned: Mapping[str, SyntheticCandle | None],
    scenario: ScenarioDefinition,
    decision_time: datetime,
) -> list[dict[str, Any]]:
    model = V2HybridPolicyModel(input_dim=26)
    masa = HybridMASAAdapter()
    predictions: list[dict[str, Any]] = []
    for timeframe in REQUIRED_TIMEFRAMES:
        snapshot = snapshots_by_timeframe[timeframe]
        candle = aligned[timeframe]
        tf_seconds = TIMEFRAME_SECONDS[timeframe]
        cutoff_dt = datetime.fromtimestamp(
            (int(decision_time.timestamp()) // tf_seconds) * tf_seconds,
            tz=timezone.utc,
        )
        available_dt = candle.available_at if candle is not None else cutoff_dt
        ingested_dt = candle.ingested_at if candle is not None else available_dt
        envelope = {
            "symbol": str(snapshot.get("symbol") or "BTCUSDT"),
            "exchange": str(getattr(candle, "exchange", "binance")),
            "decision_time": _iso(decision_time),
            "event_time": _iso(cutoff_dt),
            "available_at": _iso(available_dt),
            "ingested_at": _iso(ingested_dt),
            "timeframe_cutoffs": {timeframe: _iso(cutoff_dt)},
            "feature_cutoff": _iso(cutoff_dt),
            "feature_version": str(snapshot.get("schema_version") or "v2_native_feature_snapshot_v1"),
            "feature_hash": _hash_payload(snapshot.get("features") or {}),
            "data_quality_score": 1.0 if candle is not None else 0.0,
            "data_quality_flags": [],
            "is_backfilled": False,
            "is_final_candle": False if candle is None else bool(candle.is_final),
            "missing_candle_count": 0 if candle is not None else 1,
            "duplicate_event_count": 0,
            "out_of_order_event_count": 0,
            "source_disagreement_score": float(scenario.source_disagreement_bps),
            "latency_ms": max(0, int((decision_time - available_dt).total_seconds() * 1000)),
            "decision_id": f"e2e_obs_{scenario.name}_{timeframe}",
        }
        try:
            observation = build_observation_from_snapshot(
                snapshot,
                market_state_envelope=envelope,
            )
        except TrustGateRejectedError as exc:
            predictions.append(
                {
                    "prediction_id": f"masa_{scenario.name}_{timeframe}_{snapshot['feature_snapshot_id'][-8:]}",
                    "symbol": snapshot.get("symbol"),
                    "timeframe": timeframe,
                    "model_version": "TRUST_GATE_BLOCKED",
                    "generated_at": _iso(decision_time),
                    "trained_until": envelope["feature_cutoff"],
                    "feature_cutoff": envelope["feature_cutoff"],
                    "forecast_horizon": timeframe,
                    "predicted_return_bps": 0.0,
                    "predicted_price": None,
                    "confidence_calibrated": 0.0,
                    "confidence": 0.0,
                    "validity_until": envelope["feature_cutoff"],
                    "input_feature_hash": envelope["feature_hash"],
                    "selected_action": "hold",
                    "masa_signal": 0.0,
                    "masa_regime_score": 0.0,
                    "trust_gate_rejected": True,
                    "trust_gate_reject_reasons": list(exc.trust_gate_result.reject_reasons),
                }
            )
            continue
        model_output = model.forward(observation.tensor)
        coverage = max(
            0.0,
            100.0
            - (len(snapshot.get("missing_feature_flags") or []) * 4.0)
            - (len(snapshot.get("stale_feature_flags") or []) * 6.0),
        )
        masa_output = masa.evaluate(
            expected_move_bps=model_output.expected_move_bps,
            action_probabilities=model_output.action_probabilities,
            data_coverage_percent=coverage,
        )
        directional_probs = [
            float(model_output.action_probabilities[1]),
            float(model_output.action_probabilities[2]),
        ]
        derived_confidence = max(
            min(1.0, abs(masa_output.masa_signal)),
            min(1.0, abs(model_output.expected_move_bps) / 120.0),
            max(directional_probs),
        )
        feature_cutoff_dt = candle.close_time if candle is not None else decision_time
        feature_cutoff_dt = feature_cutoff_dt + timedelta(
            seconds=scenario.masa_feature_cutoff_offset_seconds
        )
        generated_at_dt = decision_time - timedelta(seconds=scenario.masa_age_seconds)
        selected_action = _direction_from_expected_move(model_output.expected_move_bps)
        prediction_id = f"masa_{scenario.name}_{timeframe}_{snapshot['feature_snapshot_id'][-8:]}"
        predictions.append(
            {
                "prediction_id": prediction_id,
                "symbol": snapshot.get("symbol"),
                "timeframe": timeframe,
                "model_version": model_output.model_source,
                "generated_at": _iso(generated_at_dt),
                "trained_until": _iso(feature_cutoff_dt),
                "feature_cutoff": _iso(feature_cutoff_dt),
                "forecast_horizon": timeframe,
                "predicted_return_bps": round(model_output.expected_move_bps, 6),
                "predicted_price": None,
                "confidence_calibrated": round(derived_confidence, 6),
                "confidence": round(derived_confidence, 6),
                "validity_until": _iso(feature_cutoff_dt + timedelta(seconds=TIMEFRAME_SECONDS[timeframe])),
                "input_feature_hash": _hash_payload(snapshot.get("features") or {}),
                "selected_action": selected_action,
                "masa_signal": round(masa_output.masa_signal, 6),
                "masa_regime_score": round(masa_output.regime_score, 6),
            }
        )
    return predictions


def _build_ppo_contract(
    *,
    snapshot: dict[str, Any],
    decision_time: datetime,
    current_position_state: str,
    included_masa_prediction_id: str | None,
) -> dict[str, Any]:
    try:
        observation = build_observation_from_snapshot(
            snapshot,
            market_state_envelope=build_market_state_envelope_from_snapshot(snapshot),
        )
    except TrustGateRejectedError as exc:
        return {
            "policy_version": "TRUST_GATE_BLOCKED",
            "model_source": "TRUST_GATE_BLOCKED",
            "observation_time": _iso(decision_time),
            "feature_cutoff": snapshot.get("feature_cutoff") or _iso(decision_time),
            "observation_hash": _hash_payload({"blocked": True, "snapshot": snapshot.get("feature_snapshot_id")}),
            "included_masa_prediction_id": included_masa_prediction_id,
            "action_mask": {"hold": True, "long": False, "short": False, "close": False},
            "position_state": str(current_position_state).upper(),
            "raw_selected_action": "hold",
            "selected_action": "hold",
            "action_probabilities": [1.0, 0.0, 0.0],
            "confidence_calibrated": 0.0,
            "expected_move_bps": 0.0,
            "policy_value": 0.0,
            "observation_feature_snapshot_id": str(snapshot.get("feature_snapshot_id") or ""),
            "trust_gate_rejected": True,
            "trust_gate_reject_reasons": list(exc.trust_gate_result.reject_reasons),
        }
    model = V2HybridPolicyModel(input_dim=len(observation.tensor))
    output = model.forward(observation.tensor)
    features = snapshot.get("features") if isinstance(snapshot.get("features"), dict) else {}
    normalized_action = output.selected_action
    if normalized_action not in {"long", "short", "hold"} or normalized_action == "hold":
        normalized_action = _direction_from_expected_move(output.expected_move_bps)
    if normalized_action == "hold":
        for key in ("htf_ret_pct", "ret_pct", "log_return", "macd", "macd_hist"):
            raw = features.get(key)
            try:
                bias = float(raw)
            except (TypeError, ValueError):
                continue
            if bias > 0:
                normalized_action = "long"
                break
            if bias < 0:
                normalized_action = "short"
                break
    feature_cutoff = snapshot.get("generated_at") or _iso(decision_time)
    position_state = str(current_position_state).upper()
    action_mask = {
        "hold": True,
        "long": position_state != "SHORT",
        "short": position_state != "LONG",
        "close": position_state in {"LONG", "SHORT"},
    }
    return {
        "policy_version": output.model_id,
        "model_source": output.model_source,
        "observation_time": _iso(decision_time),
        "feature_cutoff": feature_cutoff,
        "observation_hash": _hash_payload(observation.tensor),
        "included_masa_prediction_id": included_masa_prediction_id,
        "action_mask": action_mask,
        "position_state": position_state,
        "raw_selected_action": output.selected_action,
        "selected_action": normalized_action,
        "action_probabilities": list(output.action_probabilities),
        "confidence_calibrated": output.confidence_calibrated,
        "expected_move_bps": output.expected_move_bps,
        "policy_value": output.policy_value,
        "observation_feature_snapshot_id": observation.feature_snapshot_id,
    }


def _prediction_direction(action: str) -> str:
    if action == "long":
        return "long"
    if action == "short":
        return "short"
    return "flat"


def _worker_freshness_flag(gate: Mapping[str, Any]) -> str:
    flags = set(gate.get("flags") or [])
    if "missing_required_candles" in flags:
        return "missing"
    if flags:
        return "stale"
    return "fresh"


def _trainer_prediction_record(
    *,
    scenario: ScenarioDefinition,
    snapshot: Mapping[str, Any],
    ppo_contract: Mapping[str, Any],
    decision_time: datetime,
    gate: Mapping[str, Any],
) -> Any:
    freshness_flag = _worker_freshness_flag(gate)
    source_freshness_age_ms = None
    if freshness_flag != "missing":
        source_freshness_age_ms = max(
            0, int((_utc_now() - decision_time).total_seconds() * 1000)
        )
    top_features = tuple(
        str(name)
        for name in list((snapshot.get("features") or {}).keys())[:4]
    )
    return assemble_prediction_record(
        prediction_id=f"pred_{scenario.name}_{snapshot['feature_snapshot_id'][-12:]}",
        feature_snapshot_id=str(snapshot["feature_snapshot_id"])[:128],
        symbol=str(snapshot["symbol"]).upper(),
        model_version=str(ppo_contract["policy_version"])[:64],
        checkpoint_id="e2e_verification_checkpoint",
        direction=_prediction_direction(str(ppo_contract["selected_action"])),
        confidence_raw=float(ppo_contract["confidence_calibrated"]),
        confidence_calibrated=float(ppo_contract["confidence_calibrated"]),
        worker_id="run_e2e_verification",
        worker_health_status="HEALTHY" if gate["valid"] else "DEGRADED",
        freshness_flag=freshness_flag,
        source_freshness_age_ms=source_freshness_age_ms,
        top_positive_feature_codes=top_features,
        top_negative_feature_codes=tuple(str(item) for item in snapshot.get("missing_feature_flags") or ())[:4],
        now_ms_clock=lambda: _ms(decision_time),
    )


def _build_cutoff_report(
    *,
    masa_predictions: list[Mapping[str, Any]],
    ppo_contract: Mapping[str, Any],
    decision_time: datetime,
) -> dict[str, Any]:
    ppo_cutoff = str(ppo_contract.get("feature_cutoff"))
    ppo_cutoff_dt = datetime.fromisoformat(ppo_cutoff.replace("Z", "+00:00"))
    masa_cutoffs = {
        str(item["timeframe"]): str(item.get("feature_cutoff"))
        for item in masa_predictions
    }
    stale_masa = False
    future_leakage = False
    cutoff_mismatch = False
    for item in masa_predictions:
        generated_at = datetime.fromisoformat(str(item["generated_at"]).replace("Z", "+00:00"))
        feature_cutoff = datetime.fromisoformat(str(item["feature_cutoff"]).replace("Z", "+00:00"))
        if (decision_time - generated_at).total_seconds() > 300:
            stale_masa = True
        if feature_cutoff > decision_time:
            future_leakage = True
        if feature_cutoff > ppo_cutoff_dt:
            cutoff_mismatch = True
    return {
        "masa_feature_cutoffs": masa_cutoffs,
        "ppo_feature_cutoff": ppo_cutoff,
        "stale_masa_prediction": stale_masa,
        "future_leakage_detected": future_leakage,
        "cutoff_mismatch": cutoff_mismatch,
    }


def _route_strategy_for_scenario(
    *,
    gate: Mapping[str, Any],
    masa_predictions: list[Mapping[str, Any]],
    ppo_contract: Mapping[str, Any],
    scenario: ScenarioDefinition,
    current_position_state: str,
) -> dict[str, Any]:
    envelope = dict(gate["envelope"])
    envelope["confidence_calibrated"] = ppo_contract["confidence_calibrated"]
    envelope["ppo_confidence"] = ppo_contract["confidence_calibrated"]
    envelope["expected_move_after_cost_bps"] = ppo_contract["expected_move_bps"]
    return route_strategy(
        market_state_envelope=envelope,
        masa_predictions=masa_predictions,
        ppo_proposed_action=str(ppo_contract["selected_action"]),
        current_position_state=current_position_state,
        recent_execution_success_metrics={
            "execution_success_probability": scenario.execution_success_probability,
        },
        volatility_liquidity_state={
            "volatility": 0.012 if scenario.trend != "spike" else 0.028,
            "liquidity_score": 0.75 if scenario.trend != "spike" else 0.42,
            "bid_ask_spread_bps": 4.0 if scenario.trend != "spike" else 14.0,
        },
        data_quality_score=float(gate["score"]),
        current_drawdown_risk_state={
            "current_drawdown_bps": 30.0 if scenario.trend != "spike" else 140.0,
        },
        config={
            "masa_confidence_min": 0.0,
            "ppo_confidence_min": 0.2,
        },
    )


def _risk_decision(
    *,
    scenario: ScenarioDefinition,
    decision_time: datetime,
    gate: Mapping[str, Any],
    cutoff_report: Mapping[str, Any],
    router_result: Mapping[str, Any],
    trainer_prediction_record: Any,
) -> tuple[dict[str, Any], Any | None]:
    orchestrator = assemble_orchestrator_decision_record(
        prediction=trainer_prediction_record,
        low_confidence_threshold=0.0,
        now_ms_clock=lambda: _ms(decision_time),
    )
    critical_gate_flags = {
        "missing_required_candles",
        "duplicate_candles_detected",
        "unfinished_higher_timeframe_candle",
        "out_of_order_events_detected",
    }
    if not gate["valid"]:
        return {
            "risk_decision_id": f"risk_{orchestrator.decision_id}",
            "decision_id": orchestrator.decision_id,
            "risk_action": "deny",
            "risk_reason_code": "deny_data_integrity_gate",
            "block_source": "data_integrity_gate",
            "critical_flags": sorted(critical_gate_flags.intersection(gate["flags"])),
        }, orchestrator
    if cutoff_report["future_leakage_detected"]:
        return {
            "risk_decision_id": f"risk_{orchestrator.decision_id}",
            "decision_id": orchestrator.decision_id,
            "risk_action": "deny",
            "risk_reason_code": "deny_future_leaking_masa_prediction",
            "block_source": "masa_cutoff_guard",
        }, orchestrator
    if cutoff_report["cutoff_mismatch"]:
        return {
            "risk_decision_id": f"risk_{orchestrator.decision_id}",
            "decision_id": orchestrator.decision_id,
            "risk_action": "deny",
            "risk_reason_code": "deny_masa_ppo_cutoff_mismatch",
            "block_source": "masa_ppo_contract_guard",
        }, orchestrator
    if cutoff_report["stale_masa_prediction"]:
        return {
            "risk_decision_id": f"risk_{orchestrator.decision_id}",
            "decision_id": orchestrator.decision_id,
            "risk_action": "deny",
            "risk_reason_code": "deny_stale_masa_prediction",
            "block_source": "masa_freshness_guard",
        }, orchestrator
    if router_result.get("block_reason"):
        return {
            "risk_decision_id": f"risk_{orchestrator.decision_id}",
            "decision_id": orchestrator.decision_id,
            "risk_action": "deny",
            "risk_reason_code": f"deny_{router_result['block_reason'].lower()}",
            "block_source": "strategy_router",
        }, orchestrator
    if router_result.get("selected_mode") == "no_trade_mode":
        return {
            "risk_decision_id": f"risk_{orchestrator.decision_id}",
            "decision_id": orchestrator.decision_id,
            "risk_action": "deny",
            "risk_reason_code": "deny_strategy_router_no_trade_mode",
            "block_source": "strategy_router",
        }, orchestrator
    real = assemble_risk_decision_record(
        decision=orchestrator,
        now_ms_clock=lambda: _ms(decision_time),
    )
    return {
        **asdict(real),
        "block_source": "risk_gateway_service",
    }, orchestrator


def _position_state_machine(
    *,
    position_before: str,
    requested_action: str,
    risk_action: str,
) -> dict[str, Any]:
    before = str(position_before).upper()
    action = str(requested_action).lower()
    after = before
    valid_transition = True
    block_reason = None
    if before == "FLAT" and action == "long":
        after = "LONG"
    elif before == "FLAT" and action == "short":
        after = "SHORT"
    elif before == "LONG" and action == "close":
        after = "FLAT"
    elif before == "SHORT" and action == "close":
        after = "FLAT"
    elif before == "LONG" and action == "long":
        after = "LONG"
    elif before == "SHORT" and action == "short":
        after = "SHORT"
    elif action in {"hold", ""}:
        after = before
    else:
        valid_transition = False
        block_reason = "INVALID_POSITION_TRANSITION"
    if risk_action != "allow":
        after = before
    return {
        "position_before": before,
        "requested_action": action,
        "position_after": after,
        "valid_transition": valid_transition,
        "block_reason": block_reason,
    }


def _execution_simulator(
    *,
    scenario: ScenarioDefinition,
    router_result: Mapping[str, Any],
    risk_decision: Mapping[str, Any],
    position_state_result: Mapping[str, Any],
    aligned: Mapping[str, SyntheticCandle | None],
) -> dict[str, Any]:
    entry_candle = aligned.get("1m")
    market_price = entry_candle.close if entry_candle is not None else None
    if (
        risk_decision.get("risk_action") != "allow"
        or not position_state_result.get("valid_transition")
        or market_price is None
    ):
        return {
            "execution_request": {
                "requested_action": position_state_result.get("requested_action"),
                "size_multiplier": router_result.get("size_multiplier"),
            },
            "execution_response": {
                "status": "not_submitted",
                "reason": risk_decision.get("risk_reason_code")
                or position_state_result.get("block_reason")
                or "market_price_missing",
            },
            "filled": False,
            "trade_approved": False,
        }
    slippage_bps = float(scenario.execution_slippage_bps)
    if slippage_bps > float(scenario.max_execution_slippage_bps):
        return {
            "execution_request": {
                "requested_action": position_state_result.get("requested_action"),
                "size_multiplier": router_result.get("size_multiplier"),
            },
            "execution_response": {
                "status": "rejected_slippage",
                "reason": "execution_slippage_above_threshold",
                "slippage_bps": slippage_bps,
            },
            "filled": False,
            "trade_approved": False,
        }
    fill_multiplier = 1.0 + (slippage_bps / 10_000.0)
    requested_action = str(position_state_result["requested_action"])
    fill_price = market_price
    if requested_action == "long":
        fill_price = market_price * fill_multiplier
    elif requested_action == "short":
        fill_price = market_price * (1.0 - (slippage_bps / 10_000.0))
    return {
        "execution_request": {
            "requested_action": requested_action,
            "size_multiplier": router_result.get("size_multiplier"),
        },
        "execution_response": {
            "status": "filled",
            "fill_price": round(fill_price, 6),
            "slippage_bps": slippage_bps,
            "fees_bps": 5.0,
        },
        "filled": True,
        "trade_approved": True,
    }


def _training_sample_filter(
    *,
    gate: Mapping[str, Any],
    cutoff_report: Mapping[str, Any],
    execution_result: Mapping[str, Any],
    risk_decision: Mapping[str, Any],
    position_state_result: Mapping[str, Any],
    decision_time: datetime,
    label_horizon_seconds: int = 60,
) -> dict[str, Any]:
    reasons: list[str] = []
    if not gate["valid"]:
        reasons.append("data_integrity_gate_invalid")
    if cutoff_report["stale_masa_prediction"]:
        reasons.append("stale_masa_prediction_detected")
    if cutoff_report["future_leakage_detected"]:
        reasons.append("masa_future_cutoff_detected")
    if cutoff_report["cutoff_mismatch"]:
        reasons.append("masa_ppo_cutoff_mismatch")
    label_cutoff = decision_time + timedelta(seconds=label_horizon_seconds)
    available_at = gate["envelope"].get("available_at")
    if available_at:
        available_at_dt = datetime.fromisoformat(str(available_at).replace("Z", "+00:00"))
        if available_at_dt > label_cutoff:
            reasons.append("feature_available_after_label_cutoff")
    response = execution_result.get("execution_response") or {}
    if execution_result.get("trade_approved"):
        if response.get("status") != "filled":
            reasons.append("execution_result_missing_when_required")
        if response.get("fees_bps") is None:
            reasons.append("fees_missing")
        if response.get("slippage_bps") is None:
            reasons.append("slippage_missing")
    if response.get("status") == "rejected_slippage":
        reasons.append("execution_slippage_rejected")
    if risk_decision.get("risk_action") != "allow" and (
        not gate["valid"]
        or cutoff_report["stale_masa_prediction"]
        or cutoff_report["future_leakage_detected"]
        or cutoff_report["cutoff_mismatch"]
        or position_state_result.get("valid_transition") is False
    ):
        reasons.append("risk_decision_denied_for_safety")
    if position_state_result.get("valid_transition") is False:
        reasons.append("invalid_position_transition")
    return {
        "accepted": not reasons,
        "rejection_reasons": reasons,
        "label_cutoff": _iso(label_cutoff),
    }


def _actual_result(
    *,
    gate: Mapping[str, Any],
    risk_decision: Mapping[str, Any],
    execution_result: Mapping[str, Any],
) -> str:
    if not gate["valid"]:
        return "BLOCKED_BY_DATA_GATE"
    if risk_decision.get("risk_action") != "allow":
        return "BLOCKED_BY_RISK_MANAGER"
    if not execution_result.get("trade_approved"):
        return "BLOCKED_BY_EXECUTION_SIMULATOR"
    if execution_result.get("filled"):
        return "APPROVED_TRADE"
    return "VALID_DECISION_NO_TRADE"


def _passed(
    *,
    scenario: ScenarioDefinition,
    actual_result: str,
    trade_approved: bool,
    training_sample_accepted: bool,
) -> bool:
    if actual_result not in scenario.expected_actual_results:
        return False
    if (
        scenario.expect_trade_approved is not None
        and scenario.expect_trade_approved != trade_approved
    ):
        return False
    if scenario.expect_training_sample_accepted != training_sample_accepted:
        return False
    return True


def _replay_record(
    *,
    decision_id: str,
    scenario: ScenarioDefinition,
    decision_time: datetime,
    gate: Mapping[str, Any],
    masa_predictions: list[Mapping[str, Any]],
    ppo_contract: Mapping[str, Any],
    router_result: Mapping[str, Any],
    risk_decision: Mapping[str, Any],
    position_state_result: Mapping[str, Any],
    execution_result: Mapping[str, Any],
    training_result: Mapping[str, Any],
    aligned: Mapping[str, SyntheticCandle | None],
    snapshots_by_timeframe: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    prediction_payload = {
        "prediction_id": decision_id,
        "generated_utc": _iso(decision_time),
        "generated_est": _iso(decision_time),
        "symbol": snapshots_by_timeframe["1m"].get("symbol"),
        "timeframe": "1m",
        "feature_snapshot_id": snapshots_by_timeframe["1m"].get("feature_snapshot_id"),
        "all_tf_candle_timestamps": [
            _iso(candle.close_time)
            for candle in aligned.values()
            if candle is not None
        ],
        "all_source_event_times": [
            _iso(candle.available_at)
            for candle in aligned.values()
            if candle is not None
        ],
        "features": snapshots_by_timeframe["1m"].get("features"),
        "feature_names": list((snapshots_by_timeframe["1m"].get("features") or {}).keys()),
        "missing_feature_flags": snapshots_by_timeframe["1m"].get("missing_feature_flags") or [],
        "stale_feature_flags": snapshots_by_timeframe["1m"].get("stale_feature_flags") or [],
        "masa_prediction_timestamp": masa_predictions[0]["generated_at"] if masa_predictions else None,
        "ppo_observation_timestamp": ppo_contract.get("observation_time"),
        "ppo_selected_action": ppo_contract.get("selected_action"),
        "selected_action": ppo_contract.get("selected_action"),
        "masa_expected_move_bps": masa_predictions[0]["predicted_return_bps"] if masa_predictions else None,
        "masa_confidence": masa_predictions[0]["confidence"] if masa_predictions else None,
        "confidence_calibrated": ppo_contract.get("confidence_calibrated"),
    }
    paper_candidate = {
        "decision": _actual_result(
            gate=gate,
            risk_decision=risk_decision,
            execution_result=execution_result,
        ),
        "strategy_selected_mode": router_result.get("selected_mode"),
        "strategy_allowed_actions": list(router_result.get("allowed_actions") or []),
        "strategy_action_mask": dict(router_result.get("action_mask") or {}),
        "strategy_size_multiplier": router_result.get("size_multiplier"),
        "strategy_router_confidence": router_result.get("confidence"),
        "strategy_router_block_reason": router_result.get("block_reason"),
        "strategy_reason_codes": list(router_result.get("reason_codes") or []),
        "strategy_regime_labels": list(router_result.get("regime_labels") or []),
        "strategy_explanation": dict(router_result.get("explanation") or {}),
        "execution_request": execution_result.get("execution_request"),
        "execution_response": execution_result.get("execution_response"),
        "training_sample_filter": training_result,
        "position_state_before": position_state_result.get("position_before"),
        "position_state_after": position_state_result.get("position_after"),
        "position_state_transition_block_reason": position_state_result.get("block_reason"),
        "scenario_name": scenario.name,
    }
    replay = build_replay_snapshot(
        decision_id=decision_id,
        prediction=prediction_payload,
        risk_decision=dict(risk_decision),
        paper_candidate=paper_candidate,
        integrity=dict(gate["market_state_score"]),
    )
    replay["scenario_name"] = scenario.name
    replay["masa_predictions"] = list(masa_predictions)
    replay["ppo_contract"] = dict(ppo_contract)
    replay["training_sample_filter"] = dict(training_result)
    replay["position_state_machine"] = dict(position_state_result)
    return replay


def run_e2e_verification() -> VerificationReport:
    now = _utc_now().replace(second=0, microsecond=0)
    service = FeaturePipelineNativeService()
    scenario_runs: list[ScenarioRun] = []
    replay_records: dict[str, dict[str, Any]] = {}
    for scenario in _build_scenarios(now):
        decision_time = now
        decision_id = _decision_id_for(scenario.name, decision_time)
        candles_by_timeframe = _build_candles_by_timeframe(
            symbol="BTCUSDT",
            exchange="binance",
            decision_time=decision_time,
            scenario=scenario,
        )
        aligned, alignment_stats = _align_timeframes(
            candles_by_timeframe=candles_by_timeframe,
            decision_time=decision_time,
        )
        snapshots_by_timeframe: dict[str, dict[str, Any]] = {}
        for timeframe in REQUIRED_TIMEFRAMES:
            feature_input = _feature_input_for_timeframe(
                scenario=scenario,
                decision_time=decision_time,
                timeframe=timeframe,
                candles_by_timeframe=candles_by_timeframe,
                current_position_state=scenario.current_position_state,
            )
            snapshots_by_timeframe[timeframe] = service.emit_trainer_consumable_snapshot(
                feature_input
            )
        gate, envelope = _evaluate_data_gate(
            snapshot=snapshots_by_timeframe["1m"],
            aligned=aligned,
            alignment_stats=alignment_stats,
            scenario=scenario,
            decision_time=decision_time,
        )
        masa_predictions = _build_masa_predictions(
            snapshots_by_timeframe=snapshots_by_timeframe,
            aligned=aligned,
            scenario=scenario,
            decision_time=decision_time,
        )
        ppo_contract = _build_ppo_contract(
            snapshot=snapshots_by_timeframe["1m"],
            decision_time=decision_time,
            current_position_state=scenario.current_position_state,
            included_masa_prediction_id=masa_predictions[-1]["prediction_id"],
        )
        cutoff_report = _build_cutoff_report(
            masa_predictions=masa_predictions,
            ppo_contract=ppo_contract,
            decision_time=decision_time,
        )
        router_result = _route_strategy_for_scenario(
            gate=gate,
            masa_predictions=masa_predictions,
            ppo_contract=ppo_contract,
            scenario=scenario,
            current_position_state=scenario.current_position_state,
        )
        trainer_prediction = _trainer_prediction_record(
            scenario=scenario,
            snapshot=snapshots_by_timeframe["1m"],
            ppo_contract=ppo_contract,
            decision_time=decision_time,
            gate=gate,
        )
        risk_decision, _orchestrator = _risk_decision(
            scenario=scenario,
            decision_time=decision_time,
            gate=gate,
            cutoff_report=cutoff_report,
            router_result=router_result,
            trainer_prediction_record=trainer_prediction,
        )
        position_state_result = _position_state_machine(
            position_before=scenario.current_position_state,
            requested_action=str(ppo_contract["selected_action"]),
            risk_action=str(risk_decision.get("risk_action")),
        )
        execution_result = _execution_simulator(
            scenario=scenario,
            router_result=router_result,
            risk_decision=risk_decision,
            position_state_result=position_state_result,
            aligned=aligned,
        )
        training_result = _training_sample_filter(
            gate=gate,
            cutoff_report=cutoff_report,
            execution_result=execution_result,
            risk_decision=risk_decision,
            position_state_result=position_state_result,
            decision_time=decision_time,
        )
        actual_result = _actual_result(
            gate=gate,
            risk_decision=risk_decision,
            execution_result=execution_result,
        )
        replay = _replay_record(
            decision_id=decision_id,
            scenario=scenario,
            decision_time=decision_time,
            gate=gate,
            masa_predictions=masa_predictions,
            ppo_contract=ppo_contract,
            router_result=router_result,
            risk_decision=risk_decision,
            position_state_result=position_state_result,
            execution_result=execution_result,
            training_result=training_result,
            aligned=aligned,
            snapshots_by_timeframe=snapshots_by_timeframe,
        )
        replay_records[decision_id] = replay
        passed = _passed(
            scenario=scenario,
            actual_result=actual_result,
            trade_approved=bool(execution_result.get("trade_approved")),
            training_sample_accepted=bool(training_result.get("accepted")),
        )
        scenario_runs.append(
            ScenarioRun(
                scenario_name=scenario.name,
                expected_result=scenario.expected_result,
                actual_result=actual_result,
                passed=passed,
                critical=True,
                decision_id=decision_id,
                data_quality_flags=list(gate["flags"]),
                masa_ppo_cutoff=cutoff_report,
                risk_decision=dict(risk_decision),
                trade_approved=bool(execution_result.get("trade_approved")),
                training_sample_accepted=bool(training_result.get("accepted")),
                strategy_mode=str(router_result.get("selected_mode")),
                replay_snapshot=replay,
            )
        )
    summary = {
        "scenario_count": len(scenario_runs),
        "passed_count": sum(1 for item in scenario_runs if item.passed),
        "failed_count": sum(1 for item in scenario_runs if not item.passed),
        "critical_failures": sum(
            1 for item in scenario_runs if item.critical and not item.passed
        ),
        "all_decision_ids_replayable": all(
            item.decision_id in replay_records for item in scenario_runs
        ),
        "clean_data_valid_decisions": all(
            item.actual_result in {"APPROVED_TRADE", "VALID_DECISION_NO_TRADE"}
            for item in scenario_runs
            if item.scenario_name
            in {
                "clean_trending_up_market",
                "clean_trending_down_market",
                "choppy_ranging_market",
                "sudden_volatility_spike",
            }
        ),
        "dirty_data_blocked_from_training": all(
            item.training_sample_accepted is False
            for item in scenario_runs
            if "clean_" not in item.scenario_name
            and item.scenario_name
            not in {"choppy_ranging_market", "sudden_volatility_spike"}
        ),
        "dirty_data_blocked_from_execution": all(
            item.trade_approved is False
            for item in scenario_runs
            if item.scenario_name
            not in {
                "clean_trending_up_market",
                "clean_trending_down_market",
                "choppy_ranging_market",
                "sudden_volatility_spike",
            }
        ),
    }
    return VerificationReport(
        generated_at=_iso(_utc_now()),
        output_dir=str(DEFAULT_OUTPUT_DIR),
        scenarios=scenario_runs,
        summary=summary,
        replay_records=replay_records,
    )


def _text_report(report: VerificationReport) -> str:
    lines = [
        "V2 End-To-End Verification Report",
        f"Generated: {report.generated_at}",
        f"Scenarios: {report.summary['scenario_count']}",
        f"Passed: {report.summary['passed_count']}",
        f"Failed: {report.summary['failed_count']}",
        f"Critical failures: {report.summary['critical_failures']}",
        "",
    ]
    for scenario in report.scenarios:
        lines.extend(
            [
                f"Scenario: {scenario.scenario_name}",
                f"Expected: {scenario.expected_result}",
                f"Actual: {scenario.actual_result}",
                f"Passed: {'YES' if scenario.passed else 'NO'}",
                f"Decision ID: {scenario.decision_id}",
                f"Data quality flags: {', '.join(scenario.data_quality_flags) if scenario.data_quality_flags else 'none'}",
                f"MASA/PPO cutoff: masa={scenario.masa_ppo_cutoff['masa_feature_cutoffs']} ppo={scenario.masa_ppo_cutoff['ppo_feature_cutoff']}",
                f"Risk decision: {scenario.risk_decision.get('risk_action')} / {scenario.risk_decision.get('risk_reason_code')}",
                f"Trade approved: {scenario.trade_approved}",
                f"Training sample accepted: {scenario.training_sample_accepted}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def run_e2e_verification_report(
    *,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
) -> tuple[VerificationReport, int]:
    report = run_e2e_verification()
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / "e2e_verification_report.json"
    text_path = output_dir / "e2e_verification_report.txt"
    replay_path = output_dir / "e2e_verification_replays.json"
    json_path.write_text(
        json.dumps(report.to_jsonable(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    text_path.write_text(_text_report(report), encoding="utf-8")
    replay_path.write_text(
        json.dumps(report.replay_records, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    exit_code = 1 if report.summary["critical_failures"] else 0
    return report, exit_code
