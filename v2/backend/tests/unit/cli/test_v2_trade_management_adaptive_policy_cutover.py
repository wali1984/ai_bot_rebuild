from __future__ import annotations

import os
import json
from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop


class _RevocableRedis:
    def __init__(self) -> None:
        self.values = {
            paper_loop.PAPER_PORTFOLIO_STATE_REDIS_KEY: json.dumps(
                {
                    "schema_version": "v2_native_portfolio_state_v2",
                    "paper_session_id": "session_1",
                    "equity": 3_000.0,
                    "free_margin_usd": 3_000.0,
                    "used_margin_usd": 0.0,
                    "open_positions": [],
                    "open_positions_count": 0,
                    "equity_trusted": True,
                    "pnl_trusted": True,
                    "contains_live_positions": False,
                }
            ),
            paper_loop.PAPER_SESSION_REDIS_KEY: json.dumps(
                {
                    "paper_session_id": "session_1",
                    "reset_session_id": "session_1",
                    "paper_only": True,
                    "routes_to_live": False,
                    "places_real_order": False,
                }
            ),
            paper_loop.PAPER_POSITIONS_REDIS_KEY: "[]",
            paper_loop.PAPER_CLOSED_TRADES_REDIS_KEY: "[]",
        }

    def get(self, key: str):
        return self.values.get(key)

    def ttl(self, key: str) -> int:
        return -2


def _authorized_intent() -> dict:
    authorization = {
        "schema_version": "adaptive_paper_policy_authorization_v2",
        "authority_id": paper_loop.ADAPTIVE_POLICY_AUTHORITY_ID,
        "selected_action": "directional_trade",
        "primary_side": "long",
        "primary_symbol": "BTCUSDT",
        "primary_timeframe": "15m",
        "policy_trading_action_authority": True,
        "paper_entry_authority": True,
        "hard_validator_passed": True,
        "exact_action_venue_executable": True,
        "mandatory_stop_present": True,
        "static_confidence_final_authority": False,
        "static_loss_final_authority": False,
        "static_microstructure_final_authority": False,
        "static_exit_feasibility_final_authority": False,
        "static_exploration_tier_final_authority": False,
        "paper_only": True,
        "live_gate": "blocked_human_only",
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
        "live_eligible": False,
        "live_submission_ready": False,
        "adaptive_policy_action_id": "action_1",
        "adaptive_policy_action_sha256": "1" * 64,
        "objective_evaluation_id": "evaluation_1",
        "hard_validation_receipt_sha256": "2" * 64,
        "venue_attestation_id": "venue_1",
        "venue_attestation_sha256": "3" * 64,
        "operator_catastrophic_envelope_sha256": "4" * 64,
    }
    authorization_sha256 = paper_loop._paper_canonical_sha256(authorization)
    assert authorization_sha256 is not None
    return {
        "paper_opportunity_tier": paper_loop.PAPER_TIER_ADAPTIVE_POLICY_V2,
        "side": "long",
        "adaptive_paper_policy_authorization": authorization,
        "adaptive_paper_policy_authorization_sha256": authorization_sha256,
        "adaptive_policy_authoritative": True,
        "adaptive_policy_entry_authorized": True,
        "static_category_e_final_authority": False,
        "static_confidence_final_authority": False,
        "static_loss_final_authority": False,
        "static_microstructure_final_authority": False,
        "static_exit_feasibility_final_authority": False,
        "static_exploration_tier_final_authority": False,
        "adaptive_allocation": {
            "adaptive_capital_policy_version": (
                "ADAPTIVE_POLICY_EXACT_PAPER_ALLOCATION_V2"
            ),
            "symbol": "BTCUSDT",
            "timeframe": "15m",
            "action": "long",
            "allocator_decision": "ALLOW_WITH_SIZE",
            "adaptive_policy_authorization_sha256": authorization_sha256,
            "model_inputs": {
                "adaptive_policy_exact_physical_validation_status": "PASS",
                "adaptive_policy_exact_physical_rejection_reasons": [],
                "adaptive_policy_authorization": authorization,
                "adaptive_policy_authorization_sha256": authorization_sha256,
            },
        },
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "exchange_action_taken": False,
    }


