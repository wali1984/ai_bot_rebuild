from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from v2.backend.app.cli import v2_adaptive_allocation_trade_lifecycle_24h_paper_soak as soak


class FakeRedis:
    def __init__(self, payloads: dict[str, Any]) -> None:
        self.payloads = payloads
        self.writes: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str) -> str | None:
        if key not in self.payloads:
            return None
        return json.dumps(self.payloads[key])

    def set(self, *args: Any, **kwargs: Any) -> None:
        self.writes.append(("set", args, kwargs))
        raise AssertionError("soak observer must not write Redis")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _path(root: Path, absolute_template: Path) -> Path:
    return root / absolute_template.relative_to(soak.REPO_ROOT)


def _seed_runtime_files(root: Path, *, static_sizing: bool = False, closed_count: int = 1) -> None:
    paper_runtime = _path(root, soak.PAPER_RUNTIME_DIR)
    adaptive_gate = _path(root, soak.ADAPTIVE_GATE_DIR)
    paper_gate = _path(root, soak.PAPER_GATE_DIR)
    _write_json(
        paper_runtime / "paper_adaptive_sizing_runtime_status.json",
        {
            "paper_candidates_with_allocation": 3,
            "accepted_allocation_count": 2,
            "blocked_allocation_count": 1,
            "static_trade_size_used": static_sizing,
            "sample_allocations": [
                {"target_notional_usdt": 25.0, "allocator_decision": "ALLOW_WITH_SIZE"},
                {"target_notional_usdt": 37.5, "allocator_decision": "ALLOW_WITH_SIZE"},
                {"target_notional_usdt": 0.0, "allocator_decision": "BLOCK_NO_EDGE"},
            ],
            "allocator_decision_counts": {"ALLOW_WITH_SIZE": 2, "BLOCK_NO_EDGE": 1},
        },
    )
    _write_json(
        paper_runtime / "paper_position_lifecycle_status.json",
        {
            "open_positions_count": 1,
            "closed_positions_count": closed_count,
            "outcome_label_count": closed_count,
            "state_machine": "NEW_SIGNAL->ENTRY_CHECK->OPEN_POSITION->HOLD->REDUCE->CLOSE->CLOSED->OUTCOME_LABEL_WRITTEN",
        },
    )
    _write_json(
        paper_runtime / "paper_position_exposure_cap_status.json",
        {
            "blocked_count": 0,
            "evaluations": [
                {
                    "symbol": "BTCUSDT",
                    "current_symbol_notional": 25.0,
                    "candidate_notional": 0.0,
                    "computed_max_symbol_notional_usdt": 800.0,
                    "total_open_notional": 25.0,
                    "computed_max_total_notional_usdt": 6000.0,
                }
            ],
        },
    )
    _write_json(
        paper_runtime / "paper_hedge_netting_status.json",
        {
            "accidental_hedge_pairs_allowed": False,
            "same_side_netting_count": 1,
            "opposite_side_netting_count": 1,
        },
    )
    _write_json(
        paper_runtime / "paper_exit_coordinator_status.json",
        {
            "tiers_enabled": ["TIER_0", "TIER_1", "TIER_2", "TIER_3", "TIER_4"],
            "close_reasons": {"TIER_2_TAKE_PROFIT": closed_count},
        },
    )
    _write_json(
        paper_runtime / "paper_stop_takeprofit_trailing_status.json",
        {
            "stop_loss_bps": 80.0,
            "take_profit_bps": 120.0,
            "trailing_stop_bps": 60.0,
            "triggered_count": closed_count,
        },
    )
    _write_json(
        paper_runtime / "paper_closed_trade_outcome_label_status.json",
        {
            "closed_trade_count": closed_count,
            "outcome_label_count": closed_count,
            "trainer_feedback_rows_ready": closed_count,
        },
    )
    _write_json(
        paper_runtime / "risk_envelope_dynamic_budget_status.json",
        {
            "equity": 10000.0,
            "equity_source": "v2:portfolio:state",
            "drawdown_bps": 0.0,
            "operator_envelope_type": "PERCENTAGE_BASED_RISK_ENVELOPE",
            "static_trade_size_used": static_sizing,
            "fixed_200_usdt_runtime_sizing": static_sizing,
        },
    )
    _write_json(
        paper_runtime / "trade_lifecycle_guard_status.json",
        {"shared_guard_available": True, "paper_path_using_lifecycle_controls": True},
    )
    _write_json(
        paper_runtime / "paper_outcome_labels.json",
        {"outcome_labels": [{"symbol": "BTCUSDT", "realized_pnl_bps": 10.0}] * closed_count},
    )
    _write_json(
        adaptive_gate / "adaptive_sizing_static_constant_scan_status.json",
        {"current_runtime_static_sizing_remove_count": 1 if static_sizing else 0},
    )
    _write_json(
        adaptive_gate / "live_adaptive_sizing_pre_submit_status.json",
        {
            "uses_adaptive_allocator": True,
            "live_submit_changed": False,
            "submit_allowed_without_margin": False,
            "insufficient_margin_blocker_preserved": "INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER",
            "test_order_endpoint_attempted": False,
            "leverage_changed": False,
            "margin_mode_changed": False,
        },
    )
    _write_json(paper_gate / "operator_dashboard_payload.json", {"paper_trade_management_ready": True})


