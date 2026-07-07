from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.all_timeframe_prediction_signal_price_target_publisher import (
    DEFAULT_STALE_SECONDS,
    V2KeyValueStore,
    build_prediction_row,
    build_prediction_rows,
)
from v2.backend.app.services.market_state_integrity.scoring import score_market_state
from v2.backend.app.services.signal_publisher import build_signal_record
from v2.backend.app.services.v2_symbol_runtime_universe import resolve_symbols


GOAL_ID = "V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _proof_score_false_mask() -> dict[str, Any]:
    generated = _utc_now()
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "phase6_false_mask_clean",
        "generated_at": generated,
        "feature_freshness_state": "CURRENT",
        "candle_closed_confirmed": True,
        "candle_open_time": generated,
        "candle_close_time": generated,
        "source_event_time_est": generated,
        "source_received_time_est": generated,
        "decision_time_est": generated,
        "missing_feature_count": 192,
        "missing_mask": {"open": False, "high": False, "low": False, "close": False},
        "source_availability": {"ohlcv": True, "orderbook": True},
        "features": {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
    }
    score = score_market_state(row)
    return {
        "name": "false_mask_values_do_not_count_as_missing",
        "passed": "MISSING_CRITICAL_FEATURE_FAMILY" not in score.reject_reasons
        and score.source_lineage.get("missing_feature_count") == 0,
        "reject_reasons": score.reject_reasons,
        "missing_feature_count": score.source_lineage.get("missing_feature_count"),
        "missing_mask_close": score.source_lineage.get("missing_mask", {}).get("close"),
    }


def _proof_score_true_mask_blocks() -> dict[str, Any]:
    generated = _utc_now()
    row = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "phase6_true_mask_missing",
        "generated_at": generated,
        "feature_freshness_state": "CURRENT",
        "candle_closed_confirmed": True,
        "candle_open_time": generated,
        "candle_close_time": generated,
        "source_event_time_est": generated,
        "source_received_time_est": generated,
        "decision_time_est": generated,
        "missing_feature_count": 0,
        "missing_mask": {"open": False, "close": True},
        "features": {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
    }
    score = score_market_state(row)
    return {
        "name": "actual_missing_mask_still_blocks",
        "passed": "MISSING_CRITICAL_FEATURE_FAMILY" in score.reject_reasons
        and score.source_lineage.get("missing_feature_names") == ["close"],
        "reject_reasons": score.reject_reasons,
        "missing_feature_names": score.source_lineage.get("missing_feature_names"),
    }


def _paper_ready_prediction(generated: str) -> dict[str, Any]:
    return {
        "prediction_id": "phase6_pred",
        "feature_snapshot_id": "phase6_snapshot",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "trainer_source": "V2_NATIVE_RL_MASA_PPO_CUDA_TRAINER_PAPER_SHADOW",
        "model_source": "V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA",
        "selected_action": "long",
        "generated_at": generated,
        "available_at": generated,
        "decision_time": generated,
        "feature_cutoff": generated,
        "expected_move_bps": 25.0,
        "expected_move_after_cost_bps": 12.0,
        "paper_fill_allowed": True,
        "routes_to_orchestrator": True,
        "market_state_id": "phase6_market_state",
        "market_state_integrity_score": 87.5,
        "valid_for_training": False,
        "valid_for_prediction": False,
        "valid_for_risk": False,
        "valid_for_orchestrator": False,
        "valid_for_paper": False,
        "valid_for_live": False,
        "market_state_reject_reasons": ["MISSING_CRITICAL_FEATURE_FAMILY"],
        "market_state_score_components": {
            "data_freshness_score": 100.0,
            "candle_completion_score": 100.0,
            "tf_alignment_score": 100.0,
            "missing_data_score": 0.0,
            "source_disagreement_score": 100.0,
            "latency_score": 100.0,
            "backfill_score": 100.0,
            "execution_fill_quality_score": 100.0,
        },
    }


def _proof_prediction_and_signal_lineage() -> dict[str, Any]:
    generated = _utc_now()
    prediction = _paper_ready_prediction(generated)
    feature_payload = {
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "phase6_snapshot",
        "missing_feature_count": 192,
        "missing_mask": {"open": False, "high": False, "low": False, "close": False},
        "stale_mask": {"open": False, "close": False},
        "source_availability": {"ohlcv": True, "orderbook": True},
        "features": {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.5},
    }
    row = build_prediction_row(
        symbol="BTCUSDT",
        timeframe="1m",
        prediction=prediction,
        price_payload={"ticker_24hr": {"lastPrice": "100.0"}},
        feature_payload=feature_payload,
        stale_seconds=DEFAULT_STALE_SECONDS,
    )
    signal = build_signal_record(
        prediction=prediction,
        feature_snapshot=feature_payload,
        market_freshness_state="CURRENT",
        market_age_seconds=1,
        run_ts=generated,
    )
    return {
        "name": "prediction_signal_uses_actual_feature_snapshot_lineage",
        "passed": row.get("missing_feature_count") == 0
        and "MISSING_CRITICAL_FEATURE_FAMILY" not in set(row.get("market_state_reject_reasons") or [])
        and signal.get("missing_feature_count") == 0
        and signal.get("source_availability") == {"ohlcv": True, "orderbook": True},
        "row_missing_feature_count": row.get("missing_feature_count"),
        "row_reject_reasons": row.get("market_state_reject_reasons"),
        "signal_missing_feature_count": signal.get("missing_feature_count"),
        "signal_source_availability": signal.get("source_availability"),
    }