def _durable_feature_snapshot() -> dict:
    return {
        "schema_version": "durable_feature_snapshot_archive_record_v1",
        "feature_snapshot_id": "snapshot_1",
        "snapshot_id": "snapshot_1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "available_at": "2026-07-27T23:06:00Z",
        "created_at": "2026-07-27T23:07:00Z",
        "decision_time": "2026-07-27T23:07:00Z",
        "feature_cutoff": "2026-07-27T22:59:59.999Z",
        "candle_closed_confirmed": True,
        "latest_unclosed_kline_excluded": True,
        "latest_unclosed_exclusion_method": "CLOSED_KLINE_FILTER_DECISION_TIME_BOUNDED_V1",
        "latest_unclosed_exclusion_decision_time_ms": 1785193500000,
        "latest_closed_kline_close_time_ms": 1785193199999,
        "trainer_consumable": True,
        "content_sha256": "a" * 64,
        "features": {"close": 100.0},
    }


def test_adaptive_authority_is_the_only_category_e_owner() -> None:
    intent = _authorized_intent()

    assert paper_loop._paper_adaptive_policy_authority_rejection_reasons(intent) == []
    assert paper_loop._paper_policy_owner_open_rejection_reasons(intent) == []
    assert intent["paper_policy_owner_open_allowed"] is True


def test_paper_session_metadata_repairs_nullable_aliases_without_overwriting_conflict() -> None:
    enriched = paper_loop._with_paper_session_metadata(
        {
            "paper_session_id": None,
            "session_id": "",
            "reset_session_id": "conflicting_session",
        },
        paper_session_id="current_session",
        starting_equity_usd=3_000.0,
    )

    assert enriched["paper_session_id"] == "current_session"
    assert enriched["session_id"] == "current_session"
    assert enriched["reset_session_id"] == "conflicting_session"


def test_portfolio_revocable_projection_ignores_shadow_heartbeat_but_not_accounting() -> None:
    base = {
        "schema_version": "paper_exact_redis_json_source_material_v1",
        "source_kind": "REDIS_EXACT_KEY",
        "source_key": paper_loop.PAPER_PORTFOLIO_STATE_REDIS_KEY,
        "expected_container": "mapping",
        "read_status": "READY",
        "present": True,
        "payload": {
            "schema_version": "v2_native_portfolio_state_v2",
            "generated_utc": "2026-07-27T23:00:00Z",
            "shadow_observation_total": 10,
            "positions": [{"position_state": "shadow_observation_only"}],
            "paper_session_id": "session_1",
            "equity": 3_000.0,
            "free_margin_usd": 2_900.0,
            "used_margin_usd": 100.0,
            "reserved_margin_usd": 25.0,
            "paper_account_margin_status": {
                "status": "PASS",
                "used_margin_usd": 100.0,
                "newly_reserved_margin_usd": 25.0,
                "generated_utc": "2026-07-27T23:00:00Z",
            },
            "open_positions": [{"symbol": "BTCUSDT", "quantity": 0.01}],
            "open_positions_count": 1,
            "equity_trusted": True,
            "pnl_trusted": True,
        },
    }
    heartbeat = {
        **base,
        "payload": {
            **base["payload"],
            "generated_utc": "2026-07-27T23:01:00Z",
            "shadow_observation_total": 11,
            "positions": [{"position_state": "shadow_observation_only"}, {}],
            "paper_account_margin_status": {
                **base["payload"]["paper_account_margin_status"],
                "generated_utc": "2026-07-27T23:01:00Z",
            },
        },
    }
    accounting_change = {
        **heartbeat,
        "payload": {**heartbeat["payload"], "used_margin_usd": 101.0},
    }

    projected = paper_loop._paper_revocable_source_control_material(
        "portfolio_state_source", base
    )
    projected_heartbeat = paper_loop._paper_revocable_source_control_material(
        "portfolio_state_source", heartbeat
    )
    projected_accounting = paper_loop._paper_revocable_source_control_material(
        "portfolio_state_source", accounting_change
    )

    assert paper_loop._paper_canonical_sha256(projected) == paper_loop._paper_canonical_sha256(
        projected_heartbeat
    )
    assert paper_loop._paper_canonical_sha256(projected) != paper_loop._paper_canonical_sha256(
        projected_accounting
    )

    reservation_change = {
        **heartbeat,
        "payload": {**heartbeat["payload"], "reserved_margin_usd": 26.0},
    }
    projected_reservation = paper_loop._paper_revocable_source_control_material(
        "portfolio_state_source", reservation_change
    )
    assert paper_loop._paper_canonical_sha256(projected) != paper_loop._paper_canonical_sha256(
        projected_reservation
    )


