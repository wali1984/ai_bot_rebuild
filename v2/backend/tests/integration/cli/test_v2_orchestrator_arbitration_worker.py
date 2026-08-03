"""Integration tests for the v2 orchestrator arbitration worker.

Covers the required cases:

  - test_signal_schema_rejects_missing_required_fields
  - test_signal_schema_accepts_complete_signal
  - test_score_proposal_returns_finite_for_fresh
  - test_score_proposal_returns_minus_inf_for_stale
  - test_arbitrate_picks_highest_score_per_symbol_side
  - test_deconflict_picks_higher_confidence_when_opposite_sides
  - test_deconflict_picks_more_after_cost_when_same_confidence
  - test_deconflict_reports_MISSING_EVIDENCE_when_empty
  - test_stream_router_defaults_to_shadow
  - test_status_payload_carries_safety_invariants

Plus a worker-end-to-end check exercising ``--write-evidence``.
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_orchestrator_arbitration_worker as worker
from v2.backend.app.cli.v2_orchestrator_arbitration_worker import (
    PUBLIC_STATUS_FILE,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.services.orchestrator_arbitration import (
    DECONFLICT_REASON_DOMINANT_SIDE,
    DECONFLICT_REASON_EMPTY,
    DeconflictResult,
    OrchestratorArbitrationService,
    Proposal,
    StreamRouter,
    V2Signal,
    deconflict_signals,
    score_proposal,
    validate_signal,
)
from v2.backend.app.services.orchestrator_arbitration.proposal import (
    DEFAULT_MAX_AGE_SECONDS,
)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_signal_dict(**overrides) -> dict:
    base = {
        "signal_id": "sig_btc_1",
        "symbol": "btcusdt",
        "side": "long",
        "confidence_raw": 0.55,
        "confidence_calibrated": 0.65,
        "expected_move_after_cost_bps": 12.5,
        "source_prediction_id": "pred_1",
        "feature_snapshot_id": "snap_1",
        "generated_utc": "2026-05-15T00:00:00Z",
        "freshness_seconds": 10.0,
        "model_version": "v2_demo_model",
    }
    base.update(overrides)
    return base


def _make_proposal(**overrides) -> Proposal:
    base = {
        "proposal_id": "prop_1",
        "symbol": "BTCUSDT",
        "side": "long",
        "confidence_calibrated": 0.7,
        "expected_move_after_cost_bps": 25.0,
        "generated_utc": "2026-05-15T00:00:00Z",
        "source": "v2_signal_publisher",
        "freshness_seconds": 5.0,
        "model_version": "v2_demo_model",
    }
    base.update(overrides)
    return Proposal(**base)


# ---------------------------------------------------------------------------
# signal schema
# ---------------------------------------------------------------------------


def test_signal_schema_rejects_missing_required_fields() -> None:
    partial = _make_signal_dict()
    partial.pop("confidence_calibrated")
    partial.pop("expected_move_after_cost_bps")
    with pytest.raises(ValueError) as excinfo:
        validate_signal(partial)
    assert "missing_required_fields" in str(excinfo.value)
    assert "confidence_calibrated" in str(excinfo.value)
    assert "expected_move_after_cost_bps" in str(excinfo.value)


def test_signal_schema_accepts_complete_signal() -> None:
    signal = validate_signal(_make_signal_dict())
    assert isinstance(signal, V2Signal)
    assert signal.symbol == "BTCUSDT"
    assert signal.side == "long"
    assert signal.confidence_calibrated == 0.65
    assert signal.expected_move_after_cost_bps == 12.5
    assert signal.model_version == "v2_demo_model"


def test_signal_schema_rejects_unknown_side() -> None:
    with pytest.raises(ValueError):
        validate_signal(_make_signal_dict(side="hold"))


def test_signal_schema_rejects_out_of_range_confidence() -> None:
    with pytest.raises(ValueError):
        validate_signal(_make_signal_dict(confidence_calibrated=1.5))


# ---------------------------------------------------------------------------
# proposal scoring
# ---------------------------------------------------------------------------


def test_score_proposal_returns_finite_for_fresh() -> None:
    proposal = _make_proposal(freshness_seconds=5.0, confidence_calibrated=0.8)
    score = score_proposal(proposal, max_age_seconds=300)
    assert math.isfinite(score)
    assert score > 0.0


def test_score_proposal_returns_minus_inf_for_stale() -> None:
    proposal = _make_proposal(freshness_seconds=999.0)
    score = score_proposal(proposal, max_age_seconds=300)
    assert score == float("-inf")


# ---------------------------------------------------------------------------
# arbitrate
# ---------------------------------------------------------------------------


def test_arbitrate_picks_highest_score_per_symbol_side() -> None:
    service = OrchestratorArbitrationService(max_age_seconds=300)
    proposals = [
        _make_proposal(
            proposal_id="weak",
            confidence_calibrated=0.50,
            expected_move_after_cost_bps=5.0,
        ),
        _make_proposal(
            proposal_id="strong",
            confidence_calibrated=0.90,
            expected_move_after_cost_bps=40.0,
        ),
        _make_proposal(
            proposal_id="other_symbol_long",
            symbol="ETHUSDT",
            confidence_calibrated=0.85,
            expected_move_after_cost_bps=20.0,
        ),
        _make_proposal(
            proposal_id="btc_short",
            side="short",
            confidence_calibrated=0.60,
            expected_move_after_cost_bps=18.0,
        ),
    ]
    result = service.arbitrate(proposals)
    winners_by_bucket = {
        (w.symbol, w.side): w.winner.proposal_id for w in result.bucket_winners
    }
    assert winners_by_bucket[("BTCUSDT", "long")] == "strong"
    assert winners_by_bucket[("BTCUSDT", "short")] == "btc_short"
    assert winners_by_bucket[("ETHUSDT", "long")] == "other_symbol_long"
    assert result.considered_count == 4
    assert result.stale_proposal_ids == ()


def test_arbitrate_excludes_stale_proposals() -> None:
    service = OrchestratorArbitrationService(max_age_seconds=60)
    fresh = _make_proposal(
        proposal_id="fresh", freshness_seconds=5.0, confidence_calibrated=0.6
    )
    stale = _make_proposal(
        proposal_id="stale",
        freshness_seconds=120.0,
        confidence_calibrated=0.95,
    )
    result = service.arbitrate([fresh, stale])
    assert [w.winner.proposal_id for w in result.bucket_winners] == ["fresh"]
    assert result.stale_proposal_ids == ("stale",)


# ---------------------------------------------------------------------------
# deconflict
# ---------------------------------------------------------------------------


def test_deconflict_picks_higher_confidence_when_opposite_sides() -> None:
    long_signal = validate_signal(
        _make_signal_dict(
            signal_id="long_1",
            side="long",
            confidence_calibrated=0.80,
            expected_move_after_cost_bps=15.0,
        )
    )
    short_signal = validate_signal(
        _make_signal_dict(
            signal_id="short_1",
            side="short",
            confidence_calibrated=0.55,
            expected_move_after_cost_bps=20.0,
        )
    )
    result = deconflict_signals([long_signal, short_signal])
    assert isinstance(result, DeconflictResult)
    assert result.selected_side == "long"
    assert result.selected_signal is not None
    assert result.selected_signal.signal_id == "long_1"
    assert result.conflict_reason == DECONFLICT_REASON_DOMINANT_SIDE


def test_deconflict_picks_more_after_cost_when_same_confidence() -> None:
    long_signal = validate_signal(
        _make_signal_dict(
            signal_id="long_eq",
            side="long",
            confidence_calibrated=0.70,
            expected_move_after_cost_bps=10.0,
        )
    )
    short_signal = validate_signal(
        _make_signal_dict(
            signal_id="short_eq",
            side="short",
            confidence_calibrated=0.70,
            expected_move_after_cost_bps=30.0,
        )
    )
    result = deconflict_signals([long_signal, short_signal])
    assert result.selected_side == "short"
    assert result.selected_signal is not None
    assert result.selected_signal.signal_id == "short_eq"


def test_deconflict_reports_MISSING_EVIDENCE_when_empty() -> None:
    result = deconflict_signals([])
    assert result.selected_side is None
    assert result.selected_signal is None
    assert result.conflict_reason == DECONFLICT_REASON_EMPTY
    assert result.considered_count == 0


# ---------------------------------------------------------------------------
# stream router
# ---------------------------------------------------------------------------


def test_stream_router_defaults_to_shadow() -> None:
    router = StreamRouter()
    assert router.route_for("BTCUSDT") == "shadow"
    assert router.route_for("eth-usdt") == "shadow"
    assert router.route_for("") == "shadow"


def test_stream_router_honors_static_mapping() -> None:
    router = StreamRouter({"BTCUSDT": "primary", "ETHUSDT": "asjad"})
    assert router.route_for("btcusdt") == "primary"
    assert router.route_for("ETHUSDT") == "asjad"
    assert router.route_for("SOLUSDT") == "shadow"


def test_stream_router_rejects_invalid_label() -> None:
    with pytest.raises(ValueError):
        StreamRouter({"BTCUSDT": "live_primary"})


# ---------------------------------------------------------------------------
# status payload + CLI
# ---------------------------------------------------------------------------


def test_status_payload_carries_safety_invariants() -> None:
    service = OrchestratorArbitrationService(max_age_seconds=DEFAULT_MAX_AGE_SECONDS)
    status = service.current_paper_only_status()
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["live_blocked"] is True
    assert status["cannot_bypass_risk_gateway"] is True
    assert status["orchestrator_overrides_risk"] is False
    assert "proposal_dataclass_and_deterministic_scoring_paper_only" in status[
        "components_ported"
    ]
    assert "full_10523_line_orchestrator_worker_arbitration_logic" in status[
        "components_missing_in_v2"
    ]
    assert (
        status["legacy_sha256_index"][
            "v2/legacy_preserved/full_runtime_closure/rl/orchestrator_worker.py"
        ]
        == "a7ff83f992c6b0add14e4563241080cce431906642c0de6aa778d3fb9eb217c6"
    )


def test_worker_writes_status_when_requested(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "public"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", out_dir)
    monkeypatch.setattr(
        worker, "PUBLIC_STATUS_FILE", out_dir / f"{WORKER_ID}_status.json"
    )

    inputs_path = tmp_path / "inputs.json"
    inputs_path.write_text(
        json.dumps(
            {
                "proposals": [
                    {
                        "proposal_id": "fresh_long",
                        "symbol": "BTCUSDT",
                        "side": "long",
                        "confidence_calibrated": 0.8,
                        "expected_move_after_cost_bps": 30.0,
                        "generated_utc": "2026-05-15T00:00:00Z",
                        "source": "v2_signal_publisher",
                        "freshness_seconds": 5.0,
                        "model_version": "v2_demo_model",
                    },
                    {
                        "proposal_id": "stale_long",
                        "symbol": "BTCUSDT",
                        "side": "long",
                        "confidence_calibrated": 0.95,
                        "expected_move_after_cost_bps": 50.0,
                        "generated_utc": "2026-05-14T00:00:00Z",
                        "source": "v2_signal_publisher",
                        "freshness_seconds": 9_999.0,
                        "model_version": "v2_demo_model",
                    },
                ],
                "signals": [
                    {
                        "signal_id": "sig_btc_long",
                        "symbol": "BTCUSDT",
                        "side": "long",
                        "confidence_raw": 0.7,
                        "confidence_calibrated": 0.8,
                        "expected_move_after_cost_bps": 15.0,
                        "source_prediction_id": "pred_btc_long",
                        "feature_snapshot_id": "snap_btc_long",
                        "generated_utc": "2026-05-15T00:00:00Z",
                        "freshness_seconds": 5.0,
                        "model_version": "v2_demo_model",
                    },
                    {
                        "signal_id": "sig_btc_short",
                        "symbol": "BTCUSDT",
                        "side": "short",
                        "confidence_raw": 0.5,
                        "confidence_calibrated": 0.55,
                        "expected_move_after_cost_bps": 5.0,
                        "source_prediction_id": "pred_btc_short",
                        "feature_snapshot_id": "snap_btc_short",
                        "generated_utc": "2026-05-15T00:00:00Z",
                        "freshness_seconds": 10.0,
                        "model_version": "v2_demo_model",
                    },
                ],
            }
        )
    )

    rc = main(
        [
            "--once",
            "--inputs-file",
            str(inputs_path),
            "--max-age-seconds",
            "300",
            "--write-evidence",
        ]
    )
    assert rc == 0
    status_file = out_dir / f"{WORKER_ID}_status.json"
    assert status_file.exists()
    payload = json.loads(status_file.read_text())
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["inputs_proposal_count"] == 2
    assert payload["inputs_signal_count"] == 2
    assert payload["worker_id"] == WORKER_ID
    winners = payload["arbitration_bucket_winners"]
    assert any(
        w["winner_proposal_id"] == "fresh_long" for w in winners
    ), winners
    assert "stale_long" in payload["arbitration_stale_proposal_ids"]
    deconflict = payload["deconflict"]
    assert deconflict["selected_side"] == "long"
    assert deconflict["selected_signal_id"] == "sig_btc_long"


def test_worker_handles_missing_inputs_gracefully(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "public"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", out_dir)
    monkeypatch.setattr(
        worker, "PUBLIC_STATUS_FILE", out_dir / f"{WORKER_ID}_status.json"
    )
    rc = main(["--once", "--write-evidence"])
    assert rc == 0
    payload = json.loads((out_dir / f"{WORKER_ID}_status.json").read_text())
    assert payload["inputs_proposal_count"] == 0
    assert payload["inputs_signal_count"] == 0
    assert payload["deconflict"]["conflict_reason"] == DECONFLICT_REASON_EMPTY
    assert payload["live_symbols"] == []


def test_parse_args_defaults_to_once_only() -> None:
    args = parse_args([])
    assert args.once is True
    assert args.max_age_seconds == DEFAULT_MAX_AGE_SECONDS


def test_run_once_does_not_write_without_write_evidence_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_dir = tmp_path / "public_should_be_unused"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", out_dir)
    monkeypatch.setattr(
        worker, "PUBLIC_STATUS_FILE", out_dir / f"{WORKER_ID}_status.json"
    )
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["live_gate"] == "blocked_human_only"
    assert not (out_dir / f"{WORKER_ID}_status.json").exists()


def test_no_forbidden_imports_in_source() -> None:
    src = Path(worker.__file__).read_text()
    assert "import redis" not in src
    assert "from redis" not in src
    assert "import ccxt" not in src
    assert "binance" not in src.lower()


def test_default_public_runtime_dir_is_expected_path() -> None:
    expected = (
        REPO_ROOT
        / "v2"
        / "frontend"
        / "public"
        / "operator_runtime"
        / WORKER_ID
        / "latest"
        / f"{WORKER_ID}_status.json"
    )
    assert PUBLIC_STATUS_FILE == expected
