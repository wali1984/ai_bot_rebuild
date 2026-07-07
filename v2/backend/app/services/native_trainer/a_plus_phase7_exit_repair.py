from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.paper_trade_management.exits import PaperExitConfig, evaluate_exit
from v2.backend.app.services.paper_trade_management.position_state import PaperNetPosition


GOAL_ID = "V2_A_PLUS_LIVE_READY_TRAINER_EDGE_REPAIR_AND_ZERO_TOLERANCE_TRADE_GATE"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(path)


def _long_position(
    *,
    strategy_selected_mode: str | None = None,
    market_regime_at_entry: str | None = None,
    best_favorable_bps: float | None = None,
) -> PaperNetPosition:
    pos = PaperNetPosition(
        position_id="phase7_pos_BTCUSDT",
        symbol="BTCUSDT",
        side="long",
        net_quantity=0.01,
        avg_entry_price=100_000.0,
        opened_est="2026-07-06T00:00:00Z",
        strategy_selected_mode=strategy_selected_mode,
        market_regime_at_entry=market_regime_at_entry,
    )
    if best_favorable_bps is not None:
        pos.best_favorable_price = 100_000.0 * (1 + best_favorable_bps / 10000.0)
    return pos


def _mark_for_pnl_bps(pnl_bps: float) -> float:
    return 100_000.0 * (1 + pnl_bps / 10000.0)


def _proof_atr_stop_floor() -> dict[str, Any]:
    config = PaperExitConfig(
        static_stop_loss_enabled=False,
        atr_stop_floor_bps=35.0,
        catastrophic_floor_stop_bps=150.0,
        mfe_breakeven_protection_enabled=False,
        min_hold_seconds=0,
    )
    result = evaluate_exit(
        position=_long_position(strategy_selected_mode="trend_mode"),
        mark_price=_mark_for_pnl_bps(-40.0),
        generated_utc="2026-07-06T00:10:00Z",
        config=config,
        atr_bps=7.0,
    )
    return {
        "name": "compressed_atr_uses_35bps_floor",
        "passed": result.get("close_reason") == "TIER_1_ATR_VOLATILITY_STOP"
        and result.get("atr_stop_bps") == 35.0
        and result.get("atr_stop_floor_applied") is True,
        "result": result,
    }


def _proof_regime_scaled_atr_stop() -> dict[str, Any]:
    config = PaperExitConfig(
        static_stop_loss_enabled=False,
        atr_stop_floor_bps=0.0,
        catastrophic_floor_stop_bps=150.0,
        mfe_breakeven_protection_enabled=False,
        min_hold_seconds=0,
    )
    hold_result = evaluate_exit(
        position=_long_position(strategy_selected_mode="trend_mode", market_regime_at_entry="VOLATILE_EXPANSION"),
        mark_price=_mark_for_pnl_bps(-70.0),
        generated_utc="2026-07-06T00:10:00Z",
        config=config,
        atr_bps=20.0,
        regime="VOLATILE_EXPANSION",
    )
    close_result = evaluate_exit(
        position=_long_position(strategy_selected_mode="trend_mode", market_regime_at_entry="VOLATILE_EXPANSION"),
        mark_price=_mark_for_pnl_bps(-80.0),
        generated_utc="2026-07-06T00:10:00Z",
        config=config,
        atr_bps=20.0,
        regime="VOLATILE_EXPANSION",
    )
    return {
        "name": "volatile_expansion_widens_trend_atr_stop",
        "passed": hold_result.get("should_close") is False
        and close_result.get("close_reason") == "TIER_1_ATR_VOLATILITY_STOP"
        and close_result.get("atr_stop_bps") == 78.0,
        "hold_result": hold_result,
        "close_result": close_result,
    }


