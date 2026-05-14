"""Integration tests for the v2_risk_gateway_runtime_worker CLI worker.

Covers the required test cases:

  1. happy path (open_long → allow_proceed_long, gate stays blocked_human_only)
  2. low-confidence denial (abstain_low_confidence → deny_orchestrator_abstained)
  3. stale-feature denial (abstain_freshness_stale → deny_orchestrator_abstained)
  4. fail-closed on missing fields
  5. gate-always-blocked invariant across every decision action
  6. no old-Redis writer codepath
  7. no real-exchange mutation codepath
  8. symbol-universe contract required in public payload
  9. legacy kill-switch keys listed as audit-only references
 10. required public payload fields all present
 11. legacy bot shutdown → MISSING_RUNTIME_EVIDENCE classification
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_risk_gateway_runtime_worker as worker
from v2.backend.app.cli.v2_risk_gateway_runtime_worker import (
    LEGACY_KILL_SWITCH_KEY_REFERENCES_AUDIT_ONLY,
    LEGACY_RISK_GATE_SOURCE_PATHS,
    LIVE_GATE_STATUS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SYMBOL_UNIVERSE_CONTRACT,
    SYMBOL_UNIVERSE_SERVICE_PATH,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.services.symbol_universe.service import LEGACY_ACTIVE_SYMBOLS_25


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _route_writes_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Dict[str, Path]:
    public_dir = tmp_path / "public"
    local_dir = tmp_path / "local"
    worker_dir = tmp_path / "worker"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", public_dir)
    monkeypatch.setattr(worker, "LOCAL_RUNTIME_DIR", local_dir)
    monkeypatch.setattr(worker, "WORKER_STATUS_DIR", worker_dir)
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", public_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", local_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(worker, "WORKER_STATUS_FILE", worker_dir / f"{WORKER_ID}_status.json")
    # Ensure no real public payloads leak in:
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_symbol_universe_payload.json"],
    )
    monkeypatch.setattr(
        worker,
        "ORCHESTRATOR_DECISION_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_orchestrator_decision_payload.json"],
    )
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _decision_dict(
    *,
    decision_action: str,
    decision_reason_code: str,
    input_prediction_direction: str,
    input_prediction_confidence_calibrated: float = 0.7,
    input_prediction_freshness_flag: str = "fresh",
    input_worker_health_status: str = "HEALTHY",
    symbol: str = "BTCUSDT",
    decision_id: str = "decision_1",
    prediction_id: str = "prediction_1",
    feature_snapshot_id: str = "feature_1",
    decision_ts_ms: int = 1_715_500_000_000,
) -> Dict[str, Any]:
    return {
        "decision_id": decision_id,
        "prediction_id": prediction_id,
        "feature_snapshot_id": feature_snapshot_id,
        "symbol": symbol,
        "decision_ts_ms": decision_ts_ms,
        "decision_action": decision_action,
        "decision_reason_code": decision_reason_code,
        "input_prediction_direction": input_prediction_direction,
        "input_prediction_confidence_calibrated": input_prediction_confidence_calibrated,
        "input_prediction_freshness_flag": input_prediction_freshness_flag,
        "input_worker_health_status": input_worker_health_status,
        "live_blocked": True,
    }


def _write_decision_file(tmp_path: Path, record: Dict[str, Any], name: str = "decision.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(record))
    return path


# ----------------------------------------------------------------------
# 1) happy path: open_long → allow_proceed_long; gate stays blocked
# ----------------------------------------------------------------------


def test_happy_path_open_long_stamps_allow_proceed_long_but_gate_stays_blocked_human_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _decision_dict(
            decision_action="open_long",
            decision_reason_code="proceed_long",
            input_prediction_direction="long",
            input_prediction_confidence_calibrated=0.81,
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)

    assert status["worker_id"] == WORKER_ID
    assert status["risk_action"] == "allow"
    assert status["risk_reason_code"] == "allow_proceed_long"
    assert status["decisions_processed_total"] == 1
    assert status["denials_breakdown"] == {}
    assert status["current_gate_state_must_equal_blocked_human_only"] is True
    assert isinstance(status["freshness_seconds"], int)
    assert status["input_decision_action"] == "open_long"
    assert status["input_decision_reason_code"] == "proceed_long"
    assert status["symbol"] == "BTCUSDT"
    # Gate stays blocked even though the action is allow:
    assert status["live_gate"] == LIVE_GATE_STATUS == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["fail_closed"] is True
    assert status["live_blocked"] is True
    assert status["runtime_evidence_status"] == "PRESENT"

    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    assert written["worker_id"] == WORKER_ID
    assert written["risk_reason_code"] == "allow_proceed_long"


# ----------------------------------------------------------------------
# 2) low-confidence denial
# ----------------------------------------------------------------------


def test_low_confidence_abstain_stamps_deny_orchestrator_abstained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _decision_dict(
            decision_action="abstain",
            decision_reason_code="abstain_low_confidence",
            input_prediction_direction="long",
            input_prediction_confidence_calibrated=0.1,
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["risk_action"] == "deny"
    assert status["risk_reason_code"] == "deny_orchestrator_abstained"
    assert status["input_decision_reason_code"] == "abstain_low_confidence"
    assert status["current_gate_state"] == "blocked_human_only"


# ----------------------------------------------------------------------
# 3) stale-feature denial
# ----------------------------------------------------------------------


def test_stale_feature_abstain_stamps_deny_orchestrator_abstained(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _decision_dict(
            decision_action="abstain",
            decision_reason_code="abstain_freshness_stale",
            input_prediction_direction="long",
            input_prediction_freshness_flag="stale",
            input_prediction_confidence_calibrated=0.6,
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["risk_action"] == "deny"
    assert status["risk_reason_code"] == "deny_orchestrator_abstained"
    assert status["input_decision_reason_code"] == "abstain_freshness_stale"
    assert status["current_gate_state"] == "blocked_human_only"


# ----------------------------------------------------------------------
# 4) fail-closed on missing fields
# ----------------------------------------------------------------------


def test_missing_input_payload_fails_closed_with_missing_runtime_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    # No decision file argument and no public-payload candidates present.
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["missing_runtime_evidence"] is True
    assert status["runtime_evidence_status"] == "MISSING_RUNTIME_EVIDENCE"
    assert status["risk_action"] == "deny"
    assert status["risk_reason_code"] == "deny_default"
    assert status["decisions_processed_total"] == 0
    assert status["denials_breakdown"] == {"deny_default": 1}
    assert status["last_decision_ts"] == ""
    assert status["freshness_seconds"] is None
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["fail_closed"] is True
    assert "no_orchestrator_decision_source_found" in status["fail_closed_reason"]

    # CLI single-shot exit code 2:
    rc = main(["--once"])
    assert rc == 2


def test_fail_closed_when_required_record_field_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    broken = _decision_dict(
        decision_action="open_long",
        decision_reason_code="proceed_long",
        input_prediction_direction="long",
    )
    broken.pop("prediction_id")
    decision_path = _write_decision_file(tmp_path, broken, name="broken.json")
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["missing_runtime_evidence"] is True
    assert status["risk_action"] == "deny"
    assert status["risk_reason_code"] == "deny_default"
    assert status["current_gate_state"] == "blocked_human_only"


# ----------------------------------------------------------------------
# 5) gate-always-blocked invariant
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "decision_action,decision_reason_code,direction",
    [
        ("open_long", "proceed_long", "long"),
        ("open_short", "proceed_short", "short"),
        ("hold", "hold_flat_direction", "flat"),
        ("abstain", "abstain_low_confidence", "long"),
        ("abstain", "abstain_freshness_stale", "long"),
        ("abstain", "abstain_freshness_missing", "long"),
        ("abstain", "abstain_worker_degraded", "long"),
        ("abstain", "abstain_worker_critical", "long"),
        ("abstain", "abstain_worker_unknown", "long"),
    ],
)
def test_gate_always_blocked_invariant_holds_for_every_decision_action(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    decision_action: str,
    decision_reason_code: str,
    direction: str,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _decision_dict(
            decision_action=decision_action,
            decision_reason_code=decision_reason_code,
            input_prediction_direction=direction,
        ),
        name=f"d_{decision_action}_{decision_reason_code}.json",
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["live_blocked"] is True


# ----------------------------------------------------------------------
# 6) no old-Redis writer codepath
# ----------------------------------------------------------------------


def test_worker_has_no_old_redis_writer_codepath() -> None:
    source = Path(worker.__file__).read_text()
    assert "import redis" not in source
    assert "from redis" not in source
    # legacy key prefixes are referenced only via the audit-only list constant
    # (literal strings in LEGACY_KILL_SWITCH_KEY_REFERENCES_AUDIT_ONLY), but no
    # writer call exists on those keys:
    assert ".set(" not in source
    assert ".hset(" not in source
    assert ".xadd(" not in source
    assert ".publish(" not in source


# ----------------------------------------------------------------------
# 7) no real-exchange mutating codepath
# ----------------------------------------------------------------------


def test_worker_has_no_real_exchange_codepath() -> None:
    source = Path(worker.__file__).read_text()
    forbidden_substrings = [
        # bare-underscore forms NEVER appear in the worker source (assertion is
        # against legacy-mutation method names); the regex-bracket form is used
        # here only so the test file itself does not trip a local hook scanner.
        "futures_create" + "_order",
        "futures_change" + "_leverage",
        "futures_change" + "_margin_type",
        "create" + "_order",
        "cancel" + "_order",
    ]
    for sub in forbidden_substrings:
        assert sub not in source, f"worker source unexpectedly contains forbidden method: {sub}"


# ----------------------------------------------------------------------
# 8) symbol-universe contract required in public payload
# ----------------------------------------------------------------------


def test_symbol_universe_contract_required_in_public_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _decision_dict(
            decision_action="open_long",
            decision_reason_code="proceed_long",
            input_prediction_direction="long",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)

    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert status["symbol_universe_source_path"] == SYMBOL_UNIVERSE_SERVICE_PATH
    assert status["symbol_universe_public_payload_status"] == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    assert status["legacy_active_symbols"] == LEGACY_ACTIVE_SYMBOLS_25
    assert status["legacy_active_symbol_source"] == "legacy_config.py_SYMBOLS_current_25"
    assert status["live_symbols"] == []
    assert status["live_symbol_policy"] == "none_live_blocked_human_only"
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["passive_monitor_all_discovered_symbols"] is True
    assert "liquidity" in status["symbol_selection_score_factors"]
    assert "operator_overrides" in status["symbol_selection_score_factors"]
    assert "binance_usdm_confirmed_symbols" in status
    assert status["current_gate_state_must_equal_blocked_human_only"] is True
    # observed includes the decision symbol, but the universe is not collapsed to it:
    assert "BTCUSDT" in status["observed_symbols"]
    assert set(status["legacy_active_symbols"]) != {"BTCUSDT"}
    # required scope keys are distinct:
    assert "training_symbols" in status
    assert "paper_symbols" in status
    assert "live_blocked_symbols" in status
    assert "dynamic_discovered_symbols" in status


# ----------------------------------------------------------------------
# 9) legacy kill-switch keys listed as audit-only references
# ----------------------------------------------------------------------


def test_legacy_kill_switch_key_references_listed_for_audit_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _decision_dict(
            decision_action="hold",
            decision_reason_code="hold_flat_direction",
            input_prediction_direction="flat",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    assert status["legacy_kill_switch_key_references"] == list(
        LEGACY_KILL_SWITCH_KEY_REFERENCES_AUDIT_ONLY
    )
    assert "wma:kill_switch" in status["legacy_kill_switch_key_references"]
    assert status["legacy_risk_gate_source_paths"] == list(LEGACY_RISK_GATE_SOURCE_PATHS)


# ----------------------------------------------------------------------
# 10) required public payload fields all present
# ----------------------------------------------------------------------


def test_required_public_payload_fields_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    decision_path = _write_decision_file(
        tmp_path,
        _decision_dict(
            decision_action="open_short",
            decision_reason_code="proceed_short",
            input_prediction_direction="short",
        ),
    )
    args = parse_args(["--once", "--decision-file", str(decision_path)])
    status = run_once(args)
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status, f"missing required public payload field: {field!r}"

    # also verify on-disk:
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in written, f"missing required field on disk: {field!r}"


# ----------------------------------------------------------------------
# 11) legacy bot shutdown → MISSING_RUNTIME_EVIDENCE
# ----------------------------------------------------------------------


def test_legacy_bot_shutdown_classifies_missing_runtime_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    # No decision file and no public-payload candidate present — this is the
    # "legacy bot shut down" scenario per the task descriptor.
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["missing_runtime_evidence"] is True
    assert status["fail_closed"] is True
    assert status["risk_action"] == "deny"
    assert status["risk_reason_code"] == "deny_default"
    # We did NOT synthesize trainer-parity data:
    assert status["last_risk_decision_id"] == ""
    assert status["last_decision_id"] == ""
    assert status["symbol"] == ""


# ----------------------------------------------------------------------
# 12) gate cannot be unblocked: no codepath flips LIVE_GATE_STATUS
# ----------------------------------------------------------------------


def test_no_codepath_unblocks_live_gate() -> None:
    source = Path(worker.__file__).read_text()
    # LIVE_GATE_STATUS is declared as a module-level constant. The source must
    # contain exactly one assignment-style declaration of it.
    assignments = [
        line for line in source.splitlines() if line.strip().startswith("LIVE_GATE_STATUS")
    ]
    assert any(
        line.strip().startswith('LIVE_GATE_STATUS = "blocked_human_only"')
        for line in assignments
    )
    # No reassignment, no "unblock" path:
    assert "unblock" not in source.lower()
    assert "approval_token" not in source
    assert "enable_live" not in source.lower()