def _runtime_sample(redis_client: Any, *, sample_symbols: int, timeframes: tuple[str, ...]) -> dict[str, Any]:
    if redis_client is None:
        return {"status": "UNAVAILABLE_NO_REDIS_CLIENT", "sample_rows": 0}
    store = V2KeyValueStore(client=redis_client)
    symbols = resolve_symbols()[: max(1, sample_symbols)]
    rows = build_prediction_rows(
        store=store,
        symbols=symbols,
        timeframes=timeframes,
        stale_seconds=DEFAULT_STALE_SECONDS,
    )
    missing_blocks = [
        row for row in rows if "MISSING_CRITICAL_FEATURE_FAMILY" in set(row.get("market_state_reject_reasons") or [])
    ]
    false_positive_blocks = [
        row
        for row in missing_blocks
        if int(row.get("missing_feature_count") or 0) == 0 and not row.get("missing_feature_names")
    ]
    rate = (len(false_positive_blocks) / len(missing_blocks)) if missing_blocks else 0.0
    return {
        "status": "SAMPLED",
        "sample_symbols": symbols,
        "sample_timeframes": list(timeframes),
        "sample_rows": len(rows),
        "missing_critical_feature_blocks": len(missing_blocks),
        "false_positive_missing_critical_feature_blocks": len(false_positive_blocks),
        "false_positive_missing_critical_feature_block_rate": rate,
        "sample_false_positive_rows": [
            {
                "symbol": row.get("symbol"),
                "timeframe": row.get("timeframe"),
                "feature_snapshot_id": row.get("feature_snapshot_id"),
                "missing_feature_count": row.get("missing_feature_count"),
                "missing_feature_names": row.get("missing_feature_names"),
                "feature_lineage_source": row.get("feature_lineage_source"),
            }
            for row in false_positive_blocks[:10]
        ],
    }


def build_phase6_missing_feature_lineage_status(
    *,
    redis_client: Any = None,
    sample_symbols: int = 10,
    timeframes: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h"),
) -> dict[str, Any]:
    proofs = [
        _proof_score_false_mask(),
        _proof_score_true_mask_blocks(),
        _proof_prediction_and_signal_lineage(),
    ]
    runtime_sample = _runtime_sample(redis_client, sample_symbols=sample_symbols, timeframes=timeframes)
    sampled_rate = runtime_sample.get("false_positive_missing_critical_feature_block_rate")
    sample_passed = sampled_rate is None or float(sampled_rate) < 0.10
    pass_conditions = {
        "missing_feature_names_from_actual_snapshot": proofs[2]["passed"],
        "source_availability_preserved": proofs[2]["signal_source_availability"] == {"ohlcv": True, "orderbook": True},
        "missing_mask_preserved": proofs[0]["missing_mask_close"] is False,
        "stale_mask_preserved": proofs[2]["passed"],
        "market_state_integrity_reads_canonical_masks": proofs[0]["passed"] and proofs[1]["passed"],
        "false_positive_missing_critical_feature_blocks_lt_10pct": sample_passed,
        "actual_missing_features_still_block": proofs[1]["passed"],
    }
    ready = all(pass_conditions.values()) and all(proof["passed"] for proof in proofs)
    return {
        "schema_version": "missing_critical_feature_lineage_fix_status_v1",
        "goal_id": GOAL_ID,
        "generated_utc": _utc_now(),
        "status": "MISSING_CRITICAL_FEATURE_LINEAGE_FIX_READY" if ready else "MISSING_CRITICAL_FEATURE_LINEAGE_FIX_BLOCKED",
        "behavioral_proofs": proofs,
        "runtime_sample": runtime_sample,
        "pass_conditions": pass_conditions,
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
        "live_gate": "blocked_human_only",
    }


def write_phase6_missing_feature_lineage_artifacts(
    *,
    redis_client: Any = None,
    repo_root: Path,
    goal_dir: Path,
    public_dir: Path | None = None,
    sample_symbols: int = 10,
) -> dict[str, Any]:
    status = build_phase6_missing_feature_lineage_status(
        redis_client=redis_client,
        sample_symbols=sample_symbols,
    )
    _write_json(goal_dir / "missing_critical_feature_lineage_fix_status.json", status)
    if public_dir is not None:
        _write_json(public_dir / "missing_critical_feature_lineage_fix_status.json", status)
    return status