def _redis_payloads(
    *,
    closed_count: int = 1,
    outcome_count: int | None = None,
    feedback_count: int | None = None,
) -> dict[str, Any]:
    outcome_total = closed_count if outcome_count is None else outcome_count
    feedback_total = closed_count if feedback_count is None else feedback_count
    closed_rows = [
        {
            "symbol": "BTCUSDT",
            "realized_pnl_usd": 0.5,
            "realized_pnl_bps": 20.0,
            "close_reason": "TIER_2_TAKE_PROFIT",
        }
        for _ in range(closed_count)
    ]
    return {
        "v2:paper:positions": [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "net_quantity": 0.01,
                "avg_entry_price": 2500.0,
                "notional": 25.0,
                "unrealized_pnl": 0.25,
                "opened_utc": "2026-06-10T23:55:00Z",
                "last_mark_price": 2525.0,
                "last_mark_est": "2026-06-10T19:59:00-04:00",
            }
        ],
        "v2:paper:closed_trades": closed_rows,
        "v2:paper:outcome_labels": [
            {"symbol": "BTCUSDT", "realized_pnl_bps": 20.0, "winner": True}
            for _ in range(outcome_total)
        ],
        "v2:trainer:feedback:outcomes": [
            {"symbol": "BTCUSDT", "realized_pnl_bps": 20.0}
            for _ in range(feedback_total)
        ],
    }


def _dense_observations(base: dict[str, Any], *, start: datetime, seconds: int, count: int) -> list[dict[str, Any]]:
    if count <= 1:
        return [{**base, "observed_utc": soak._iso(start), "observed_est": soak._est_iso(soak._iso(start))}]
    rows: list[dict[str, Any]] = []
    for index in range(count):
        offset = round(index * seconds / (count - 1))
        observed_at = start + timedelta(seconds=offset)
        rows.append(
            {
                **base,
                "observed_utc": soak._iso(observed_at),
                "observed_est": soak._est_iso(soak._iso(observed_at)),
            }
        )
    return rows


