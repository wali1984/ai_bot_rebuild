from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.v2 import control_center_status as v2_control_center_status
from app.api.v2 import market_contracts as v2_market_contracts
from app.api.v2 import realtime as v2_realtime
from app.api.v2 import ui as v2_ui
from app.main import create_app


class FakeRedis:
    def __init__(self) -> None:
        self.kv: dict[str, str] = {}
        self.set_calls: list[tuple[str, str]] = []

    def get(self, key: str) -> str | None:
        return self.kv.get(key)

    def set(self, key: str, value: Any) -> bool:
        self.kv[key] = value if isinstance(value, str) else json.dumps(value)
        self.set_calls.append((key, self.kv[key]))
        return True

    def ping(self) -> bool:
        return True


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    redis = FakeRedis()
    monkeypatch.setattr(v2_control_center_status, "get_redis", lambda: redis)
    monkeypatch.setattr(v2_market_contracts, "get_redis", lambda: redis)
    monkeypatch.setattr(v2_ui, "get_redis", lambda: redis)
    monkeypatch.setattr(v2_realtime, "get_redis", lambda: redis)
    return redis


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _seed_unproven_a_grade_runtime_blockers(fake_redis: FakeRedis) -> None:
    fake_redis.kv["v2:trainer:hybrid_cuda:status"] = json.dumps({
        "online_learning_status": "BLOCKED_NO_DURABLE_WEIGHT_UPDATE",
        "effective_trainer_mode": "REPLAY_AND_ONLINE_LEARNING",
        "learning_metrics": {
            "ppo_entropy": 0.96,
            "train_val_generalization_gap": 3.2,
            "validation_supervised_loss": 6.7,
            "validation_supervised_loss_before": 2.4,
            "validation_supervised_loss_after": 6.7,
            "validation_loss_delta": 4.3,
            "loss_after": 2.4,
            "checkpoint_promotion_reason": "VALIDATION_LOSS_REGRESSED",
            "checkpoint_promotion_rejected": True,
            "hard_promotion_rejection_reason": True,
        },
    })
    fake_redis.kv["v2:paper:a_grade_gate_burndown_status"] = json.dumps({
        "status": "A_GRADE_GATE_ACTIVE_BLOCKED_SOURCE_OWNED",
        "A_grade_rows": 0,
        "near_A_grade_rows": 31,
        "guardian_status": "A_GRADE_HALTED_PERFORMANCE",
        "guardian_new_entries_allowed": False,
        "closest_gap_reason": "NO_STRICT_A_GRADE_SUPPLY",
    })
    fake_redis.kv["v2:paper:preemptive_edge_control_status"] = json.dumps({
        "candidate_count": 2,
        "accepted_count": 0,
    })
    fake_redis.kv["v2:paper:preemptive_candidate_decision_matrix"] = json.dumps({
        "rows": [
            {
                "pre_trade_loss_probability": 0.92,
                "expected_edge_after_cost_bps": -1.0,
                "recent_bucket_profit_factor": 0.03,
                "block_reasons": [
                    "GUARDIAN_HALTED_OR_MISSING",
                    "EXPECTED_EDGE_AFTER_COST_NON_POSITIVE",
                ],
            },
            {
                "pre_trade_loss_probability": 0.91,
                "expected_edge_after_cost_bps": 0.0,
                "recent_bucket_profit_factor": 0.2,
                "block_reasons": ["NEGATIVE_BUCKET_HEALTH"],
            },
        ]
    })
    fake_redis.kv["v2:paper:exploration:supply_status"] = json.dumps({
        "fresh_strategy_supply_rows": 565,
        "fresh_exploration_candidates": 3,
        "materialized_positions_last_cycle": 0,
    })
    fake_redis.kv[
        "v2:paper:exploration:materialization_queue_status"
    ] = json.dumps({
        "queued_count": 0,
        "active_count": 0,
        "same_cycle_materialized_count": 0,
        "rejected_after_queue_count": 3,
        "exact_no_fill_reason": "MIXED_TRUE_NO_FILL_AFTER_QUEUE_CONSUMPTION",
        "canonical_exact_no_fill_reason": "MIXED_TRUE_NO_FILL_AFTER_QUEUE_CONSUMPTION",
        "after_queue_exact_no_fill_reason": "MIXED_TRUE_NO_FILL_AFTER_QUEUE_CONSUMPTION",
        "after_queue_no_fill_reasons": [
            "TRUE_RISK_BLOCK_AFTER_QUEUE_CONSUMPTION",
            "TRUE_ENTRY_GATE_SYMBOL_EXCLUDED_AFTER_QUEUE_CONSUMPTION",
        ],
        "rejected_after_queue_reason_counts": {
            "TRUE_RISK_BLOCK_AFTER_QUEUE_CONSUMPTION": 2,
            "TRUE_ENTRY_GATE_SYMBOL_EXCLUDED_AFTER_QUEUE_CONSUMPTION": 1,
        },
    })
    fake_redis.kv["v2:continuous_edge_guardian:a_grade_execution_gate"] = json.dumps({
        "status": "A_GRADE_HALTED_PERFORMANCE",
        "a_grade_new_entries_allowed": False,
    })