@pytest.mark.parametrize(
    "reason",
    (
        "ENTRY_GATE_EVALUATION_NOT_ALLOWED",
        "A_PLUS_GATE_ALLOCATION_IDENTITY_MISMATCH",
        "PREEMPTIVE_TIER_DECISION_INVALID:NO_TRADE",
        "CONTROL_SOURCE_CHANGED:adaptive_tuning_source",
        "CURRENT_CONTROL_SOURCE_NOT_READY:continuous_edge_guardian:MISSING",
    ),
)
def test_only_explicit_legacy_category_e_verdicts_are_advisory(reason: str) -> None:
    assert paper_loop._paper_adaptive_static_category_e_advisory_reason(reason) is True


@pytest.mark.parametrize(
    "reason",
    (
        "PAPER_SESSION_REVALIDATION:CURRENT_PAPER_SESSION_CHANGED_FROM_CANDIDATE",
        "CONTROL_SOURCE_CHANGED:portfolio_state_source",
        "FINAL_ADMISSION_CYCLE_RESERVATION_COMMIT_RECEIPT_INVALID",
        "FINAL_ADMISSION_RISK_DECISION_RECORD_MISSING",
        "MAINTENANCE_BRACKET_EVIDENCE_EXPIRED_DURING_FINAL_ADMISSION",
        "NONOVERRIDABLE_PORTFOLIO_TRUTH_FREEZE_ACTIVE",
        "ADAPTIVE_TUNING_REVALIDATION:CANONICAL_PAYLOAD_NUMERIC_INVALID",
    ),
)
def test_hard_authorization_accounting_and_catastrophic_reasons_never_become_advisory(
    reason: str,
) -> None:
    assert paper_loop._paper_adaptive_static_category_e_advisory_reason(reason) is False


def _adaptive_revocable_intent(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict, _RevocableRedis]:
    redis = _RevocableRedis()
    sources = paper_loop._paper_revocable_control_source_materials(redis)
    owner_projection = {
        "schema_version": "paper_runtime_owner_minimal_projection_v1",
        "status": "PASS_ACTIVE_RUNTIME_OWNER_VALIDATION",
        "active_new_entry_owner": "v2_trade_management_paper_loop",
        "canonical_paper_writer_count": 1,
        "canonical_service_scope_writer_count": 1,
        "forbidden_entry_process_count": 0,
        "duplicate_paper_writer_count": 0,
        "current_process_is_only_canonical_writer": True,
        "paper_online_runtime_active": False,
        "paper_online_runtime_enabled": False,
        "canonical_paper_runtime_enabled": True,
        "toy_momentum_entry_writer_active": False,
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
        "pass_conditions": {
            "canonical_paper_writer_count_eq_1": True,
            "canonical_service_scope_writer_count_eq_1": True,
            "current_process_is_only_canonical_writer": True,
            "forbidden_entry_process_count_zero": True,
            "duplicate_paper_writer_count_zero": True,
            "paper_online_runtime_active_false": True,
            "paper_online_runtime_enabled_false": True,
            "canonical_paper_runtime_enabled_true": True,
            "toy_momentum_entry_writer_active_false": True,
            "active_new_entry_owner_is_v2_trade_management_paper_loop": True,
        },
    }
    monkeypatch.setattr(
        paper_loop,
        "_paper_active_runtime_owner_status",
        lambda: {"ignored": True},
    )
    monkeypatch.setattr(
        paper_loop,
        "_paper_runtime_owner_minimal_projection",
        lambda value: owner_projection,
    )
    observed_at = "2026-07-27T23:00:00Z"
    frozen_rows = []
    for role, material in sources.items():
        control_material = paper_loop._paper_revocable_source_control_material(
            role,
            material,
        )
        frozen_rows.append(
            paper_loop._paper_snapshot_lineage(
                role=role,
                redis_key=str(control_material.get("source_key")),
                payload=control_material,
                observed_at=observed_at,
            )
        )
    freeze = paper_loop._compose_paper_entry_freeze({}, json.loads(redis.values[
        paper_loop.PAPER_PORTFOLIO_STATE_REDIS_KEY
    ]))
    risk = paper_loop._paper_current_risk_state_from_sources(sources)
    for role, source, payload in (
        (
            "paper_entry_freeze",
            "IN_PROCESS_COMPOSED_FROM_EXACT_REDIS_FREEZE_AND_PORTFOLIO_SOURCES",
            freeze,
        ),
        (
            "current_risk_state",
            "IN_PROCESS_DERIVED_FROM_EXACT_PAPER_POSITION_AND_PORTFOLIO_SOURCES",
            risk,
        ),
        (
            "paper_runtime_owner",
            "PROCFS_AND_SYSTEMD_CURRENT_PROCESS_OWNER_PROJECTION",
            owner_projection,
        ),
    ):
        frozen_rows.append(
            paper_loop._paper_snapshot_lineage(
                role=role,
                redis_key=source,
                payload=payload,
                observed_at=observed_at,
            )
        )
    return (
        {
            "paper_opportunity_tier": paper_loop.PAPER_TIER_ADAPTIVE_POLICY_V2,
            "adaptive_policy_entry_authorized": True,
            "paper_session_id": "session_1",
            "paper_pre_cycle_control_snapshot": {"lineage": frozen_rows},
        },
        redis,
    )