def test_status_ready_to_observe_before_12h_without_claiming_completion(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    observation = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads()),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    status = soak.build_soak_status([observation], generated_utc=observation["observed_utc"])

    assert status["generated_utc"] == observation["observed_utc"]
    assert status["generated_est"] == "2026-06-10T20:00:00-04:00"
    assert status["gate"] == soak.READY_GATE
    assert status["proof_status"] == "PENDING_12H_OBSERVATION"
    assert status["completion_marker"] is None
    assert status["soak_24h_complete"] is False
    assert status["first_observation_est"] == "2026-06-10T20:00:00-04:00"
    assert status["latest_observation_est"] == "2026-06-10T20:00:00-04:00"
    assert status["elapsed_seconds"] == 0
    assert status["soak_window_label"] == "12h"
    assert status["soak_required_seconds"] == 12 * 3600
    assert status["soak_12h_complete"] is False
    assert status["density_window_elapsed_seconds"] == 0
    assert status["observation_density_status"] == "INSUFFICIENT_OBSERVATION_DENSITY"
    assert status["last_observation_freshness_status"] == "CLEAR"
    assert status["success_criteria"]["closed_trades_gt_0"] is True
    assert status["success_criteria"]["no_fixed_runtime_sizing_appears"] is True
    assert status["high_severity_alerts"] == []
    assert status["latest_metrics"]["paper_allocation_distribution"]["count"] == 2
    assert status["latest_metrics"]["paper_equity"] == 10000.0
    assert status["latest_metrics"]["paper_equity_source"] == "v2:portfolio:state"
    assert status["latest_metrics"]["open_positions_count"] == 1
    assert status["latest_metrics"]["closed_positions_count"] == 1
    assert status["latest_metrics"]["outcome_label_count"] == 1
    assert status["latest_metrics"]["trainer_feedback_row_count"] == 1
    assert status["latest_metrics"]["same_symbol_stack_status"] == "CLEAR"
    assert status["latest_metrics"]["same_symbol_hedge_status"] == "CLEAR"
    assert status["latest_metrics"]["static_sizing_regression_status"] == "CLEAR"
    assert status["latest_metrics"]["live_balance_hold_status"] == "CLEAR"


def test_collect_observation_uses_current_portfolio_equity_when_risk_equity_zero(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    paper_runtime = _path(tmp_path, soak.PAPER_RUNTIME_DIR)
    portfolio_state = _path(tmp_path, soak.PORTFOLIO_STATE_DIR)
    _write_json(
        paper_runtime / "risk_envelope_dynamic_budget_status.json",
        {
            "equity": 0.0,
            "equity_source": "stale_zero_risk_envelope",
            "drawdown_bps": 0.0,
            "operator_envelope_type": "PERCENTAGE_BASED_RISK_ENVELOPE",
        },
    )
    _write_json(
        portfolio_state / "v2_portfolio_state.json",
        {
            "equity": 10027.5223659,
            "generated_utc": "2026-06-14T09:41:52Z",
            "realized_pnl_usd": -15.6150225,
            "unrealized_pnl_usd": 43.13738839,
        },
    )

    observation = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads()),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert observation["paper_equity"] == 10027.5223659
    assert observation["paper_equity_source"] == "operator_runtime:v2_portfolio_state.equity"
    status = soak.build_soak_status([observation], generated_utc=observation["observed_utc"])
    assert status["latest_metrics"]["paper_equity"] == 10027.5223659
    assert status["latest_metrics"]["paper_equity_source"] == "operator_runtime:v2_portfolio_state.equity"