def test_ui_portfolio_returns_canonical_pnl_contract(client: TestClient, fake_redis: FakeRedis) -> None:
    fake_redis.kv["v2:portfolio:state"] = json.dumps({
        "generated_utc": "2026-07-09T00:00:00Z",
        "paper_session_id": "paper-session-test",
        "starting_equity_usd": 3000.0,
        "equity": 3000.68,
        "realized_net_pnl_usd": 0.68,
        "unrealized_pnl_usd": 0.0,
        "closed_trade_count": 1,
    })

    response = client.get("/api/v2/ui/portfolio")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_ui_snapshot_v1"
    assert body["resource"] == "portfolio"
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False
    payload = body["payload"]
    assert payload["schema_version"] == "canonical_pnl_v1"
    assert payload["equity_usd"] == 3000.68
    assert payload["paper_equity_usd"] == 3000.68
    assert payload["paper_realized_pnl_usd"] == 0.68
    assert payload["paper_unrealized_pnl_usd"] == 0.0
    assert payload["paper_total_pnl_usd"] == 0.68
    assert payload["net_pnl_usd"] == 0.68
    assert payload["data_source"] == "v2:portfolio:state"
    assert payload["staleness_seconds"] is not None
    assert payload["reconciliation_status"] == "PASS"
    assert payload["paper_only"] is True


def test_ui_provider_cards_do_not_allow_heartbeat_only_green(client: TestClient, fake_redis: FakeRedis) -> None:
    fake_redis.kv["v2:provider:coinglass:health"] = json.dumps({
        "status": "GREEN",
        "dashboard_color": "green",
        "heartbeat_only": True,
        "actual_payload_count": 0,
    })

    response = client.get("/api/v2/ui/providers")
    assert response.status_code == 200
    providers = response.json()["payload"]["providers"]
    coinglass = next(card for card in providers if card["provider"] == "coinglass")
    assert coinglass["heartbeat_only"] is True
    assert coinglass["dashboard_color"] == "yellow"
    assert coinglass["subscription_tier"] == "unknown"
    assert isinstance(coinglass["endpoints_active"], list)
    assert isinstance(coinglass["endpoints_disabled"], list)
    assert coinglass["raw_key_exposed"] is False
    assert coinglass["places_real_order"] is False


