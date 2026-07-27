from __future__ import annotations

import os

import pytest

from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop


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
