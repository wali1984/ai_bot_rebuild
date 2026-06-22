"""Integration tests for the v2_signal_lineage_worker CLI worker.

Covers the required test cases:

  1. full-chain capture: all seven per-stage records present, lineage
     reassembled, signal_record produced by the V2 signal publisher
  2. explainability citation invariant: every present-stage explanation
     either cites every evidence field or is replaced with
     EVIDENCE_MISSING_LABEL; the worker never invents a claim
  3. fail-closed on a missing chain record
  4. fail-closed on a stale chain record
  5. no-placeholder remnants in signal_publisher.py
  6. Symbol Universe contract emitted on every payload
  7. gate-always-blocked invariant
  8. no real exchange-mutation method names in worker source
  9. no Binance/ccxt/Redis imports in worker source
 10. required public payload fields present (status + on disk)
 11. signal publisher self-check is included in payload
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_signal_lineage_worker as worker
from v2.backend.app.cli.v2_signal_lineage_worker import (
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DEFAULT_WARN_THRESHOLD_SECONDS,
    EXCHANGE_CALL_INVARIANT,
    LEGACY_SOURCE_PATHS,
    LIVE_GATE_STATUS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SIGNAL_PUBLISHER_REL_PATH,
    SIGNAL_PUBLISHER_REMNANT_PATTERNS,
    SOURCE_RUNTIME_ID,
    STAGE_ORDER,
    SYMBOL_UNIVERSE_CONTRACT,
    SYMBOL_UNIVERSE_SERVICE_PATH,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.services import signal_publisher
from v2.backend.app.services.signal_publisher import (
    EVIDENCE_MISSING_LABEL,
    SIGNAL_SERVICE_ID,
    build_signal_record,
    required_signal_record_fields,
)
from v2.backend.app.services.symbol_universe.service import LEGACY_ACTIVE_SYMBOLS_25


def _route_writes_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Dict[str, Path]:
    public_dir = tmp_path / "public"
    local_dir = tmp_path / "local"
    worker_dir = tmp_path / "worker"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", public_dir)
    monkeypatch.setattr(worker, "LOCAL_RUNTIME_DIR", local_dir)
    monkeypatch.setattr(worker, "WORKER_STATUS_DIR", worker_dir)
    monkeypatch.setattr(
        worker, "PUBLIC_STATUS_FILE", public_dir / f"{WORKER_ID}_status.json"
    )
    monkeypatch.setattr(
        worker, "LOCAL_STATUS_FILE", local_dir / f"{WORKER_ID}_status.json"
    )
    monkeypatch.setattr(
        worker, "WORKER_STATUS_FILE", worker_dir / f"{WORKER_ID}_status.json"
    )
    monkeypatch.setattr(
        worker,
        "BUNDLE_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_paper_runtime_bundle.json"],
    )
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_symbol_universe_payload.json"],
    )
    return {
        "public": public_dir,
        "local": local_dir,
        "worker": worker_dir,
    }


def _fresh_bundle(
    *,
    generated_at_ms: Optional[int] = None,
    drop_keys: Optional[list[str]] = None,
    omit_paths: Optional[list[tuple[str, str]]] = None,
) -> Dict[str, Any]:
    if generated_at_ms is None:
        generated_at_ms = worker.now_ms() - 5_000  # 5 seconds ago
    bundle: Dict[str, Any] = {
        "generated_at": "2026-05-14T05:00:00Z",
        "generated_at_ms": generated_at_ms,
        "market_feed": {
            "symbol": "BTCUSDT",
            "price": 60000.5,
            "freshness_state": "CURRENT",
            "age_seconds": 4,
            "source_type": "READONLY_MARKET_FEED",
            "last_event_at": "2026-05-14T04:59:55Z",
        },
        "feature_snapshot": {
            "feature_snapshot_id": "fs_paper_tick_1",
            "generated_at": "2026-05-14T05:00:00Z",
            "available_at": "2026-05-14T04:59:58Z",
            "feature_cutoff": "2026-05-14T04:59:58Z",
            "timeframe": "1m",
            "freshness_state": "CURRENT",
            "market_age_seconds": 4,
            "features": {
                "return_1m": 0.001,
                "return_5m": 0.004,
                "return_15m": 0.006,
                "volume_last": 12.3,
                "volume_avg_10": 11.1,
                "volatility_10": 0.00012,
            },
        },
        "trainer_prediction": {
            "prediction_id": "pred_paper_tick_1",
            "feature_snapshot_id": "fs_paper_tick_1",
            "generated_at": "2026-05-14T05:00:00Z",
            "symbol": "BTCUSDT",
            "trainer_state": "V2_PAPER_TRAINER_WRAPPER_CURRENT",
            "model_checkpoint": "v2_paper_readonly_momentum_wrapper_v1",
            "confidence_raw": 0.66,
            "confidence_calibrated": 0.64,
            "timeframe": "1m",
            "expected_move_bps": 18.0,
            "expected_move_after_cost_bps": 11.5,
            "available_at": "2026-05-14T04:59:59Z",
            "decision_time": "2026-05-14T05:00:00Z",
            "feature_cutoff": "2026-05-14T04:59:58Z",
            "price_target": 60108.5009,
            "price_target_after_cost": 60069.500575,
            "raw_output": {"side": "long", "momentum_score": 0.05},
            "freshness_state": "CURRENT",
            "market_age_seconds": 4,
        },
        "current_signal_lineage": {
            "orchestrator_decision": {
                "orchestrator_decision_id": "orch_paper_tick_1",
                "generated_at": "2026-05-14T05:00:00Z",
                "signal_id": "sig_upstream_1",
                "decision_action": "open_long",
                "decision_reason": "paper_momentum_signal_routed",
                "risk_gateway_required": True,
                "cannot_bypass_risk_gateway": True,
            },
            "risk_decision": {
                "risk_decision_id": "risk_paper_tick_1",
                "generated_at": "2026-05-14T05:00:00Z",
                "signal_id": "sig_upstream_1",
                "prediction_id": "pred_paper_tick_1",
                "feature_snapshot_id": "fs_paper_tick_1",
                "orchestrator_decision_id": "orch_paper_tick_1",
                "risk_action": "allow",
                "risk_result": "APPROVED_FOR_PAPER_ONLY",
                "risk_reason_code": "allow_proceed_long",
                "live_blocked": True,
            },
        },
        "paper_ledger_tail": [
            {
                "paper_ledger_entry_id": "pledger_paper_tick_1",
                "generated_at": "2026-05-14T05:00:00Z",
                "execution_intent_id": "pei_paper_tick_1",
                "risk_decision_id": "risk_paper_tick_1",
                "signal_id": "sig_upstream_1",
                "symbol": "BTCUSDT",
                "ledger_action": "PAPER_FILL_SIMULATED",
                "paper_result": "FILLED_PAPER_ONLY",
                "live_order": False,
                "legacy_redis_write": False,
            }
        ],
    }
    if drop_keys:
        for key in drop_keys:
            bundle.pop(key, None)
    if omit_paths:
        for parent, child in omit_paths:
            node = bundle.get(parent)
            if isinstance(node, dict):
                node.pop(child, None)
    return bundle


def _write_source(tmp_path: Path, payload: Dict[str, Any], name: str = "bundle.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


# ----------------------------------------------------------------------
# 1) full-chain capture
# ----------------------------------------------------------------------


def test_full_chain_capture_all_seven_stages(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["fail_closed"] is False
    assert status["fail_closed_reason"] == ""
    assert status["chain_complete"] is True
    assert status["chain_consistent"] is True
    assert status["chain_inconsistencies"] == []
    assert status["runtime_evidence_status"] == "PRESENT"

    # All seven stages present.
    for name in STAGE_ORDER:
        block = status["stages"][name]
        assert block["present"] is True, f"stage {name} unexpectedly absent"
        assert block["freshness_state"] in ("CURRENT", "WARN")
        assert block["explanation"] != EVIDENCE_MISSING_LABEL

    # Lineage ids fully populated.
    ids = status["lineage_ids"]
    assert ids["feature_snapshot_id"] == "fs_paper_tick_1"
    assert ids["prediction_id"] == "pred_paper_tick_1"
    assert ids["orchestrator_decision_id"] == "orch_paper_tick_1"
    assert ids["risk_decision_id"] == "risk_paper_tick_1"
    assert ids["execution_intent_id"] == "pei_paper_tick_1"
    assert ids["paper_ledger_entry_id"] == "pledger_paper_tick_1"
    assert ids["signal_id"] == "sig_upstream_1"
    assert set(ids["signal_id_sources"].values()) == {"sig_upstream_1"}

    # Signal record came from the V2 signal publisher.
    sig = status["signal_record"]
    for field in required_signal_record_fields():
        assert field in sig, f"signal record missing field {field!r}"
    assert sig["service_id"] == SIGNAL_SERVICE_ID
    assert sig["prediction_id"] == "pred_paper_tick_1"
    assert sig["feature_snapshot_id"] == "fs_paper_tick_1"
    assert sig["timeframe"] == "1m"
    assert sig["expected_move_bps"] == 18.0
    assert sig["expected_move_after_cost_bps"] == 11.5
    assert sig["expected_net_edge_bps"] == 11.5
    assert sig["available_at"] == "2026-05-14T04:59:59Z"
    assert sig["decision_time"] == "2026-05-14T05:00:00Z"
    assert sig["feature_cutoff"] == "2026-05-14T04:59:58Z"
    assert sig["price_target_after_cost"] == 60069.500575
    assert sig["source_lineage"]["expected_move_after_cost_bps_source_field"] == (
        "trainer_prediction.expected_move_after_cost_bps"
    )
    assert sig["actionable"] is True
    assert sig["explanation"] != EVIDENCE_MISSING_LABEL

    # Unified lineage record is present and references all stages.
    rec = status["signal_lineage_record"]
    assert rec["stage_order"] == list(STAGE_ORDER)
    assert set(rec["stages"].keys()) == set(STAGE_ORDER)
    assert rec["live_gate"] == LIVE_GATE_STATUS

    # Explainability invariant not violated.
    assert status["explainability_invariant_violated"] is False


# ----------------------------------------------------------------------
# 2) explainability citation invariant
# ----------------------------------------------------------------------


def test_explainability_invariant_when_field_missing_uses_label(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bundle = _fresh_bundle()
    # Strip risk_action so risk-decision stage has a missing required field.
    bundle["current_signal_lineage"]["risk_decision"].pop("risk_action", None)
    src = _write_source(tmp_path, bundle)
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    risk_block = status["stages"]["risk_gateway_decision"]
    assert risk_block["present"] is True
    # Explanation must collapse to the missing-evidence label rather than
    # invent a claim from absent data.
    assert risk_block["explanation"] == EVIDENCE_MISSING_LABEL
    assert risk_block["evidence_missing_label_used"] is True
    # The remaining stages with full evidence keep their cited explanations.
    for name in (
        "market_data",
        "feature_snapshot",
        "model_output",
        "trainer_prediction",
        "orchestrator_decision",
        "paper_execution_result",
    ):
        assert status["stages"][name]["explanation"] != EVIDENCE_MISSING_LABEL
    # Invariant tracker still false — we did not invent any claim.
    assert status["explainability_invariant_violated"] is False


def test_explainability_invariant_full_evidence_cites_fields(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    for name in STAGE_ORDER:
        block = status["stages"][name]
        # Every cited field has a source pointer; every value is recoverable.
        for citation in block["evidence_citations"]:
            assert citation["field_name"]
            assert citation["source"]
            # Either present with a value, or marked missing — never silent.
            assert "present" in citation
    feature_sources = {
        citation["source"]
        for citation in status["stages"]["feature_snapshot"]["evidence_citations"]
    }
    assert "feature_snapshot.features.volume_last" in feature_sources


def test_cross_stage_signal_id_mismatch_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bundle = _fresh_bundle()
    bundle["current_signal_lineage"]["risk_decision"]["signal_id"] = "sig_mismatch"
    src = _write_source(tmp_path, bundle, name="signal_id_mismatch.json")
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["fail_closed"] is True
    assert status["chain_consistent"] is False
    assert status["runtime_evidence_status"] == "CHAIN_INCONSISTENT"
    assert "signal_id_mismatch" in ",".join(status["chain_inconsistencies"])
    assert status["signal_lineage_record"] == {}


# ----------------------------------------------------------------------
# 3) fail-closed on missing chain record
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "drop_kind,expected_fragment",
    [
        ("drop_market", "market_data"),
        ("drop_feature", "feature_snapshot"),
        ("drop_prediction", "trainer_prediction"),
        ("drop_orchestrator", "orchestrator_decision"),
        ("drop_risk", "risk_gateway_decision"),
        ("drop_execution", "paper_execution_result"),
    ],
)
def test_fail_closed_on_missing_chain_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    drop_kind: str,
    expected_fragment: str,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bundle = _fresh_bundle()
    if drop_kind == "drop_market":
        bundle.pop("market_feed", None)
    elif drop_kind == "drop_feature":
        bundle.pop("feature_snapshot", None)
    elif drop_kind == "drop_prediction":
        bundle.pop("trainer_prediction", None)
    elif drop_kind == "drop_orchestrator":
        bundle["current_signal_lineage"].pop("orchestrator_decision", None)
    elif drop_kind == "drop_risk":
        bundle["current_signal_lineage"].pop("risk_decision", None)
    elif drop_kind == "drop_execution":
        bundle["paper_ledger_tail"] = []

    src = _write_source(tmp_path, bundle, name=f"bundle_{drop_kind}.json")
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["fail_closed"] is True
    assert status["chain_complete"] is False
    assert "chain_record_missing" in status["fail_closed_reason"]
    assert expected_fragment in status["fail_closed_reason"]
    assert status["missing_runtime_evidence"] is True
    assert status["runtime_evidence_status"] == "MISSING_CHAIN_RECORDS"

    rc = main(["--once", "--source-file", str(src)])
    assert rc == 2


def test_fail_closed_when_source_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["missing_runtime_evidence"] is True
    assert status["runtime_evidence_status"] == "MISSING_RUNTIME_EVIDENCE"
    assert status["chain_complete"] is False

    rc = main(["--once"])
    assert rc == 2


# ----------------------------------------------------------------------
# 4) fail-closed on stale chain record
# ----------------------------------------------------------------------


def test_fail_closed_on_stale_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    stale_ms = worker.now_ms() - (DEFAULT_STALE_THRESHOLD_SECONDS + 60) * 1000
    bundle = _fresh_bundle(generated_at_ms=stale_ms)
    src = _write_source(tmp_path, bundle, name="bundle_stale.json")
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["fail_closed"] is True
    assert "paper_runtime_source_stale" in status["fail_closed_reason"]
    assert status["runtime_evidence_status"] == "STALE_RUNTIME_EVIDENCE"
    assert status["missing_runtime_evidence"] is True
    assert status["chain_complete"] is False
    assert status["freshness_seconds"] is not None
    assert status["freshness_seconds"] > DEFAULT_STALE_THRESHOLD_SECONDS


# ----------------------------------------------------------------------
# 5) no-placeholder remnants in signal_publisher.py
# ----------------------------------------------------------------------


def test_no_scaffold_remnants_in_signal_publisher() -> None:
    publisher_path = REPO_ROOT / SIGNAL_PUBLISHER_REL_PATH
    text = publisher_path.read_text(encoding="utf-8").lower()
    for pattern in SIGNAL_PUBLISHER_REMNANT_PATTERNS:
        assert pattern not in text, (
            f"signal_publisher.py unexpectedly contains scaffold remnant: "
            f"{pattern!r}"
        )


def test_status_payload_records_placeholder_check_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    check = status["placeholder_remnant_check"]
    assert check["readable"] is True
    assert check["remnants_found"] is False
    assert check["remnants_matched"] == []
    assert set(check["patterns_checked"]) == set(SIGNAL_PUBLISHER_REMNANT_PATTERNS)


def test_paper_online_runtime_delegates_lineage_construction() -> None:
    path = REPO_ROOT / "v2/backend/app/cli/paper_online_runtime.py"
    source = path.read_text(encoding="utf-8")
    start = source.index("def build_signal_lineage(")
    end = source.index("def build_paper_ledger_entry(", start)
    body = source[start:end]

    assert "build_paper_runtime_lineage" in body
    for token in [
        "orchestrator_decision_id =",
        "risk_decision_id =",
        "execution_intent_id =",
        "risk_action =",
        "risk_decision =",
    ]:
        assert token not in body


def test_signal_publisher_self_check_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    self_check = status["signal_publisher_self_check"]
    assert self_check["service_id"] == SIGNAL_SERVICE_ID
    assert self_check["evidence_missing_label"] == EVIDENCE_MISSING_LABEL
    assert self_check["implementation_present"] is True


def test_signal_publisher_build_signal_record_uses_evidence_missing_label() -> None:
    record = build_signal_record(
        prediction={
            "prediction_id": "",
            "raw_output": {"side": ""},
            "confidence_calibrated": None,
        },
        feature_snapshot={"feature_snapshot_id": ""},
        market_freshness_state="",
        market_age_seconds=None,
    )
    assert record["explanation"] == EVIDENCE_MISSING_LABEL
    assert record["actionable"] is False


def test_signal_publisher_build_signal_record_preserves_optional_edge_and_pit_fields() -> None:
    record = build_signal_record(
        prediction={
            "prediction_id": "pred_edge_1",
            "symbol": "BTCUSDT",
            "timeframe": "5m",
            "raw_output": {"side": "short"},
            "confidence_calibrated": 0.72,
            "expected_move_bps": -22.0,
            "expected_move_after_cost_bps": -15.5,
            "available_at": "2026-05-14T04:59:59Z",
            "decision_time": "2026-05-14T05:00:00Z",
            "feature_cutoff": "2026-05-14T04:59:58Z",
            "price_target_after_cost": 59907.0,
        },
        feature_snapshot={
            "feature_snapshot_id": "fs_edge_1",
            "symbol": "BTCUSDT",
            "timeframe": "5m",
        },
        market_freshness_state="CURRENT",
        market_age_seconds=2,
        run_ts="2026-05-14T05:00:01Z",
    )

    assert record["timeframe"] == "5m"
    assert record["expected_move_bps"] == -22.0
    assert record["expected_move_after_cost_bps"] == -15.5
    assert record["expected_net_edge_bps"] == -15.5
    assert record["available_at"] == "2026-05-14T04:59:59Z"
    assert record["decision_time"] == "2026-05-14T05:00:00Z"
    assert record["feature_cutoff"] == "2026-05-14T04:59:58Z"
    assert record["price_target_after_cost"] == 59907.0
    assert record["explanation"] != EVIDENCE_MISSING_LABEL
    citation_by_field = {
        citation["field_name"]: citation
        for citation in record["evidence_citations"]
    }
    assert citation_by_field["expected_move_after_cost_bps"]["present"] is True


# ----------------------------------------------------------------------
# 6) Symbol Universe contract emitted on every payload
# ----------------------------------------------------------------------


def test_symbol_universe_contract_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert status["symbol_universe_source_path"] == SYMBOL_UNIVERSE_SERVICE_PATH
    assert (
        status["symbol_universe_public_payload_status"]
        == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    )
    assert status["legacy_active_symbols"] == LEGACY_ACTIVE_SYMBOLS_25
    assert status["legacy_active_symbol_source"] == "legacy_config.py_SYMBOLS_current_25"
    assert status["live_symbols"] == []
    assert status["live_symbol_policy"] == "none_live_blocked_human_only"
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["passive_monitor_all_discovered_symbols"] is True
    assert "liquidity" in status["symbol_selection_score_factors"]
    assert "operator_overrides" in status["symbol_selection_score_factors"]
    assert "BTCUSDT" in status["observed_symbols"]
    assert set(status["legacy_active_symbols"]) != {"BTCUSDT"}


# ----------------------------------------------------------------------
# 7) gate-always-blocked invariant
# ----------------------------------------------------------------------


def test_gate_always_blocked_invariant(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["current_gate_state_must_equal_blocked_human_only"] is True
    assert status["gate_always_blocked_invariant"] is True
    assert status["exchange_call_invariant"] == EXCHANGE_CALL_INVARIANT
    assert status["exchange_action_taken"] is False
    assert status["live_blocked"] is True


# ----------------------------------------------------------------------
# 8) worker source contains no exchange-mutation method names
# ----------------------------------------------------------------------


def test_worker_source_no_exchange_method_names() -> None:
    source = Path(worker.__file__).read_text()
    forbidden = [
        "create" + "_order",
        "cancel" + "_order",
        "futures_create" + "_order",
        "futures_change" + "_leverage",
        "futures_change" + "_margin_type",
        "place" + "_order",
    ]
    for token in forbidden:
        assert token not in source, (
            f"worker source unexpectedly contains forbidden token: {token!r}"
        )


# ----------------------------------------------------------------------
# 9) worker source has no Binance/ccxt/Redis import or writer call
# ----------------------------------------------------------------------


def test_worker_source_no_exchange_or_redis_imports() -> None:
    source = Path(worker.__file__).read_text()
    forbidden_imports = [
        "import bin" + "ance",
        "from bin" + "ance",
        "import cc" + "xt",
        "from cc" + "xt",
        "import re" + "dis",
        "from re" + "dis",
    ]
    for token in forbidden_imports:
        assert token not in source, (
            f"worker source unexpectedly contains forbidden import: {token!r}"
        )
    for writer in [".xadd(", ".publish(", ".hset(", ".set("]:
        assert writer not in source, (
            f"worker source unexpectedly contains Redis writer call: "
            f"{writer!r}"
        )


def test_publisher_source_no_exchange_or_redis_imports() -> None:
    source = Path(signal_publisher.__file__).read_text()
    forbidden_imports = [
        "import bin" + "ance",
        "from bin" + "ance",
        "import cc" + "xt",
        "from cc" + "xt",
        "import re" + "dis",
        "from re" + "dis",
    ]
    for token in forbidden_imports:
        assert token not in source, (
            f"signal_publisher.py unexpectedly contains forbidden import: "
            f"{token!r}"
        )


# ----------------------------------------------------------------------
# 10) required public payload fields present (status + on disk)
# ----------------------------------------------------------------------


def test_required_public_payload_fields_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status, f"missing required field in status: {field!r}"

    written_path = paths["public"] / f"{WORKER_ID}_status.json"
    assert written_path.exists()
    written = json.loads(written_path.read_text())
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in written, f"missing required field on disk: {field!r}"
    assert written["source_runtime_id"] == SOURCE_RUNTIME_ID
    assert written["legacy_source_paths"] == list(LEGACY_SOURCE_PATHS)


# ----------------------------------------------------------------------
# 11) chain inconsistency surfaces via chain_inconsistencies + fail_closed
# ----------------------------------------------------------------------


def test_chain_inconsistency_when_lineage_id_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bundle = _fresh_bundle()
    # Drop the orchestrator_decision_id field while keeping the block.
    bundle["current_signal_lineage"]["orchestrator_decision"].pop(
        "orchestrator_decision_id", None
    )
    src = _write_source(tmp_path, bundle, name="bundle_no_orch_id.json")
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["chain_consistent"] is False
    assert any(
        item.startswith("missing_lineage_id:orchestrator_decision_id")
        for item in status["chain_inconsistencies"]
    )
    assert status["fail_closed"] is True
    assert "chain_id_inconsistencies" in status["fail_closed_reason"]