def _proof_missing_atr_floor_fallback() -> dict[str, Any]:
    config = PaperExitConfig(
        static_stop_loss_enabled=False,
        atr_stop_floor_bps=35.0,
        catastrophic_floor_stop_bps=150.0,
        mfe_breakeven_protection_enabled=False,
        min_hold_seconds=0,
    )
    result = evaluate_exit(
        position=_long_position(),
        mark_price=_mark_for_pnl_bps(-40.0),
        generated_utc="2026-07-06T00:10:00Z",
        config=config,
        atr_bps=None,
    )
    return {
        "name": "missing_atr_falls_back_to_floor_stop",
        "passed": result.get("close_reason") == "TIER_1_ATR_VOLATILITY_STOP"
        and result.get("atr_missing_floor_fallback") is True,
        "result": result,
    }


def _proof_mfe_breakeven_protection() -> dict[str, Any]:
    config = PaperExitConfig(
        static_stop_loss_enabled=False,
        atr_stop_floor_bps=0.0,
        catastrophic_floor_stop_bps=0.0,
        mfe_breakeven_protection_enabled=True,
        mfe_breakeven_min_mfe_bps=20.0,
        mfe_breakeven_cost_buffer_bps=8.0,
        min_hold_seconds=0,
        trailing_stop_enabled=False,
    )
    protected = evaluate_exit(
        position=_long_position(best_favorable_bps=35.0),
        mark_price=_mark_for_pnl_bps(5.0),
        generated_utc="2026-07-06T00:10:00Z",
        config=config,
        atr_bps=None,
    )
    deep_loss = evaluate_exit(
        position=_long_position(best_favorable_bps=35.0),
        mark_price=_mark_for_pnl_bps(-286.0),
        generated_utc="2026-07-06T00:10:00Z",
        config=config,
        atr_bps=None,
    )
    return {
        "name": "mfe_breakeven_protects_near_breakeven_not_deep_losses",
        "passed": protected.get("close_reason") == "TIER_2_MFE_BREAKEVEN_PROTECTION"
        and deep_loss.get("close_reason") != "TIER_2_MFE_BREAKEVEN_PROTECTION",
        "protected_result": protected,
        "deep_loss_result": deep_loss,
    }


def _proof_model_reversal_precedes_atr_stop() -> dict[str, Any]:
    config = PaperExitConfig(
        static_stop_loss_enabled=False,
        atr_stop_floor_bps=35.0,
        catastrophic_floor_stop_bps=150.0,
        mfe_breakeven_protection_enabled=False,
        min_hold_seconds=0,
    )
    result = evaluate_exit(
        position=_long_position(),
        mark_price=_mark_for_pnl_bps(-5.0),
        generated_utc="2026-07-06T00:10:00Z",
        config=config,
        atr_bps=20.0,
        model_context={"model_reversal": True},
    )
    return {
        "name": "model_reversal_exit_fires_before_atr_stop",
        "passed": result.get("close_reason") == "TIER_1_MODEL_REVERSAL_EXIT",
        "result": result,
    }


def _proof_atr_loser_bucket_quarantine() -> dict[str, Any]:
    from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop

    def _loss(ts: str) -> dict[str, Any]:
        return {
            "paper_only": True,
            "symbol": "SOLUSDT",
            "timeframe": "1m",
            "side": "long",
            "strategy_id": "range_scalp",
            "market_regime": "RANGING",
            "confidence_calibrated": 0.74,
            "gross_notional_usd": 25.0,
            "realized_pnl_bps": -9.0,
            "realized_pnl_usd": -0.05,
            "close_reason": "TIER_1_ATR_VOLATILITY_STOP",
            "exit_price_utc": ts,
        }

    status = paper_loop._paper_bucket_quarantine_status(  # noqa: SLF001
        [_loss("2099-01-01T00:00:00Z"), _loss("2099-01-01T00:05:00Z")],
        generated_utc="2099-01-01T00:10:00Z",
    )
    first_bucket = (status.get("quarantined_buckets") or [{}])[0]
    return {
        "name": "atr_loser_cluster_quarantines_matching_bucket",
        "passed": status.get("status") == "ACTIVE_WITH_QUARANTINES"
        and "ATR_STOP_LOSS_CLUSTER" in set(first_bucket.get("block_reasons") or [])
        and status.get("places_real_order") is False,
        "bucket_status": status,
    }