def test_control_center_required_status_aliases_return_json_contracts(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    fake_redis.kv["v2:provider:coinglass:health"] = json.dumps({
        "status": "GREEN",
        "dashboard_color": "green",
        "heartbeat_only": False,
        "actual_payload_count": 2,
        "consumer_roles": ["trainer", "risk", "UI"],
    })
    fake_redis.kv["v2:live_canary:status"] = json.dumps({
        "schema_version": "v2_live_canary_status_v1",
        "generated_utc": "2026-07-09T00:00:00Z",
        "go_no_go": "NO_A_PLUS_CANDIDATE",
        "dry_run": True,
        "real_order_attempted": False,
        "real_order_submitted": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "live_gate": "blocked_human_only",
    })
    fake_redis.kv["v2:paper:a_plus_gate:status"] = json.dumps({
        "schema_version": "v2_paper_a_plus_gate_status_v1",
        "generated_utc": "2026-07-09T00:00:00Z",
        "evaluated_candidates": 2,
        "a_plus_candidates": 0,
        "rejected_reason_matrix": {
            "RISK_CONTROLLER_BLOCKED_MAX_LOSS_UNKNOWN": 2,
            "INSUFFICIENT_PROFIT_FACTOR_EVIDENCE": 1,
        },
        "candidate_matrix": [
            {"symbol": "BTCUSDT", "a_plus": False, "failed_checks": ["allocator_allows"]},
            {"symbol": "ETHUSDT", "a_plus": False, "failed_checks": ["risk_allows"]},
        ],
    })

    expectations = {
        "/api/v2/providers/status": "control_center_provider_status_v1",
        "/api/v2/control-center/status": "control_center_status_v1",
        "/api/v2/control-center": "control_center_status_v1",
        "/api/v2/live-canary/status": "control_center_live_canary_status_v1",
        "/api/v2/a-plus/inventory": "control_center_a_plus_inventory_v1",
    }
    for path, schema_version in expectations.items():
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        assert body["schema_version"] == schema_version
        assert body["canonical_owner"] == path
        assert body["live_gate"] == "blocked_human_only"
        assert body["places_real_order"] is False
        assert body["routes_to_live"] is False
        assert body["data_quality_status"] in {"fresh", "degraded", "stale", "partial"}
        assert isinstance(body["data"], dict)

    a_plus = client.get("/api/v2/a-plus/inventory").json()["data"]
    assert a_plus["a_plus_candidates"] == 0
    assert a_plus["exact_no_a_plus_reason"] == "RISK_CONTROLLER_BLOCKED_MAX_LOSS_UNKNOWN"
    assert a_plus["top_a_plus_blockers"][0] == "RISK_CONTROLLER_BLOCKED_MAX_LOSS_UNKNOWN"
    assert a_plus["counts_as_final_a_plus"] is False
    assert len(a_plus["candidate_matrix_preview"]) == 2

    live_canary = client.get("/api/v2/live-canary/status").json()["data"]
    assert live_canary["dry_run"] is True
    assert live_canary["no_mutation_flags"]["real_order_submitted"] is False
    assert live_canary["no_mutation_flags"]["places_real_order"] is False


def test_control_center_routes_expose_a_grade_blocker_truth(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    _seed_unproven_a_grade_runtime_blockers(fake_redis)

    for path in ("/api/v2/control-center/status", "/api/v2/control-center"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        body = response.json()
        data = body["data"]
        readiness = data["real_trader_readiness"]

        assert body["schema_version"] == "control_center_status_v1"
        assert body["canonical_owner"] == path
        assert body["live_gate"] == "blocked_human_only"
        assert body["routes_to_live"] is False
        assert body["places_real_order"] is False
        assert data["status"] == "A_GRADE_BLOCKED_LIVE_BLOCKED"
        assert data["top_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
        assert readiness["live_ready"] is False
        assert readiness["live_submit_allowed"] is False
        assert readiness["exact_no_live_reason"] == "A_GRADE_SUPPLY_ZERO"
        assert readiness["readiness_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
        assert "VALIDATION_LOSS_REGRESSED" in readiness["readiness_blockers"]
        assert "BLOCKED_NO_DURABLE_WEIGHT_UPDATE" in readiness["readiness_blockers"]
        assert "GUARDIAN_HALTED_PERFORMANCE" in readiness["readiness_blockers"]
        assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in readiness["readiness_blockers"]
        assert data["a_grade_blocker_truth"]["status"] == (
            "A_GRADE_ADAPTATION_NOT_PROVEN"
        )
        assert data["a_grade_blocker_truth"]["paper_learning_feeder"][
            "no_fill_component_reasons"
        ] == [
            "TRUE_RISK_BLOCK_AFTER_QUEUE_CONSUMPTION",
            "TRUE_ENTRY_GATE_SYMBOL_EXCLUDED_AFTER_QUEUE_CONSUMPTION",
        ]
        feeder_finding = next(
            finding
            for finding in data["a_grade_blocker_truth"]["findings"]
            if finding["id"] == "PAPER_OUTCOME_FEEDER_STARVED_BY_TRUE_GATES"
        )
        assert feeder_finding["after_queue_no_fill_reasons"] == [
            "TRUE_RISK_BLOCK_AFTER_QUEUE_CONSUMPTION",
            "TRUE_ENTRY_GATE_SYMBOL_EXCLUDED_AFTER_QUEUE_CONSUMPTION",
        ]
        assert data["a_grade_blocker_truth"]["routes_to_live"] is False
        assert data["a_grade_blocker_truth"]["places_real_order"] is False


def test_a_plus_inventory_prefers_runtime_a_grade_blockers_over_legacy_reason(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    fake_redis.kv["v2:paper:a_plus_gate:status"] = json.dumps({
        "schema_version": "v2_paper_a_plus_gate_status_v1",
        "generated_utc": "2026-07-09T00:00:00Z",
        "evaluated_candidates": 2,
        "a_plus_candidates": 0,
        "rejected_reason_matrix": {"exit_plan_valid": 2},
        "candidate_matrix": [
            {
                "symbol": "BTCUSDT",
                "a_plus": False,
                "failed_checks": ["exit_plan_valid"],
            }
        ],
    })
    _seed_unproven_a_grade_runtime_blockers(fake_redis)

    response = client.get("/api/v2/a-plus/inventory")
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["a_plus_candidates"] == 0
    assert data["exact_no_a_plus_reason"] == "A_GRADE_SUPPLY_ZERO"
    assert data["top_a_plus_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
    assert "VALIDATION_LOSS_REGRESSED" in data["top_a_plus_blockers"]
    assert "BLOCKED_NO_DURABLE_WEIGHT_UPDATE" in data["top_a_plus_blockers"]
    assert "GUARDIAN_HALTED_PERFORMANCE" in data["top_a_plus_blockers"]
    assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in data["top_a_plus_blockers"]
    assert data["legacy_exact_no_a_plus_reason"] == "exit_plan_valid"
    assert data["a_grade_blocker_truth"]["status"] == "A_GRADE_ADAPTATION_NOT_PROVEN"
    assert data["a_grade_blocker_truth"]["a_grade"]["A_grade_rows"] == 0
    assert data["a_grade_blocker_truth"]["routes_to_live"] is False
    assert data["a_grade_blocker_truth"]["places_real_order"] is False


def test_live_canary_status_overrides_stale_ready_pending_with_a_grade_truth(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    fake_redis.kv["v2:live_canary:status"] = json.dumps({
        "schema_version": "v2_live_canary_status_v1",
        "generated_utc": "2026-07-09T00:00:00Z",
        "why_none": "V2_24H_LIVE_CANARY_READY_PENDING_CODEX",
        "dry_run": True,
        "real_order_attempted": False,
        "real_order_submitted": False,
        "test_order_submitted": False,
        "leverage_changed": False,
        "margin_mode_changed": False,
        "live_gate": "blocked_human_only",
    })
    _seed_unproven_a_grade_runtime_blockers(fake_redis)

    response = client.get("/api/v2/live-canary/status")
    assert response.status_code == 200
    data = response.json()["data"]

    assert data["why_none"] == "A_GRADE_SUPPLY_ZERO"
    assert data["legacy_why_none"] == "V2_24H_LIVE_CANARY_READY_PENDING_CODEX"
    assert "GUARDIAN_HALTED_PERFORMANCE" in data["why_none_detail"]
    assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in data["why_none_detail"]
    assert data["a_plus_candidates"] == 0
    assert data["live_ready_candidates"] == 0
    assert data["live_gate"] == "blocked_human_only"
    assert data["order_submitted"] is False
    assert data["test_order_submitted"] is False
    assert data["leverage_mutated"] is False
    assert data["margin_mutated"] is False
    assert data["no_mutation_flags"]["real_order_submitted"] is False
    assert data["no_mutation_flags"]["test_order_submitted"] is False
    assert data["no_mutation_flags"]["places_real_order"] is False
    assert data["no_mutation_flags"]["routes_to_live"] is False


def test_market_live_readiness_alias_exposes_a_grade_blocker_truth(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    _seed_unproven_a_grade_runtime_blockers(fake_redis)

    response = client.get("/api/v2/live/readiness")
    assert response.status_code == 200
    body = response.json()
    data = body["data"]

    assert body["live_gate"] == "blocked_human_only"
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False
    assert data["live_ready"] is False
    assert data["live_submit_allowed"] is False
    assert data["exact_no_live_reason"] == "A_GRADE_SUPPLY_ZERO"
    assert data["readiness_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
    assert "GUARDIAN_HALTED_PERFORMANCE" in data["readiness_blockers"]
    assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in data["readiness_blockers"]
    assert data["a_grade_blocker_truth"]["status"] == "A_GRADE_ADAPTATION_NOT_PROVEN"
    assert data["a_grade_blocker_truth"]["a_grade"]["A_grade_rows"] == 0
    assert data["a_grade_blocker_truth"]["routes_to_live"] is False
    assert data["a_grade_blocker_truth"]["places_real_order"] is False


def test_mobile_risk_status_real_trader_readiness_exposes_a_grade_blockers(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    _seed_unproven_a_grade_runtime_blockers(fake_redis)

    response = client.get("/api/v2/mobile/risk-status")
    assert response.status_code == 200
    data = response.json()
    readiness = data["real_trader_readiness"]

    assert readiness["live_ready"] is False
    assert readiness["live_submit_allowed"] is False
    assert readiness["exact_no_live_reason"] == "A_GRADE_SUPPLY_ZERO"
    assert readiness["readiness_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
    assert "GUARDIAN_HALTED_PERFORMANCE" in readiness["readiness_blockers"]
    assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in readiness["readiness_blockers"]
    assert readiness["a_grade_blocker_truth"]["status"] == (
        "A_GRADE_ADAPTATION_NOT_PROVEN"
    )
    assert readiness["a_grade_blocker_truth"]["routes_to_live"] is False
    assert readiness["a_grade_blocker_truth"]["places_real_order"] is False
    assert data["top_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
    assert data["routes_to_live"] is False
    assert data["places_real_order"] is False


def test_paper_trader_routes_expose_a_grade_blocker_truth(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    _seed_unproven_a_grade_runtime_blockers(fake_redis)

    for path in (
        "/api/v2/paper/status",
        "/api/v2/paper/activity",
        "/api/v2/paper/fills",
    ):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        data = body["data"]
        readiness = data["real_trader_readiness"]

        assert body["live_gate"] == "blocked_human_only"
        assert body["routes_to_live"] is False
        assert body["places_real_order"] is False
        assert readiness["live_ready"] is False
        assert readiness["live_submit_allowed"] is False
        assert readiness["exact_no_live_reason"] == "A_GRADE_SUPPLY_ZERO"
        assert readiness["readiness_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
        assert "VALIDATION_LOSS_REGRESSED" in readiness["readiness_blockers"]
        assert "BLOCKED_NO_DURABLE_WEIGHT_UPDATE" in readiness["readiness_blockers"]
        assert "GUARDIAN_HALTED_PERFORMANCE" in readiness["readiness_blockers"]
        assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in readiness["readiness_blockers"]
        assert readiness["a_grade_blocker_truth"]["status"] == (
            "A_GRADE_ADAPTATION_NOT_PROVEN"
        )
        assert readiness["a_grade_blocker_truth"]["routes_to_live"] is False
        assert readiness["a_grade_blocker_truth"]["places_real_order"] is False
        assert data["top_blockers"][0] == "A_GRADE_SUPPLY_ZERO"


def test_risk_and_paper_runtime_routes_expose_a_grade_blocker_truth(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    _seed_unproven_a_grade_runtime_blockers(fake_redis)
    fake_redis.kv["v2:risk:gateway:heartbeat"] = json.dumps({
        "worker_id": "risk-gateway-test",
        "finished_at": "2026-07-09T00:00:00Z",
        "classification": "V2_RISK_GATEWAY_LIVE_OK",
        "current_gate_state": "blocked_human_only",
        "live_gate": "blocked_human_only",
        "approves_live": False,
        "live_blocked": True,
        "fail_closed": True,
        "places_real_order": False,
    })
    fake_redis.kv["v2:risk:active_profile"] = json.dumps({
        "profile_id": "runtime-risk-profile-test",
        "profile_name": "Runtime risk controls",
        "fields": {},
    })
    fake_redis.kv["v2:paper:heartbeat"] = json.dumps({
        "worker_id": "v2_trade_management_paper_loop",
        "heartbeat_generated_at": "2026-07-09T00:00:00Z",
        "writes_legacy_redis": False,
    })

    for path in (
        "/api/v2/risk/status",
        "/api/v2/risk",
        "/api/v2/paper/runtime-status",
    ):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        data = body.get("data") if isinstance(body.get("data"), dict) else body
        readiness = data["real_trader_readiness"]

        assert body["live_gate"] == "blocked_human_only"
        assert body["routes_to_live"] is False
        assert body["places_real_order"] is False
        assert data["top_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
        assert readiness["live_ready"] is False
        assert readiness["live_submit_allowed"] is False
        assert readiness["exact_no_live_reason"] == "A_GRADE_SUPPLY_ZERO"
        assert readiness["readiness_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
        assert "GUARDIAN_HALTED_PERFORMANCE" in readiness["readiness_blockers"]
        assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in readiness["readiness_blockers"]
        assert data["a_grade_blocker_truth"]["status"] == (
            "A_GRADE_ADAPTATION_NOT_PROVEN"
        )
        assert data["a_grade_blocker_truth"]["routes_to_live"] is False
        assert data["a_grade_blocker_truth"]["places_real_order"] is False


def test_orchestrator_and_adaptive_capital_expose_a_grade_blocker_truth(
    client: TestClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _seed_unproven_a_grade_runtime_blockers(fake_redis)
    fake_redis.kv["v2:orchestrator:heartbeat"] = json.dumps({
        "worker_id": "orchestrator-test",
        "finished_at": "2026-07-09T00:00:00Z",
        "classification": "ORCHESTRATOR_RUNTIME_ACTIVE",
        "live_gate": "blocked_human_only",
        "approves_live": False,
        "cannot_bypass_risk_gateway": True,
    })
    fake_redis.kv["v2:orchestrator:decisions"] = json.dumps([
        {
            "decision_id": "orchestrator-decision-test",
            "generated_utc": "2026-07-09T00:00:00Z",
            "deconflict_reason": "WAIT_FOR_A_GRADE_SUPPLY",
            "approves_live": False,
        }
    ])

    monkeypatch.setattr(
        v2_market_contracts,
        "_adaptive_capital_compact_payload",
        lambda: (
            {
                "capital_productivity_runtime_status": {"status": "ACTIVE"},
                "adaptive_capital_policy_status": {"status": "ACTIVE"},
                "counterfactual_capital_sweep_status": {"status": "ACTIVE"},
                "signal_prediction_accuracy_status": {"status": "ACTIVE"},
            },
            "test:adaptive-capital",
            "2026-07-09T00:00:00Z",
        ),
    )

    for path in (
        "/api/v2/orchestrator/status",
        "/api/v2/orchestrator",
        "/api/v2/adaptive-capital/dashboard",
        "/api/v2/allocator/status",
        "/api/v2/allocator",
    ):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        data = body["data"]
        readiness = data["real_trader_readiness"]

        assert body["live_gate"] == "blocked_human_only"
        assert body["routes_to_live"] is False
        assert body["places_real_order"] is False
        assert data["top_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
        assert readiness["live_ready"] is False
        assert readiness["live_submit_allowed"] is False
        assert readiness["exact_no_live_reason"] == "A_GRADE_SUPPLY_ZERO"
        assert readiness["readiness_blockers"][0] == "A_GRADE_SUPPLY_ZERO"
        assert "GUARDIAN_HALTED_PERFORMANCE" in readiness["readiness_blockers"]
        assert "PREEMPTIVE_LOSS_PROBABILITY_TOO_HIGH" in readiness["readiness_blockers"]
        assert data["a_grade_blocker_truth"]["status"] == (
            "A_GRADE_ADAPTATION_NOT_PROVEN"
        )
        assert data["a_grade_blocker_truth"]["routes_to_live"] is False
        assert data["a_grade_blocker_truth"]["places_real_order"] is False


def test_current_signals_alias_returns_signal_json_not_spa_html(
    client: TestClient,
    fake_redis: FakeRedis,
) -> None:
    fake_redis.kv["v2:signals:paper:BTCUSDT:5m"] = json.dumps({
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "action": "LONG",
        "confidence": 0.72,
        "price_target_after_cost": 101000.0,
        "paper_fill_allowed": False,
        "paper_fill_status": "PAPER_FILL_GATE_BLOCKED",
        "risk_state": "BLOCKED_HUMAN_ONLY",
        "signal_id": "signal-current-test",
        "prediction_id": "prediction-current-test",
        "live_gate": "blocked_human_only",
    })

    response = client.get("/api/v2/signals/current?symbol=BTCUSDT")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    body = response.json()
    assert body["schema_version"] == "api_v2_readonly_envelope_v1"
    assert body["canonical_owner"] == "/api/v2/signals/current"
    assert body["endpoint"] == "/api/v2/signals/current?symbol=BTCUSDT"
    assert body["places_real_order"] is False
    assert body["routes_to_live"] is False
    assert body["data"]["active_signal"]["signal_id"] == "signal-current-test"


def test_ui_ai_brain_exposes_page_contract_without_live_routes(client: TestClient, fake_redis: FakeRedis) -> None:
    fake_redis.kv["v2:altdata:provider_consumption_status"] = json.dumps({
        "provider_tensor_consumption": True,
        "confluence_trade_block_score": 0.2,
        "confluence_reduce_size_score": 0.1,
        "confluence_hedge_required_score": 0.0,
        "provider_contribution_last_50": {"status": "current", "sample_count": 50},
    })
    fake_redis.kv["v2:provider:coinglass:feature_bridge_status"] = json.dumps({
        "feature_count": 12,
        "actual_payload_count": 3,
        "heartbeat_only": False,
    })
    fake_redis.kv["v2:provider:moralis:feature_bridge_status"] = json.dumps({
        "feature_count": 10,
        "actual_payload_count": 2,
        "heartbeat_only": False,
    })

    response = client.get("/api/v2/ui/ai-brain")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_ui_snapshot_v1"
    assert body["resource"] == "ai_brain"
    payload = body["payload"]
    contract = payload["ai_page_contract"]
    assert contract["schema_version"] == "enterprise_ai_page_contract_v1"
    assert contract["ppo_tensor_provider_features"] is True
    assert contract["masa_tensor_provider_features"] is True
    assert contract["provider_feature_count_by_provider"]["coinglass"] == 12
    assert contract["provider_feature_count_by_provider"]["moralis"] == 10
    assert contract["routes_to_live"] is False
    assert contract["places_real_order"] is False
    assert payload["routes_to_live"] is False
    assert payload["places_real_order"] is False


def test_realtime_bootstrap_returns_all_resources(client: TestClient, fake_redis: FakeRedis) -> None:
    response = client.get("/api/v2/realtime/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "enterprise_realtime_bootstrap_v1"
    assert body["live_gate"] == "blocked_human_only"
    assert body["routes_to_live"] is False
    assert body["places_real_order"] is False
    for resource in (
        "dashboard",
        "markets",
        "ai_brain",
        "risk",
        "portfolio",
        "providers",
        "system_health",
        "trader_cockpit",
    ):
        assert resource in body["resources"]
        assert body["resources"][resource]["schema_version"] == "enterprise_ui_snapshot_v1"


def test_realtime_health_and_resource_registry(client: TestClient, fake_redis: FakeRedis) -> None:
    health = client.get("/api/v2/realtime/health").json()
    assert health["status"] == "ok"
    assert health["one_socket_per_session"] is True
    assert health["readonly_path_multiplexing"] is True
    assert health["websocket_endpoint"] == "/api/v2/realtime/ws"
    assert health["places_real_order"] is False

    resources = client.get("/api/v2/realtime/resources").json()
    assert resources["schema_version"] == "enterprise_realtime_resources_v1"
    assert {row["name"] for row in resources["resources"]} >= {"dashboard", "portfolio", "providers"}
    assert resources["one_socket_per_session"] is True
    assert resources["readonly_path_multiplexing"] is True


def test_realtime_websocket_multiplexes_readonly_resource_paths(
    client: TestClient,
    fake_redis: FakeRedis,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(path: str, headers: dict[str, str]) -> dict[str, Any]:
        return {
            "data": {"path": path, "ok": True},
            "source": path,
            "source_type": "api",
            "endpoint": path,
            "timestamp": "2026-07-09T00:00:00Z",
            "received_at": "2026-07-09T00:00:00Z",
            "lag_ms": 0,
            "stale": False,
            "missing_fields": [],
            "warnings": [],
            "mode": "read_only",
        }

    monkeypatch.setattr(v2_realtime, "_readonly_resource_resolve_payload", fake_resolve)

    with client.websocket_connect(
        "/api/v2/realtime/ws?resources=portfolio&path=/api/v2/portfolio&path_interval_ms=5000",
    ) as websocket:
        bootstrap = websocket.receive_json()
        assert bootstrap["type"] == "bootstrap"

        path_frame = None
        for _ in range(6):
            frame = websocket.receive_json()
            if frame["type"] == "resource_path_delta":
                path_frame = frame
                break
        assert path_frame is not None
        assert path_frame["path"] == "/api/v2/portfolio"
        assert path_frame["payload"]["transport"] == "websocket"
        assert path_frame["payload"]["data"]["ok"] is True
        assert path_frame["payload"].get("places_real_order") is not True