def test_collect_observation_uses_portfolio_open_positions_when_redis_positions_missing(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    portfolio_state = _path(tmp_path, soak.PORTFOLIO_STATE_DIR)
    _write_json(
        portfolio_state / "v2_portfolio_state.json",
        {
            "equity": 10063.47,
            "open_positions": [
                {
                    "symbol": "AAVEUSDT",
                    "position_state": "accepted_paper_fill_open",
                    "open_position": True,
                    "side": "short",
                    "quantity": -7.8,
                    "notional": 675.0,
                    "entry_price": 66.67,
                    "latest_price": 65.44,
                    "unrealized_pnl_usd": 9.7,
                    "source_fill_ids": ["fill_a"],
                },
                {
                    "symbol": "BCHUSDT",
                    "position_state": "accepted_paper_fill_open",
                    "open_position": True,
                    "side": "short",
                    "quantity": -2.6,
                    "notional": 600.0,
                    "entry_price": 208.16,
                    "latest_price": 198.93,
                    "unrealized_pnl_usd": 24.4,
                    "source_fill_ids": ["fill_b"],
                },
            ],
        },
    )
    redis_payloads = _redis_payloads()
    del redis_payloads["v2:paper:positions"]

    observation = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(redis_payloads),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    status = soak.build_soak_status([observation], generated_utc=observation["observed_utc"])

    assert observation["position_source"] == "operator_runtime:v2_portfolio_state.open_positions"
    assert observation["raw_redis_position_row_count"] == 0
    assert observation["canonical_redis_position_row_count"] == 0
    assert observation["portfolio_position_row_count"] == 2
    assert observation["canonical_portfolio_position_row_count"] == 2
    assert observation["open_positions_count"] == 2
    assert observation["total_paper_exposure_usdt"] == 1275.0
    assert observation["unrealized_pnl_usd"] == 34.1
    assert observation["same_symbol_stack_status"] == "CLEAR"
    assert observation["same_symbol_hedge_status"] == "CLEAR"
    assert status["latest_metrics"]["position_source"] == "operator_runtime:v2_portfolio_state.open_positions"
    assert status["latest_metrics"]["open_positions_count"] == 2
    assert status["latest_metrics"]["canonical_portfolio_position_row_count"] == 2


def test_status_completes_after_12h_when_success_criteria_hold(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    first = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads()),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    start = datetime(2026, 6, 11, tzinfo=timezone.utc)
    observations = _dense_observations(first, start=start, seconds=12 * 3600, count=116)
    status = soak.build_soak_status(
        observations,
        generated_utc=observations[-1]["observed_utc"],
        interval_seconds=300,
    )

    assert status["gate"] == soak.READY_GATE
    assert status["proof_status"] == "SOAK_12H_COMPLETE"
    assert status["completion_marker"] == soak.COMPLETE_READY_GATE
    assert status["soak_complete"] is True
    assert status["soak_12h_complete"] is True
    assert status["soak_24h_complete"] is False
    assert status["density_window_elapsed_seconds"] == 12 * 3600
    assert status["expected_observations"] == 144
    assert status["minimum_required_observations"] == 115
    assert status["density_eligible_observation_count"] == 116
    assert status["observation_density_status"] == "CLEAR"
    assert status["last_observation_freshness_status"] == "CLEAR"


def test_elapsed_time_without_observation_density_stays_pending(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    first = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads()),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    second = {**first, "observed_utc": soak._iso(datetime(2026, 6, 12, tzinfo=timezone.utc))}
    status = soak.build_soak_status(
        [first, second],
        generated_utc=second["observed_utc"],
        interval_seconds=300,
    )

    assert status["gate"] == soak.READY_GATE
    assert status["proof_status"] == "PENDING_12H_OBSERVATION"
    assert status["completion_marker"] is None
    assert status["elapsed_seconds"] == 24 * 3600
    assert status["density_window_elapsed_seconds"] == 24 * 3600
    assert status["density_eligible_observation_count"] == 2
    assert status["observation_density_status"] == "INSUFFICIENT_OBSERVATION_DENSITY"
    assert status["soak_12h_complete"] is False
    assert status["soak_24h_complete"] is False


def test_stale_latest_observation_stays_pending(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    first = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads()),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    start = datetime(2026, 6, 11, tzinfo=timezone.utc)
    observations = _dense_observations(first, start=start, seconds=12 * 3600, count=116)
    generated_utc = soak._iso(start + timedelta(seconds=12 * 3600 + 601))
    status = soak.build_soak_status(
        observations,
        generated_utc=generated_utc,
        interval_seconds=300,
    )

    assert status["gate"] == soak.READY_GATE
    assert status["proof_status"] == "PENDING_12H_OBSERVATION"
    assert status["completion_marker"] is None
    assert status["observation_density_status"] == "CLEAR"
    assert status["last_observation_freshness_status"] == "STALE_LAST_OBSERVATION"
    assert status["last_observation_age_seconds"] == 601
    assert status["soak_12h_complete"] is False
    assert status["soak_24h_complete"] is False


def test_resolved_safety_breach_restarts_clean_proof_window(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    clean = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads()),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    start = datetime(2026, 6, 11, tzinfo=timezone.utc)
    breached = {
        **clean,
        "observed_utc": soak._iso(start),
        "observed_est": soak._est_iso(soak._iso(start)),
        "position_stale_status": "BREACH_POSITION_OPEN_BEYOND_MAX_HOLD",
        "max_position_age_seconds": 21624,
    }
    resolved = {
        **clean,
        "observed_utc": soak._iso(start + timedelta(seconds=300)),
        "observed_est": soak._est_iso(soak._iso(start + timedelta(seconds=300))),
        "open_positions": [],
        "open_positions_count": 0,
        "position_stale_status": "CLEAR",
        "max_position_age_seconds": None,
    }

    status = soak.build_soak_status(
        [breached, resolved],
        generated_utc=resolved["observed_utc"],
        interval_seconds=300,
    )

    assert status["gate"] == soak.READY_GATE
    assert status["proof_status"] == "PENDING_12H_OBSERVATION"
    assert status["completion_marker"] is None
    assert status["high_severity_alerts"] == []
    assert status["historical_high_severity_alerts"] == ["PAPER_POSITION_STALE_BEYOND_EXIT_RULES"]
    assert status["last_safety_breach_alerts"] == ["PAPER_POSITION_STALE_BEYOND_EXIT_RULES"]
    assert status["proof_window_reset_reason"] == "SAFETY_BREACH_RESOLVED_RESTARTED_PROOF_WINDOW"
    assert status["observation_count"] == 1
    assert status["total_observation_count"] == 2
    assert status["density_window_elapsed_seconds"] == 0


def test_static_sizing_regression_blocks_gate(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path, static_sizing=True)
    observation = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads()),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    status = soak.build_soak_status([observation], generated_utc=observation["observed_utc"])

    assert status["gate"] == soak.BLOCKED_GATE
    assert "STATIC_RUNTIME_SIZING_REGRESSION" in status["dangerous_blockers"]
    assert "STATIC_RUNTIME_SIZING_REGRESSION" in status["high_severity_alerts"]
    assert status["completion_marker"] == soak.COMPLETE_BLOCKED_GATE