def test_adaptive_revocable_boundary_keeps_static_controls_advisory_and_session_hard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent, redis = _adaptive_revocable_intent(monkeypatch)
    started = datetime.now(UTC) - timedelta(milliseconds=10)

    receipt = paper_loop._paper_revocable_control_commit_revalidation(
        intent,
        redis_client=redis,
        validation_started_at=started,
    )

    assert receipt["status"] == "PASS"
    assert receipt["rejection_reasons"] == []
    assert receipt["static_category_e_final_authority"] is False
    assert any(
        reason.startswith("CURRENT_CONTROL_SOURCE_NOT_READY:continuous_edge_guardian")
        for reason in receipt["static_category_e_advisory_reasons"]
    )
    assert any(
        reason.startswith("ADAPTIVE_TUNING_")
        for reason in receipt["static_category_e_advisory_reasons"]
    )

    mismatched = {**intent, "paper_session_id": "other_session"}
    blocked = paper_loop._paper_revocable_control_commit_revalidation(
        mismatched,
        redis_client=redis,
        validation_started_at=datetime.now(UTC) - timedelta(milliseconds=10),
    )
    assert blocked["status"] == "BLOCKED"
    assert (
        "PAPER_SESSION_REVALIDATION:CURRENT_PAPER_SESSION_CHANGED_FROM_CANDIDATE"
        in blocked["rejection_reasons"]
    )


def test_static_category_e_reintroduction_fails_closed() -> None:
    intent = _authorized_intent()
    intent["static_microstructure_final_authority"] = True

    reasons = paper_loop._paper_policy_owner_open_rejection_reasons(intent)

    assert "STATIC_CATEGORY_E_AUTHORITY_REINTRODUCED:static_microstructure_final_authority" in reasons
    assert intent["paper_policy_owner_open_allowed"] is False


def test_adaptive_authorization_tamper_fails_closed() -> None:
    intent = _authorized_intent()
    intent["adaptive_paper_policy_authorization"]["primary_side"] = "short"

    reasons = paper_loop._paper_adaptive_policy_authority_rejection_reasons(intent)

    assert "ADAPTIVE_POLICY_AUTHORIZATION_HASH_MISMATCH" in reasons
    assert "ADAPTIVE_POLICY_AUTHORIZED_SIDE_MISMATCH" in reasons


