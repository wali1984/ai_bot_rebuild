"""Paper-only trusted prediction publisher proof.

This command proves the real trusted publisher write path can emit a replayable
pipeline_trust_v3 prediction from canonical closed-candle evidence. It is not a
strategy runner and it cannot submit live orders.
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
    append_closed_candle,
    build_multi_timeframe_decision_snapshot,
    canonical_from_binance_rest,
    closed_candle_key,
    current_candle_key,
    legacy_closed_compat_key,
    latest_closed_candle_at_or_before,
    now_ms,
    parse_ms,
    stable_hash,
)
from v2.backend.app.services.market_state_integrity.trust import (
    ENFORCEMENT_EPOCH,
    TRUST_SCHEMA_VERSION,
    attach_runtime_trust_metadata,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.config import (
    ACTION_LABELS,
    MODEL_SOURCE,
    PREDICTION_KEY_TEMPLATE,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.data_loader import TrainingExample
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.model import ModelForwardResult
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.publisher import (
    V2HybridPredictionPublisher,
    build_prediction_payload,
)
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.safety import V2OnlyJsonIO
from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder import FeatureTensorRecord


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_trusted_prediction_publisher_once")
    parser.add_argument("--redis-url", required=True)
    parser.add_argument("--symbol", default="")
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--timeframe", default="1m")
    parser.add_argument("--paper-only", action="store_true")
    parser.add_argument("--no-live", action="store_true")
    parser.add_argument("--output-dir", default="")
    args = parser.parse_args(argv)

    if not args.paper_only or not args.no_live:
        result = {
            "success": False,
            "status": "BLOCKED",
            "reason": "PAPER_ONLY_AND_NO_LIVE_FLAGS_REQUIRED",
        }
        print(json.dumps(result, indent=2, sort_keys=True))
        return 1

    client = redis_client(args.redis_url)
    result = run_publisher_proof_once(
        client=client,
        symbol=args.symbol or None,
        exchange=args.exchange,
        timeframe=args.timeframe,
    )
    if args.output_dir:
        write_result(Path(args.output_dir), result)
    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0 if result.get("success") is True else 1


def redis_client(redis_url: str) -> Any:
    import redis  # type: ignore[import-not-found]

    return redis.Redis.from_url(redis_url, decode_responses=True)


def run_publisher_proof_once(
    *,
    client: Any,
    symbol: str | None = None,
    exchange: str = "binance",
    timeframe: str = "1m",
) -> dict[str, Any]:
    generated_at = utc_now()
    restore_canonical_closed_candles_from_legacy(client, exchange=exchange)
    selected_symbol = (symbol or select_symbol_with_closed_coverage(client, exchange=exchange) or "").upper()
    if not selected_symbol:
        return fail_result(
            generated_at,
            "NO_SYMBOL_WITH_CANONICAL_CLOSED_CANDLE_COVERAGE",
            checked_patterns=[closed_candle_key(exchange, "*", tf) for tf in REQUIRED_DECISION_TIMEFRAMES],
        )

    candles_by_tf = {
        tf: read_json_key(client, closed_candle_key(exchange, selected_symbol, tf))
        for tf in REQUIRED_DECISION_TIMEFRAMES
    }
    decision_time = now_ms()
    snapshot = build_multi_timeframe_decision_snapshot(
        symbol=selected_symbol,
        decision_time=decision_time,
        candles_by_timeframe=candles_by_tf,
        required_timeframes=REQUIRED_DECISION_TIMEFRAMES,
    )
    if snapshot.get("valid") is not True:
        return fail_result(
            generated_at,
            "MTF_SNAPSHOT_INVALID",
            symbol=selected_symbol,
            mtf_snapshot_id=snapshot.get("mtf_snapshot_id"),
            reject_reasons=list(snapshot.get("reject_reasons") or []),
            missing_timeframes=list(snapshot.get("missing_timeframes") or []),
        )

    selected_candle = latest_closed_candle_at_or_before(candles_by_tf.get(timeframe), decision_time)
    if selected_candle is None:
        return fail_result(
            generated_at,
            "PRIMARY_TIMEFRAME_CLOSED_CANDLE_MISSING",
            symbol=selected_symbol,
            timeframe=timeframe,
        )

    tensor = build_minimal_tensor(
        symbol=selected_symbol,
        timeframe=timeframe,
        candle=selected_candle,
        snapshot=snapshot,
    )
    trust_row = build_trust_row(
        symbol=selected_symbol,
        timeframe=timeframe,
        tensor=tensor,
        candle=selected_candle,
        snapshot=snapshot,
        generated_at=generated_at,
    )
    example = TrainingExample(
        symbol=selected_symbol,
        timeframe=timeframe,
        tensor=tensor,
        label_action_index=0,
        label_expected_move_after_cost_bps=0.0,
        payload_keys=tuple(closed_candle_key(exchange, selected_symbol, tf) for tf in REQUIRED_DECISION_TIMEFRAMES),
        row_classification="PUBLISHER_PROOF_ONLY",
        trust_row=trust_row,
    )
    model_output = hold_model_output()
    payload = build_prediction_payload(
        example=example,
        model_output=model_output,
        checkpoint=None,
        round_trip_cost_bps=0.0,
        min_data_coverage_percent=1.0,
        min_confidence_calibrated=1.0,
        min_edge_after_cost_bps=9999.0,
    )
    payload.update(
        {
            "generated_at": payload.get("generated_est") or generated_at,
            "masa_generated_at": payload.get("generated_est") or generated_at,
            "masa_feature_cutoff": payload.get("feature_cutoff"),
            "masa_forecast_horizon": timeframe,
            "masa_symbol": selected_symbol,
            "masa_timeframe": timeframe,
            "ppo_observation_time": payload.get("decision_time") or payload.get("generated_est") or generated_at,
            "ppo_feature_cutoff": payload.get("feature_cutoff"),
            "ppo_symbol": selected_symbol,
            "ppo_timeframe": timeframe,
            "model_version": payload.get("model_id") or MODEL_SOURCE,
            "policy_version": payload.get("model_id") or "publisher_proof_hold_policy_v1",
            "routes_to_live": False,
            "live_order_allowed": False,
            "paper_only": True,
            "proof_only": True,
            "confidence_source": "PROOF_DEFAULT",
            "masa_confidence_source": "PROOF_DEFAULT",
            "ppo_confidence_source": "PROOF_DEFAULT",
            "combined_confidence_source": "PROOF_DEFAULT",
            "confidence_scale": "0-1 probability",
            "model_consumable": False,
            "paper_intent_consumable": False,
            "routeability_candidate": False,
            "paper_only_diagnostic_prediction": True,
            "no_live": True,
            "publisher_proof_command": "run_trusted_prediction_publisher_once",
        }
    )
    snapshot_payload = attach_runtime_trust_metadata(
        dict(snapshot),
        decision_id=payload.get("decision_id"),
        prediction_id=payload.get("prediction_id"),
        mtf_snapshot_id=payload.get("mtf_snapshot_id"),
        replay_snapshot_id=payload.get("replay_snapshot_id"),
        created_at=generated_at,
        producer="run_trusted_prediction_publisher_once",
    )
    snapshot_payload.update(
        {
            "available_at": payload.get("available_at"),
            "generated_at": payload.get("generated_at") or generated_at,
            "timeframe": timeframe,
            "masa_generated_at": payload.get("masa_generated_at") or payload.get("generated_at") or generated_at,
            "masa_feature_cutoff": payload.get("masa_feature_cutoff") or payload.get("feature_cutoff"),
            "masa_forecast_horizon": payload.get("masa_forecast_horizon") or timeframe,
            "masa_symbol": selected_symbol,
            "masa_timeframe": timeframe,
            "ppo_observation_time": payload.get("ppo_observation_time") or payload.get("decision_time") or generated_at,
            "ppo_feature_cutoff": payload.get("ppo_feature_cutoff") or payload.get("feature_cutoff"),
            "ppo_symbol": selected_symbol,
            "ppo_timeframe": timeframe,
            "all_source_event_times": list(payload.get("all_source_event_times") or []),
            "feature_hash": payload.get("feature_vector_hash"),
            "feature_vector_hash": payload.get("feature_vector_hash"),
            "routes_to_live": False,
            "live_order_allowed": False,
        }
    )
    payload["multi_timeframe_decision_snapshot"] = snapshot_payload
    payload["mtf_snapshot"] = snapshot_payload

    io = V2OnlyJsonIO(client=client)
    feature_key = f"v2:trainer:hybrid_cuda:features:publisher_proof:{selected_symbol}:{timeframe}"
    feature_payload = build_feature_evidence(
        symbol=selected_symbol,
        timeframe=timeframe,
        tensor=tensor,
        trust_row=trust_row,
        generated_at=generated_at,
    )
    if not io.set_json(feature_key, feature_payload):
        return fail_result(
            generated_at,
            "FEATURE_EVIDENCE_WRITE_FAILED",
            symbol=selected_symbol,
            feature_key=feature_key,
            io_errors=list(io.audit.errors),
        )

    mtf_key = f"v2:market:mtf_snapshot:{snapshot_payload['mtf_snapshot_id']}"
    if not io.set_json(mtf_key, snapshot_payload):
        return fail_result(
            generated_at,
            "MTF_SNAPSHOT_WRITE_FAILED",
            symbol=selected_symbol,
            mtf_snapshot_key=mtf_key,
            io_errors=list(io.audit.errors),
        )

    publisher = V2HybridPredictionPublisher(io=io)
    if not publisher.publish_prediction(payload):
        return fail_result(
            generated_at,
            "PREDICTION_PUBLISH_FAILED",
            symbol=selected_symbol,
            prediction_id=payload.get("prediction_id"),
            replay_snapshot_key=payload.get("replay_snapshot_key"),
            mtf_snapshot_key=mtf_key,
            io_errors=list(io.audit.errors),
            keys_written=list(io.audit.keys_written),
        )

    prediction_key = PREDICTION_KEY_TEMPLATE.format(symbol=selected_symbol, timeframe=timeframe)
    published_prediction = read_json_key(client, prediction_key)
    return {
        "success": True,
        "status": "PUBLISHER_PROOF_WRITTEN",
        "generated_at": generated_at,
        "symbol": selected_symbol,
        "timeframe": timeframe,
        "prediction_key": prediction_key,
        "prediction_id": payload.get("prediction_id"),
        "feature_key": feature_key,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "mtf_snapshot_key": mtf_key,
        "mtf_snapshot_id": payload.get("mtf_snapshot_id"),
        "replay_snapshot_key": payload.get("replay_snapshot_key"),
        "replay_snapshot_id": payload.get("replay_snapshot_id"),
        "trust_schema_version": payload.get("trust_schema_version"),
        "routes_to_live": False,
        "live_order_allowed": False,
        "paper_fill_allowed": bool(payload.get("paper_fill_allowed")),
        "routes_to_orchestrator": bool(payload.get("routes_to_orchestrator")),
        "keys_written": list(io.audit.keys_written),
        "published_prediction_present": isinstance(published_prediction, Mapping),
    }


def select_symbol_with_closed_coverage(client: Any, *, exchange: str) -> str | None:
    symbols: dict[str, set[str]] = {}
    pattern = closed_candle_key(exchange, "*", "*")
    try:
        iterator = client.scan_iter(match=pattern, count=500)
    except Exception:
        return None
    for key in iterator:
        parts = str(key).split(":")
        if len(parts) < 6:
            continue
        symbol, timeframe = parts[-2], parts[-1]
        symbols.setdefault(symbol.upper(), set()).add(timeframe)
    required = set(REQUIRED_DECISION_TIMEFRAMES)
    for candidate, timeframes in sorted(symbols.items()):
        if required.issubset(timeframes):
            return candidate
    return None


def restore_canonical_closed_candles_from_legacy(client: Any, *, exchange: str) -> dict[str, Any]:
    if client is None or str(exchange).lower() != "binance":
        return {
            "scanned_legacy_keys": 0,
            "closed_keys_written": 0,
            "current_keys_written": 0,
            "symbols_repaired": [],
        }

    repair_now_ms = now_ms()
    scanned_legacy_keys = 0
    closed_keys_written = 0
    current_keys_written = 0
    symbols_repaired: set[str] = set()
    pattern = legacy_closed_compat_key(exchange, "*", "*")

    try:
        iterator = client.scan_iter(match=pattern, count=500)
    except Exception:
        return {
            "scanned_legacy_keys": 0,
            "closed_keys_written": 0,
            "current_keys_written": 0,
            "symbols_repaired": [],
        }

    for raw_key in iterator:
        key = raw_key.decode("utf-8") if isinstance(raw_key, (bytes, bytearray)) else str(raw_key)
        if not key or key.endswith(":source"):
            continue
        parts = key.split(":")
        if len(parts) < 6:
            continue

        symbol = parts[-2].upper()
        timeframe = parts[-1]
        rows = read_legacy_rows_key(client, key)
        if not isinstance(rows, list) or not rows:
            continue
        scanned_legacy_keys += 1

        source = read_json_key(client, f"{key}:source")
        source_open_time = _coerce_int(source.get("open_time_ms")) if isinstance(source, Mapping) else None
        source_close_time = _coerce_int(source.get("close_time_ms")) if isinstance(source, Mapping) else None
        source_closed = bool(source.get("closed_candle")) if isinstance(source, Mapping) and "closed_candle" in source else None
        source_event_time = _coerce_int(source.get("event_time_ms")) if isinstance(source, Mapping) else None

        target_closed_key = closed_candle_key(exchange, symbol, timeframe)
        existing_closed = read_json_key(client, target_closed_key)
        canonical_rows = list(existing_closed) if isinstance(existing_closed, list) else []
        current_payload: dict[str, Any] | None = None
        before_closed = json.dumps(canonical_rows, sort_keys=True, default=str)

        for index, row in enumerate(rows):
            if not isinstance(row, list) or len(row) < 7:
                continue
            row_open_time = _coerce_int(row[0])
            row_close_time = _coerce_int(row[6])
            if row_open_time is None:
                continue

            is_last = index == len(rows) - 1
            matches_sidecar = (
                source_open_time is not None
                and source_open_time == row_open_time
                and (source_close_time is None or source_close_time == row_close_time)
            )
            treat_as_current = bool(
                is_last
                and (
                    (matches_sidecar and source_closed is False)
                    or (row_close_time is not None and row_close_time >= repair_now_ms)
                )
            )

            if treat_as_current:
                current_ingested_at = max(row_open_time, (row_close_time - 1) if row_close_time is not None else repair_now_ms)
                current_payload = canonical_from_binance_rest(
                    row,
                    symbol=symbol,
                    timeframe=timeframe,
                    ingested_at=current_ingested_at,
                ).to_dict()
                continue

            closed_ingested_at = (row_close_time + 1) if row_close_time is not None else repair_now_ms
            if is_last and matches_sidecar and source_closed is True and source_event_time is not None:
                closed_ingested_at = max(closed_ingested_at, source_event_time)

            payload = canonical_from_binance_rest(
                row,
                symbol=symbol,
                timeframe=timeframe,
                ingested_at=closed_ingested_at,
            ).to_dict()
            canonical_rows = append_closed_candle(canonical_rows, payload)

        after_closed = json.dumps(canonical_rows, sort_keys=True, default=str)
        if canonical_rows and after_closed != before_closed:
            write_json_key(client, target_closed_key, canonical_rows)
            closed_keys_written += 1
            symbols_repaired.add(symbol)

        if current_payload is not None:
            write_json_key(client, current_candle_key(exchange, symbol, timeframe), current_payload)
            current_keys_written += 1

    return {
        "scanned_legacy_keys": scanned_legacy_keys,
        "closed_keys_written": closed_keys_written,
        "current_keys_written": current_keys_written,
        "symbols_repaired": sorted(symbols_repaired),
    }


def read_json_key(client: Any, key: str) -> Any:
    try:
        raw = client.get(key)
    except Exception:
        return None
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def read_legacy_rows_key(client: Any, key: str) -> list[Any] | None:
    direct = read_json_key(client, key)
    if isinstance(direct, list):
        return direct
    try:
        key_type = client.type(key)
    except Exception:
        return None
    if isinstance(key_type, (bytes, bytearray)):
        key_type = key_type.decode("utf-8")
    if str(key_type) != "list":
        return None
    try:
        raw_rows = client.lrange(key, 0, -1)
    except Exception:
        return None

    parsed_rows: list[Any] = []
    for raw in raw_rows:
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except ValueError:
                pass
        parsed_rows.append(raw)
    return parsed_rows


def write_json_key(client: Any, key: str, payload: Any) -> bool:
    try:
        return bool(client.set(key, json.dumps(payload, sort_keys=True, default=str)))
    except Exception:
        return False


def _coerce_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def build_minimal_tensor(
    *,
    symbol: str,
    timeframe: str,
    candle: Mapping[str, Any],
    snapshot: Mapping[str, Any],
) -> FeatureTensorRecord:
    open_price = finite_float(candle.get("open") or (candle.get("ohlcv") or {}).get("open"))
    close_price = finite_float(candle.get("close") or (candle.get("ohlcv") or {}).get("close"))
    high_price = finite_float(candle.get("high") or (candle.get("ohlcv") or {}).get("high"))
    low_price = finite_float(candle.get("low") or (candle.get("ohlcv") or {}).get("low"))
    volume = finite_float(candle.get("volume") or (candle.get("ohlcv") or {}).get("volume"))
    ret_pct = ((close_price - open_price) / open_price) if open_price else 0.0
    range_pct = ((high_price - low_price) / open_price) if open_price else 0.0
    values = (close_price, volume, ret_pct, range_pct)
    tensor_id = "publisher_proof_tensor_" + stable_hash(
        {
            "symbol": symbol,
            "timeframe": timeframe,
            "values": values,
            "mtf_snapshot_id": snapshot.get("mtf_snapshot_id"),
        }
    )[:24]
    return FeatureTensorRecord(
        tensor_id=tensor_id,
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id="publisher_proof_feature_" + tensor_id[-24:],
        values=values,
        missing_mask=(0, 0, 0, 0),
        stale_mask=(0, 0, 0, 0),
        source_availability=(1, 1, 1, 1),
        feature_names=("close", "volume", "ret_pct", "range_pct"),
        source_labels=("canonical_closed_candle",) * 4,
        missing_feature_names=(),
        stale_feature_names=(),
        data_coverage_percent=100.0,
        source_availability_vector=(1, 1, 1, 1),
    )


def build_trust_row(
    *,
    symbol: str,
    timeframe: str,
    tensor: FeatureTensorRecord,
    candle: Mapping[str, Any],
    snapshot: Mapping[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    feature_cutoff = snapshot.get("feature_cutoff")
    available_at = candle.get("available_at")
    close_time = candle.get("candle_close_time") or candle.get("close_time")
    open_time = candle.get("candle_open_time") or candle.get("open_time")
    event_time = candle.get("event_time") or close_time
    return {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "enforcement_epoch": ENFORCEMENT_EPOCH,
        "producer": "run_trusted_prediction_publisher_once",
        "producer_version": TRUST_SCHEMA_VERSION,
        "created_at": generated_at,
        "sample_id": "publisher_proof_" + str(snapshot.get("mtf_snapshot_id")),
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "feature_vector_hash": tensor.tensor_id,
        "feature_freshness_state": "CURRENT",
        "trainer_consumable": False,
        "candle_closed_confirmed": True,
        "closed_candle": True,
        "candle_open_time": iso_ms(open_time),
        "candle_close_time": iso_ms(close_time),
        "source_event_time_est": iso_ms(event_time),
        "source_received_time_est": iso_ms(available_at),
        "source_available_time": iso_ms(available_at),
        "available_at": iso_ms(available_at),
        "feature_cutoff": iso_ms(feature_cutoff),
        "decision_time_est": generated_at,
        "masa_prediction_timestamp": generated_at,
        "ppo_observation_timestamp": generated_at,
        "masa_feature_cutoff": iso_ms(feature_cutoff),
        "ppo_feature_cutoff": iso_ms(feature_cutoff),
        "all_tf_candle_timestamps": list(snapshot.get("all_tf_candle_timestamps") or []),
        "all_source_event_times": list(snapshot.get("all_source_event_times") or []),
        "decision_id": snapshot.get("decision_id"),
        "mtf_snapshot_id": snapshot.get("mtf_snapshot_id"),
        "mtf_snapshot_valid": snapshot.get("valid"),
        "mtf_snapshot_reject_reasons": list(snapshot.get("reject_reasons") or []),
        "multi_timeframe_decision_snapshot": dict(snapshot),
        "features": dict(zip(tensor.feature_names, tensor.values, strict=True)),
        "latency_ms": 0,
        "is_backfilled": False,
        "backfilled": False,
        "source_mode": "live",
    }


def build_feature_evidence(
    *,
    symbol: str,
    timeframe: str,
    tensor: FeatureTensorRecord,
    trust_row: Mapping[str, Any],
    generated_at: str,
) -> dict[str, Any]:
    return {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "producer": "run_trusted_prediction_publisher_once",
        "producer_version": TRUST_SCHEMA_VERSION,
        "generated_at": generated_at,
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_snapshot_id": tensor.feature_snapshot_id,
        "feature_hash": tensor.tensor_id,
        "feature_vector_hash": tensor.tensor_id,
        "feature_cutoff": trust_row.get("feature_cutoff"),
        "decision_time": trust_row.get("decision_time_est"),
        "available_at": trust_row.get("available_at"),
        "feature_timestamp": trust_row.get("feature_cutoff"),
        "source_candle_timestamps": list(trust_row.get("all_tf_candle_timestamps") or []),
        "source_event_times": list(trust_row.get("all_source_event_times") or []),
        "features": dict(zip(tensor.feature_names, tensor.values, strict=True)),
        "feature_names": list(tensor.feature_names),
        "missing_feature_names": list(tensor.missing_feature_names),
        "stale_feature_names": list(tensor.stale_feature_names),
        "missing_feature_count": len(tensor.missing_feature_names),
        "stale_feature_count": len(tensor.stale_feature_names),
        "source_availability_vector": list(tensor.source_availability_vector),
        "data_coverage_percent": tensor.data_coverage_percent,
        "feature_freshness_state": "CURRENT",
        "candle_closed_confirmed": True,
        "is_backfilled": False,
        "backfilled": False,
    }


def hold_model_output() -> ModelForwardResult:
    probabilities = [0.0] * len(ACTION_LABELS)
    probabilities[0] = 1.0
    return ModelForwardResult(
        model_id="publisher_proof_hold_policy_v1",
        model_source=MODEL_SOURCE,
        action_logits=tuple(0.0 for _ in ACTION_LABELS),
        action_probabilities=tuple(probabilities),
        selected_action_index=0,
        selected_action="hold",
        expected_move_bps=0.0,
        confidence_raw=0.0,
        confidence_calibrated=0.0,
        policy_value=0.0,
        masa_signal=0.0,
        calibration={"mode": "publisher_proof_hold_no_trade"},
        device="cpu",
        cuda_active=False,
        model_tensors_device_verified=False,
    )


def finite_float(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    if parsed != parsed or parsed in (float("inf"), float("-inf")):
        return 0.0
    return parsed


def iso_ms(value: Any) -> str:
    parsed = parse_ms(value)
    if parsed is None:
        return utc_now()
    return datetime.fromtimestamp(parsed / 1000.0, tz=timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def fail_result(generated_at: str, reason: str, **extra: Any) -> dict[str, Any]:
    return {
        "success": False,
        "status": "BLOCKED",
        "generated_at": generated_at,
        "reason": reason,
        "routes_to_live": False,
        "live_order_allowed": False,
        **extra,
    }


def write_result(output_root: Path, result: Mapping[str, Any]) -> None:
    output_root.mkdir(parents=True, exist_ok=True)
    path = output_root / "run_trusted_prediction_publisher_once_result.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