def test_missing_closed_trade_feedback_stays_pending_not_faked(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path, closed_count=0)
    observation = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads(closed_count=0)),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    status = soak.build_soak_status([observation], generated_utc=observation["observed_utc"])

    assert status["gate"] == soak.READY_GATE
    assert status["soak_24h_complete"] is False
    assert status["success_criteria"]["closed_trades_gt_0"] is False
    assert status["success_criteria"]["outcome_labels_gt_0"] is False
    assert status["success_criteria"]["trainer_feedback_rows_gt_0"] is False


def test_closed_trade_without_outcome_label_blocks_gate(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path, closed_count=0)
    observation = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(_redis_payloads(closed_count=1, outcome_count=0, feedback_count=0)),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    status = soak.build_soak_status([observation], generated_utc=observation["observed_utc"])

    assert status["gate"] == soak.BLOCKED_GATE
    assert "CLOSED_TRADES_WITHOUT_OUTCOME_LABELS" in status["high_severity_alerts"]
    assert status["completion_marker"] == soak.COMPLETE_BLOCKED_GATE


def test_raw_accepted_fill_rows_do_not_count_as_open_positions(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path, closed_count=1)
    raw_fill_rows = [
        {
            "symbol": "BTCUSDT",
            "side": "long",
            "quantity": 1.0,
            "entry_price": 100.0,
            "paper_fill_allowed": True,
            "decision": "ACCEPTED_PAPER_FILL",
        },
        {
            "symbol": "BTCUSDT",
            "side": "short",
            "quantity": 1.0,
            "entry_price": 101.0,
            "paper_fill_allowed": True,
            "decision": "ACCEPTED_PAPER_FILL",
        },
    ]
    redis_payloads = _redis_payloads()
    redis_payloads["v2:paper:positions"] = raw_fill_rows
    observation = soak.collect_observation(
        root=tmp_path,
        redis_client=FakeRedis(redis_payloads),
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )
    status = soak.build_soak_status([observation], generated_utc=observation["observed_utc"])

    assert observation["raw_redis_position_row_count"] == 2
    assert observation["canonical_redis_position_row_count"] == 0
    assert observation["position_source"] == "redis:v2:paper:positions.raw_rows_ignored"
    assert observation["open_positions_count"] == 1
    assert observation["same_symbol_stack_status"] == "CLEAR"
    assert observation["same_symbol_hedge_status"] == "CLEAR"
    assert status["gate"] == soak.READY_GATE
    assert status["high_severity_alerts"] == []


