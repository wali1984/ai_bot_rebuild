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