def build_phase7_exit_repair_status(*, repair_deployed_utc: str | None = None) -> dict[str, Any]:
    deployed = repair_deployed_utc or _utc_now()
    proofs = [
        _proof_atr_stop_floor(),
        _proof_regime_scaled_atr_stop(),
        _proof_missing_atr_floor_fallback(),
        _proof_mfe_breakeven_protection(),
        _proof_model_reversal_precedes_atr_stop(),
        _proof_atr_loser_bucket_quarantine(),
    ]
    passed = all(proof["passed"] for proof in proofs)
    pass_conditions = {
        "atr_cluster_no_longer_irrecoverable_pre_repair_losses_excluded": passed,
        "atr_stop_floor_active": proofs[0]["passed"],
        "stop_multiplier_by_regime_active": proofs[1]["passed"],
        "missing_atr_floor_fallback_active": proofs[2]["passed"],
        "mfe_protection_active": proofs[3]["passed"],
        "model_reversal_exit_quality_active": proofs[4]["passed"],
        "bucket_quarantine_for_atr_losers_active": proofs[5]["passed"],
        "paper_entry_freeze_clear_allowed_only_after_exit_repair_test_passes": passed,
    }
    return {
        "schema_version": "a_plus_phase7_exit_repair_status_v1",
        "goal_id": GOAL_ID,
        "generated_utc": _utc_now(),
        "repair_deployed_utc": deployed,
        "repair_test_passed": passed,
        "status": "ATR_STOP_CLUSTER_REPAIR_READY" if passed else "ATR_STOP_CLUSTER_REPAIR_BLOCKED",
        "root_cause": "ATR stop cluster made the 50-trade gate irrecoverable before adaptive exit repair",
        "repairs": [
            "ATR stop floor",
            "regime-aware ATR stop scaling",
            "missing-ATR floor fallback",
            "MFE breakeven protection",
            "model reversal exit precedence",
            "ATR-loser bucket quarantine",
        ],
        "behavioral_proofs": proofs,
        "pass_conditions": pass_conditions,
        "paper_entry_freeze_clear_allowed_by_exit_repair": passed,
        "paper_entry_freeze_mutated": False,
        "no_threshold_lowering": True,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "test_order_submitted": False,
        "exchange_leverage_mutated": False,
        "exchange_margin_mutated": False,
        "writes_legacy_redis": False,
        "live_gate": "blocked_human_only",
    }


def write_phase7_exit_repair_artifacts(
    *,
    repo_root: Path,
    goal_dir: Path,
    public_dir: Path | None = None,
    repair_deployed_utc: str | None = None,
) -> dict[str, Any]:
    status = build_phase7_exit_repair_status(repair_deployed_utc=repair_deployed_utc)
    adaptive_exit = {
        **status,
        "schema_version": "adaptive_exit_repair_status_v1",
        "status": "ADAPTIVE_EXIT_REPAIR_READY" if status["repair_test_passed"] else "ADAPTIVE_EXIT_REPAIR_BLOCKED",
    }
    mfe_status = {
        **status,
        "schema_version": "mfe_protection_status_v1",
        "status": "MFE_PROTECTION_READY" if status["pass_conditions"]["mfe_protection_active"] else "MFE_PROTECTION_BLOCKED",
    }
    payloads = {
        "atr_stop_cluster_repair_status.json": status,
        "adaptive_exit_repair_status.json": adaptive_exit,
        "mfe_protection_status.json": mfe_status,
    }
    for name, payload in payloads.items():
        _write_json(goal_dir / name, payload)
        if public_dir is not None:
            _write_json(public_dir / name, payload)
    return status
