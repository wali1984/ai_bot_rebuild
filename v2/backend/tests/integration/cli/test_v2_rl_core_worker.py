"""Integration tests for v2_rl_core_worker and the RL core service.

Paper-only. No network IO. No Redis. No PyTorch.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from v2.backend.app.cli import v2_rl_core_worker
from v2.backend.app.services.rl_core import (
    LEGACY_OBS_SHA256,
    RLCoreService,
    V2_OBSERVATION_SCHEMA,
    calibrate_confidence,
    compute_constrained_reward,
    observation_field_names,
    parse_legacy_checkpoint_filename,
)


# --------------------------------------------------------------------------- #
# Observation schema
# --------------------------------------------------------------------------- #
def test_observation_schema_has_expected_fields() -> None:
    names = observation_field_names()
    # Must include the high-signal V2 fields the prompt called out
    expected_subset = {
        "price_norm",
        "atr_pct",
        "volume_zscore",
        "funding_rate",
        "oi_change_pct",
        "regime_trend",
        "regime_range",
        "regime_chop",
        "confidence_blended_logit",
        "confidence_temperature",
        "position_side",
        "position_size_norm",
        "account_drawdown_pct",
    }
    missing = expected_subset.difference(names)
    assert not missing, f"observation schema missing fields: {sorted(missing)}"
    # And the schema must be reasonably sized (around 30 fields per spec)
    assert len(V2_OBSERVATION_SCHEMA) >= 25
    # SHA256 of the legacy obs_schema.py must be cited
    assert (
        LEGACY_OBS_SHA256
        == "9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f"
    )


# --------------------------------------------------------------------------- #
# Reward
# --------------------------------------------------------------------------- #
def test_reward_components_drawdown_penalty_negative() -> None:
    # No PnL but a large drawdown — total must be strictly negative because the
    # drawdown penalty alone is positive (and subtracted).
    components = compute_constrained_reward(
        realized_pnl=0.0,
        drawdown_pct=0.20,  # 20% drawdown, far above 5% threshold
        trade_executed=False,
    )
    assert components.drawdown_penalty > 0.0
    assert components.total < 0.0


def test_reward_fee_ratio_shaping_reduces_score_when_fee_high() -> None:
    # Keep absolute fee_penalty small (notional=100) so the fee_ratio_penalty
    # is the dominant gradient and we don't hit the hard clamp.
    common = dict(
        realized_pnl=2.0,
        notional_usd=100.0,
        slippage_bps=0.0,
        expected_move_bps=100.0,
        drawdown_pct=0.0,
        trade_executed=True,
    )
    low_fee = compute_constrained_reward(fee_bps=5.0, **common)  # ratio 0.05
    high_fee = compute_constrained_reward(fee_bps=60.0, **common)  # ratio 0.60 -> HIGH
    critical_fee = compute_constrained_reward(fee_bps=85.0, **common)  # ratio 0.85 -> CRITICAL

    assert low_fee.fee_ratio_penalty == 0.0
    assert high_fee.fee_ratio_penalty > 0.0
    assert critical_fee.fee_ratio_penalty > high_fee.fee_ratio_penalty
    # Total reward shrinks (or goes negative) as fee ratio penalty grows.
    assert critical_fee.total < high_fee.total < low_fee.total
    # And none of these should hit the clamp at this scale.
    assert not critical_fee.clamped
    assert not high_fee.clamped
    assert not low_fee.clamped


def test_reward_no_trade_correct_credit_positive() -> None:
    # Agent did not trade, the market move stayed within noise: small + credit.
    components = compute_constrained_reward(
        realized_pnl=0.0,
        notional_usd=0.0,
        fee_bps=0.0,
        slippage_bps=0.0,
        expected_move_bps=0.0,
        drawdown_pct=0.0,
        trade_executed=False,
        no_trade_outcome_bps=1.0,
        no_trade_noise_bps=5.0,
    )
    assert components.no_trade_correct_credit > 0.0
    assert components.total > 0.0


def test_reward_total_is_clamped_to_safe_range() -> None:
    # Extreme realized PnL must still be clamped by the hard cap.
    components = compute_constrained_reward(
        realized_pnl=1_000_000.0,
        drawdown_pct=0.0,
        trade_executed=True,
    )
    assert components.clamped is True
    assert components.total <= 5.0
    assert components.raw_total >= components.total


# --------------------------------------------------------------------------- #
# Checkpoint metadata
# --------------------------------------------------------------------------- #
def test_checkpoint_filename_legacy_pattern_parses() -> None:
    md = parse_legacy_checkpoint_filename(
        "legacy_live_checkpoint_1717000000_v3.zip",
        sha256_if_known="deadbeef" * 8,
    )
    assert md is not None
    assert md.prefix == "legacy_live_checkpoint"
    assert md.model_version == "v3"
    assert md.created_utc.endswith("Z")
    assert md.source_legacy_path == "legacy_live_checkpoint_1717000000_v3.zip"
    assert md.sha256_if_known == "deadbeef" * 8

    # Plain timestamp-only variant
    md2 = parse_legacy_checkpoint_filename("hybrid_trainer_ckpt_1700000000.zip")
    assert md2 is not None
    assert md2.prefix == "hybrid_trainer_ckpt"
    assert md2.model_version == "unknown"


def test_checkpoint_filename_invalid_returns_none() -> None:
    assert parse_legacy_checkpoint_filename("random_unrelated_file.txt") is None
    assert parse_legacy_checkpoint_filename("") is None
    assert parse_legacy_checkpoint_filename("legacy_live_checkpoint.zip") is None


# --------------------------------------------------------------------------- #
# Confidence calibration
# --------------------------------------------------------------------------- #
def test_calibrated_confidence_temperature_one_is_identity() -> None:
    result = calibrate_confidence(raw_logit=0.7, temperature=1.0)
    # T=1 -> calibrated probability equals raw sigmoid probability
    assert math.isclose(result["raw_prob"], result["calibrated_prob"], rel_tol=1e-9)
    # T=1 is identity so used_calibration should be False
    assert result["used_calibration"] is False


def test_calibrated_confidence_temperature_higher_is_softer() -> None:
    # For a positive logit, higher T must pull the calibrated prob TOWARD 0.5.
    raw = calibrate_confidence(raw_logit=2.0, temperature=1.0)
    softer = calibrate_confidence(raw_logit=2.0, temperature=4.0)
    assert softer["calibrated_prob"] < raw["calibrated_prob"]
    assert softer["calibrated_prob"] > 0.5  # still above neutral
    assert softer["used_calibration"] is True

    # Disabled flag -> identity
    disabled = calibrate_confidence(
        raw_logit=2.0, temperature=4.0, calibration_enabled=False
    )
    assert disabled["used_calibration"] is False
    assert math.isclose(
        disabled["calibrated_prob"], raw["calibrated_prob"], rel_tol=1e-9
    )

    # Bad temperature falls back to identity (raw sigmoid) without raising.
    bad = calibrate_confidence(raw_logit=2.0, temperature=0.0)
    assert bad["used_calibration"] is False
    assert math.isclose(bad["calibrated_prob"], raw["calibrated_prob"], rel_tol=1e-9)


# --------------------------------------------------------------------------- #
# Status payload
# --------------------------------------------------------------------------- #
def test_status_payload_carries_safety_invariants() -> None:
    payload = RLCoreService().current_paper_only_status()
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["scope"] == "PAPER_ONLY"
    invariants = payload["safety_invariants"]
    assert invariants["no_legacy_redis_writes"] is True
    assert invariants["no_exchange_mutation"] is True
    assert invariants["no_policy_weight_loading"] is True
    assert invariants["no_training_loop"] is True
    assert invariants["paper_only"] is True
    assert payload["go_no_go"].startswith("SUBPROJECT_1_RL_CORE")


def test_status_payload_lists_components_missing() -> None:
    payload = RLCoreService().current_paper_only_status()
    missing = payload["components_missing"]
    present = payload["components_present"]
    # Honest MISSING_IN_V2 must be declared
    expected_missing = {
        "ppo_masa_policy_network_MISSING_IN_V2",
        "gymnasium_env_step_reset_loop_MISSING_IN_V2",
        "gpu_training_loop_MISSING_IN_V2",
        "unified_feature_builder_tensor_assembly_MISSING_IN_V2",
    }
    assert expected_missing.issubset(set(missing))
    # And ported pieces must be declared present.
    expected_present_subset = {
        "observation_schema_descriptor",
        "constrained_reward_paper",
        "checkpoint_metadata_filename_parser",
        "temperature_calibration_math",
    }
    assert expected_present_subset.issubset(set(present))
    # Legacy SHA256 citations carried through
    citations = payload["legacy_sha256_citations"]
    assert (
        citations["rl/obs_schema.py"]
        == "9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f"
    )
    assert (
        citations["rl/reward_functions.py"]
        == "87ef4602012cbbd944bdf506fb8f1646375e7732c3a93e87b0946db7a1cca853"
    )
    assert (
        citations["rl/constrained_reward.py"]
        == "69ff3c75b53d8d3d7844894954cf9d16f334e79e0c1bd39e9624a4482a459b2e"
    )


# --------------------------------------------------------------------------- #
# CLI behavior
# --------------------------------------------------------------------------- #
def test_cli_dry_run_prints_payload(capsys: pytest.CaptureFixture[str]) -> None:
    rc = v2_rl_core_worker.main(["--dry-run", "--require-paper-only"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["live_gate"] == "blocked_human_only"
    assert parsed["live_symbols"] == []
    assert parsed["scope"] == "PAPER_ONLY"


def test_cli_write_evidence_emits_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out_path = tmp_path / "v2_rl_core_status.json"
    rc = v2_rl_core_worker.main(
        ["--write-evidence", "--output", str(out_path), "--require-paper-only"]
    )
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["wrote"] == str(out_path)
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["go_no_go"] == "SUBPROJECT_1_RL_CORE_PARTIALLY_MIGRATED_PAPER_ONLY"
    # Payload includes the operator_runtime contract fields
    assert "generated_at" in payload
    assert "evidence_classification" in payload


def test_cli_rejects_mutually_exclusive_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    rc = v2_rl_core_worker.main(["--dry-run", "--write-evidence"])
    assert rc == 2


def test_cli_observation_status_via_service() -> None:
    obs_status = RLCoreService().build_observation_status()
    assert obs_status["field_count"] == len(V2_OBSERVATION_SCHEMA)
    assert (
        obs_status["legacy_obs_sha256"]
        == "9ec040fa1306ac28f4395aac103b104eb02644866ca8acec5577b155fd925f5f"
    )
    # Freshness count should be non-trivial
    assert obs_status["freshness_required_count"] > 10