def test_adaptive_directional_identity_rebinds_only_the_authorized_action() -> None:
    intent = _authorized_intent()
    intent.update(
        {
            "side": "hold",
            "action": "hold",
            "selected_action": "hold",
            "predicted_direction": "hold",
        }
    )
    allocation = dict(intent["adaptive_allocation"])

    reasons = paper_loop._paper_bind_adaptive_policy_directional_identity(
        intent=intent,
        allocation=allocation,
        authorization=intent["adaptive_paper_policy_authorization"],
    )

    assert reasons == []
    assert intent["side"] == "long"
    assert intent["action"] == "long"
    assert intent["selected_action"] == "long"
    assert intent["predicted_direction"] == "long"
    assert intent["adaptive_policy_source_action_comparator"] == {
        "side": "hold",
        "action": "hold",
        "selected_action": "hold",
        "predicted_direction": "hold",
        "static_comparator_only": True,
    }


def test_adaptive_directional_identity_mismatch_fails_without_mutation() -> None:
    intent = _authorized_intent()
    intent["side"] = "hold"
    allocation = dict(intent["adaptive_allocation"])
    allocation["action"] = "short"

    reasons = paper_loop._paper_bind_adaptive_policy_directional_identity(
        intent=intent,
        allocation=allocation,
        authorization=intent["adaptive_paper_policy_authorization"],
    )

    assert reasons == ["ADAPTIVE_POLICY_ALLOCATION_SIDE_MISMATCH"]
    assert intent["side"] == "hold"
    assert "adaptive_policy_source_action_comparator" not in intent


def test_adaptive_execution_refresh_rebuilds_partial_fill_ledger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intent = {
        "side": "long",
        "action": "long",
        "selected_action": "long",
        "entry_price": 100.0,
        "fill_price": 100.0,
        "fill_price_utc": "2026-07-27T23:00:00Z",
        "generated_utc": "2026-07-27T23:00:00Z",
        "paper_only": True,
        "routes_to_live": False,
        "places_real_order": False,
    }
    allocation = {
        "adaptive_capital_policy_version": "ADAPTIVE_POLICY_EXACT_PAPER_ALLOCATION_V2",
        "allocation_id": "allocation_1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "action": "long",
        "allocator_decision": "ALLOW_WITH_SIZE",
        "target_notional_usdt": 25.0,
        "target_notional_usd": 25.0,
        "gross_notional_usd": 25.0,
        "target_quantity": 0.25,
        "allocated_margin_usd": 5.0,
        "recommended_leverage": 5.0,
        "effective_leverage": 5.0,
        "recommended_margin_mode": "isolated_paper_simulated",
        "model_inputs": {},
    }
    monkeypatch.setattr(
        paper_loop,
        "_attach_runtime_cost_capture_contract",
        lambda *args, **kwargs: None,
    )

    paper_loop._paper_refresh_adaptive_policy_execution_evidence(
        intent=intent,
        allocation=allocation,
        market_microstructure={},
        mark_index_evidence={},
        signal={},
        prediction={},
    )

    assert intent["adaptive_allocation"] is allocation
    assert intent["partial_fill_count"] == 1
    assert intent["fill_count"] == 1
    assert intent["partial_fills"] == [
        {
            "fill_sequence": 1,
            "quantity": 0.25,
            "price": 100.0,
            "notional_usd": 25.0,
            "fill_time": "2026-07-27T23:00:00Z",
            "source": "PAPER_SINGLE_FILL_LEDGER_RECORD",
            "paper_only": True,
            "places_real_order": False,
        }
    ]


def test_runtime_intent_projection_retains_adaptive_authority_evidence() -> None:
    intent = _authorized_intent()
    intent["adaptive_policy_action"] = {"decision_id": "action_1"}
    intent["legacy_category_e_comparator"] = {"static_comparator_only": True}
    intent["adaptive_policy_source_action_comparator"] = {
        "side": "hold",
        "static_comparator_only": True,
    }

    compact = paper_loop._compact_runtime_intent_for_redis(intent)

    assert compact["adaptive_policy_action"] == {"decision_id": "action_1"}
    assert compact["adaptive_paper_policy_authorization"] == intent[
        "adaptive_paper_policy_authorization"
    ]
    assert compact["adaptive_allocation"]["adaptive_policy_authorization_sha256"] == intent[
        "adaptive_paper_policy_authorization_sha256"
    ]
    assert compact["adaptive_allocation"]["model_inputs"][
        "adaptive_policy_exact_physical_validation_status"
    ] == "PASS"