def test_run_once_writes_public_artifacts_without_redis_writes(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    fake_redis = FakeRedis(_redis_payloads())

    status = soak.run_once(
        root=tmp_path,
        redis_client=fake_redis,
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    public_dir = _path(tmp_path, soak.PUBLIC_DIR)
    runtime_dir = _path(tmp_path, soak.RUNTIME_DIR)
    assert status["gate"] == soak.READY_GATE
    assert (public_dir / "GO_NO_GO.md").read_text(encoding="utf-8").strip() == soak.READY_GATE
    assert (public_dir / "soak_status.json").exists()
    assert (runtime_dir / "soak_observations.jsonl").exists()
    assert fake_redis.writes == []


def test_run_once_ignores_pre_position_schema_observations(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    fake_redis = FakeRedis(_redis_payloads())
    runtime_dir = _path(tmp_path, soak.RUNTIME_DIR)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    (runtime_dir / soak.OBSERVATION_JSONL).write_text(
        json.dumps(
            {
                "observed_utc": "2026-06-10T00:00:00Z",
                "same_symbol_stack_status": "BREACH_UNCONTROLLED_SAME_SYMBOL_STACKING",
                "same_symbol_hedge_status": "BREACH_ACCIDENTAL_SAME_SYMBOL_HEDGE",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    status = soak.run_once(
        root=tmp_path,
        redis_client=fake_redis,
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    assert status["gate"] == soak.READY_GATE
    assert status["high_severity_alerts"] == []
    assert status["observation_count"] == 1


def test_run_once_filters_density_by_observation_run_id(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path)
    fake_redis = FakeRedis(_redis_payloads())

    soak.run_once(
        root=tmp_path,
        redis_client=fake_redis,
        now=datetime(2026, 6, 11, 0, 0, tzinfo=timezone.utc),
        observation_run_id="old_run",
    )
    status = soak.run_once(
        root=tmp_path,
        redis_client=fake_redis,
        now=datetime(2026, 6, 11, 1, 0, tzinfo=timezone.utc),
        observation_run_id="new_run",
    )

    runtime_dir = _path(tmp_path, soak.RUNTIME_DIR)
    rows = [
        json.loads(line)
        for line in (runtime_dir / soak.OBSERVATION_JSONL).read_text(encoding="utf-8").splitlines()
    ]
    assert {row["observation_run_id"] for row in rows} == {"old_run", "new_run"}
    assert status["observation_count"] == 1
    assert status["first_observation_utc"] == "2026-06-11T01:00:00Z"
    assert fake_redis.writes == []


def test_run_once_writes_blocked_completion_artifacts_on_breach(tmp_path: Path) -> None:
    _seed_runtime_files(tmp_path, static_sizing=True)
    fake_redis = FakeRedis(_redis_payloads())

    status = soak.run_once(
        root=tmp_path,
        redis_client=fake_redis,
        now=datetime(2026, 6, 11, tzinfo=timezone.utc),
    )

    public_dir = _path(tmp_path, soak.PUBLIC_DIR)
    assert status["completion_marker"] == soak.COMPLETE_BLOCKED_GATE
    assert (public_dir / "GO_NO_GO.md").read_text(encoding="utf-8").strip() == soak.COMPLETE_BLOCKED_GATE
    assert (public_dir / "adaptive_allocation_24h_distribution.json").exists()
    assert (public_dir / "paper_lifecycle_24h_exposure_status.json").exists()
    assert (public_dir / "paper_lifecycle_24h_exit_status.json").exists()
    assert (public_dir / "paper_lifecycle_24h_outcome_labels_status.json").exists()
    assert (public_dir / "trainer_feedback_24h_status.json").exists()
    assert (public_dir / "paper_pnl_24h_status.json").exists()
    assert (public_dir / "soak_24h_final_operator_dashboard_payload.json").exists()
    assert fake_redis.writes == []