def test_verified_durable_snapshot_binds_exact_finality_and_clocks() -> None:
    intent = {
        "feature_snapshot_id": "snapshot_1",
        "entry_feature_snapshot_id": "snapshot_1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "decision_time": "2026-07-27T23:10:00Z",
    }

    reasons = paper_loop._paper_bind_verified_durable_feature_snapshot(
        intent=intent,
        snapshot=_durable_feature_snapshot(),
    )

    assert reasons == []
    assert intent["entry_feature_available_at"] == "2026-07-27T23:06:00Z"
    assert intent["entry_feature_generated_at"] == "2026-07-27T23:07:00Z"
    assert intent["entry_feature_cutoff"] == "2026-07-27T22:59:59.999Z"
    assert intent["entry_feature_decision_time"] == "2026-07-27T23:10:00Z"
    assert intent["entry_feature_candle_closed_confirmed"] is True
    assert intent["entry_feature_latest_unclosed_kline_excluded"] is True
    assert intent["entry_feature_snapshot_archive_verified"] is True
    assert intent["entry_feature_snapshot_content_sha256"] == "a" * 64
    market_reasons = paper_loop._paper_runtime_market_evidence_rejection_reasons(
        {
            **intent,
            "entry_price_provenance_present": True,
            "actual_observed_spread_entry_bps": 1.0,
            "expected_slippage_bps": 0.1,
            "expected_slippage_source": "VERIFIED_MODEL",
            "partial_fill_count": 1,
            "partial_fills": [{"quantity": 0.25, "price": 100.0}],
        },
        require_fill_ledger=True,
    )
    assert "MISSING_ENTRY_FEATURE_AVAILABLE_AT" not in market_reasons
    assert "MISSING_ENTRY_FEATURE_GENERATED_AT" not in market_reasons
    assert "MISSING_ENTRY_FEATURE_CUTOFF" not in market_reasons
    assert "ENTRY_FEATURE_CANDLE_NOT_CONFIRMED_CLOSED" not in market_reasons


def test_durable_snapshot_future_generation_blocks_without_binding() -> None:
    intent = {
        "feature_snapshot_id": "snapshot_1",
        "entry_feature_snapshot_id": "snapshot_1",
        "symbol": "BTCUSDT",
        "timeframe": "15m",
        "decision_time": "2026-07-27T23:10:00Z",
    }
    snapshot = _durable_feature_snapshot()
    snapshot["created_at"] = "2026-07-27T23:11:00Z"

    reasons = paper_loop._paper_bind_verified_durable_feature_snapshot(
        intent=intent,
        snapshot=snapshot,
    )

    assert reasons == ["DURABLE_FEATURE_SNAPSHOT_GENERATED_AFTER_DECISION"]
    assert "entry_feature_available_at" not in intent
    assert "entry_feature_snapshot" not in intent


def test_validator_seed_requires_protected_exact_file(tmp_path) -> None:
    seed_path = tmp_path / "seed.cred"
    seed_path.write_bytes(b"a" * 32)
    seed_path.chmod(0o600)
    environ = {paper_loop.ADAPTIVE_POLICY_VALIDATOR_SEED_PATH_ENV: str(seed_path)}

    assert paper_loop._paper_adaptive_validator_seed(environ) == b"a" * 32

    seed_path.chmod(0o640)
    with pytest.raises(RuntimeError, match="PERMISSIONS_TOO_BROAD"):
        paper_loop._paper_adaptive_validator_seed(environ)


def test_feature_archive_root_requires_absolute_directory(tmp_path) -> None:
    assert paper_loop._paper_adaptive_feature_archive_root(
        {paper_loop.ADAPTIVE_POLICY_FEATURE_ARCHIVE_ROOT_ENV: os.fspath(tmp_path)}
    ) == tmp_path

    with pytest.raises(RuntimeError, match="FEATURE_ARCHIVE_ROOT_INVALID"):
        paper_loop._paper_adaptive_feature_archive_root(
            {paper_loop.ADAPTIVE_POLICY_FEATURE_ARCHIVE_ROOT_ENV: "relative"}
        )
