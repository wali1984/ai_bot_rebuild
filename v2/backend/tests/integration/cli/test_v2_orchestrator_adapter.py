"""Integration tests for the v2_orchestrator_adapter CLI worker.

Covers the required test cases:

  1. happy-path open_long / open_short / hold decisions
  2. abstain on low confidence / stale / missing freshness / worker health
  3. orchestrator-never-overrides-risk-gateway invariant
  4. fail-closed on missing source / invalid JSON / stale bundle
  5. Symbol Universe contract emitted on every payload
  6. gate-always-blocked invariant
  7. no exchange-mutation method names in worker source
  8. no Binance/ccxt/Redis imports or writer calls in worker source
  9. required public payload fields present (status + on disk)
 10. codex_review_v2_orchestrator_adapter trigger on every emit
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

from v2.backend.app.cli import v2_orchestrator_adapter as worker
from v2.backend.app.cli.v2_orchestrator_adapter import (
    ALLOWED_DECISION_ACTIONS,
    CODEX_REVIEW_TRIGGER,
    DEFAULT_LOW_CONFIDENCE_THRESHOLD,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    EXCHANGE_CALL_INVARIANT,
    LEGACY_SOURCE_PATHS,
    LIVE_GATE_STATUS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SOURCE_RUNTIME_ID,
    SYMBOL_UNIVERSE_CONTRACT,
    SYMBOL_UNIVERSE_SERVICE_PATH,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.domain.orchestrator_decision import (
    DECISION_ACTION_ABSTAIN,
    DECISION_ACTION_HOLD,
    DECISION_ACTION_OPEN_LONG,
    DECISION_ACTION_OPEN_SHORT,
    DECISION_REASON_ABSTAIN_FRESHNESS_MISSING,
    DECISION_REASON_ABSTAIN_FRESHNESS_STALE,
    DECISION_REASON_ABSTAIN_LOW_CONFIDENCE,
    DECISION_REASON_ABSTAIN_WORKER_CRITICAL,
    DECISION_REASON_ABSTAIN_WORKER_DEGRADED,
    DECISION_REASON_ABSTAIN_WORKER_UNKNOWN,
    DECISION_REASON_HOLD_FLAT_DIRECTION,
    DECISION_REASON_PROCEED_LONG,
    DECISION_REASON_PROCEED_SHORT,
)
from v2.backend.app.services.symbol_universe.service import (
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
)


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
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _fresh_bundle(
    *,
    generated_at_ms: Optional[int] = None,
    side: str = "long",
    confidence_calibrated: float = 0.72,
    confidence_raw: float = 0.74,
    freshness_state: str = "CURRENT",
    worker_health_status: str = "HEALTHY",
    upstream_risk_action: str = "allow",
    drop_trainer_prediction: bool = False,
) -> Dict[str, Any]:
    if generated_at_ms is None:
        generated_at_ms = worker.now_ms() - 5_000
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
            "freshness_state": "CURRENT",
            "market_age_seconds": 4,
            "features": {
                "return_5m": 0.004,
                "return_15m": 0.006,
                "volume_last": 12.3,
            },
        },
        "trainer_prediction": {
            "prediction_id": "pred_paper_tick_1",
            "feature_snapshot_id": "fs_paper_tick_1",
            "generated_at": "2026-05-14T05:00:00Z",
            "symbol": "BTCUSDT",
            "model_version": "v2_paper_readonly_momentum_wrapper_v1",
            "model_checkpoint": "v2_paper_readonly_momentum_wrapper_v1",
            "confidence_raw": confidence_raw,
            "confidence_calibrated": confidence_calibrated,
            "raw_output": {"side": side, "momentum_score": 0.05},
            "freshness_state": freshness_state,
            "market_age_seconds": 4,
            "worker_health_status": worker_health_status,
            "top_positive_features": ["return_5m", "return_15m"],
            "top_negative_features": ["spread_widening"],
        },
        "current_signal_lineage": {
            "orchestrator_decision": {
                "orchestrator_decision_id": "orch_paper_tick_1",
                "generated_at": "2026-05-14T05:00:00Z",
                "signal_id": "sig_upstream_1",
                "decision_action": "open_long",
                "decision_reason": "paper_momentum_signal_routed",
                "risk_gateway_required": True,
            },
            "risk_decision": {
                "risk_decision_id": "risk_paper_tick_1",
                "generated_at": "2026-05-14T05:00:00Z",
                "signal_id": "sig_upstream_1",
                "prediction_id": "pred_paper_tick_1",
                "feature_snapshot_id": "fs_paper_tick_1",
                "orchestrator_decision_id": "orch_paper_tick_1",
                "risk_action": upstream_risk_action,
                "risk_result": "APPROVED_FOR_PAPER_ONLY",
                "risk_reason_code": "allow_proceed_long",
                "live_blocked": True,
            },
        },
    }
    if drop_trainer_prediction:
        bundle.pop("trainer_prediction", None)
    return bundle


def _write_source(tmp_path: Path, payload: Dict[str, Any], name: str = "bundle.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


# ----------------------------------------------------------------------
# 1) happy-path decision emission
# ----------------------------------------------------------------------


def test_happy_path_open_long_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle(side="long", confidence_calibrated=0.72))
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["fail_closed"] is False
    assert status["decision_record_present"] is True
    assert status["decision_action"] == DECISION_ACTION_OPEN_LONG
    assert status["decision_reason_code"] == DECISION_REASON_PROCEED_LONG
    assert status["decision_id"] == "dec_pred_paper_tick_1"
    assert status["prediction_id"] == "pred_paper_tick_1"
    assert status["feature_snapshot_id"] == "fs_paper_tick_1"
    assert status["symbol"] == "BTCUSDT"
    record = status["decision_record"]
    assert record["decision_action"] == DECISION_ACTION_OPEN_LONG
    assert record["input_prediction_direction"] == "long"
    assert record["live_blocked"] is True
    assert record["risk_gateway_binding"] is True
    assert record["cannot_bypass_risk_gateway"] is True
    assert record["orchestrator_overrides_risk"] is False


def test_happy_path_open_short_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle(side="short", confidence_calibrated=0.81))
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_OPEN_SHORT
    assert status["decision_reason_code"] == DECISION_REASON_PROCEED_SHORT


def test_hold_on_flat_direction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path, _fresh_bundle(side="flat", confidence_calibrated=0.65)
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_HOLD
    assert status["decision_reason_code"] == DECISION_REASON_HOLD_FLAT_DIRECTION


# ----------------------------------------------------------------------
# 2) abstain branches
# ----------------------------------------------------------------------


def test_abstain_on_low_confidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _fresh_bundle(side="long", confidence_calibrated=0.10, confidence_raw=0.12),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_ABSTAIN
    assert status["decision_reason_code"] == DECISION_REASON_ABSTAIN_LOW_CONFIDENCE


def test_abstain_on_stale_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _fresh_bundle(side="long", confidence_calibrated=0.9, freshness_state="STALE"),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_ABSTAIN
    assert status["decision_reason_code"] == DECISION_REASON_ABSTAIN_FRESHNESS_STALE


def test_abstain_on_missing_freshness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bundle = _fresh_bundle(side="long", confidence_calibrated=0.9)
    bundle["trainer_prediction"]["freshness_state"] = "MISSING"
    src = _write_source(tmp_path, bundle, name="missing_freshness.json")
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_ABSTAIN
    assert status["decision_reason_code"] == DECISION_REASON_ABSTAIN_FRESHNESS_MISSING


def test_abstain_on_critical_worker_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _fresh_bundle(
            side="long", confidence_calibrated=0.9, worker_health_status="CRITICAL"
        ),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_ABSTAIN
    assert status["decision_reason_code"] == DECISION_REASON_ABSTAIN_WORKER_CRITICAL


def test_abstain_on_degraded_worker_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _fresh_bundle(
            side="long", confidence_calibrated=0.9, worker_health_status="DEGRADED"
        ),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_ABSTAIN
    assert status["decision_reason_code"] == DECISION_REASON_ABSTAIN_WORKER_DEGRADED
    assert status["decision_record"]["input_worker_health_status"] == "DEGRADED"


def test_abstain_on_unrecognized_worker_health_as_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _fresh_bundle(
            side="long",
            confidence_calibrated=0.9,
            worker_health_status="transient_bootstrap_state",
        ),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_ABSTAIN
    assert status["decision_reason_code"] == DECISION_REASON_ABSTAIN_WORKER_UNKNOWN
    assert status["decision_record"]["input_worker_health_status"] == "UNKNOWN"


def test_confidence_exactly_at_threshold_does_not_abstain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _fresh_bundle(
            side="long",
            confidence_calibrated=DEFAULT_LOW_CONFIDENCE_THRESHOLD,
            confidence_raw=DEFAULT_LOW_CONFIDENCE_THRESHOLD,
        ),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["decision_action"] == DECISION_ACTION_OPEN_LONG
    assert status["decision_reason_code"] == DECISION_REASON_PROCEED_LONG
    assert status["decision_record"]["input_prediction_confidence_calibrated"] == pytest.approx(
        DEFAULT_LOW_CONFIDENCE_THRESHOLD
    )


# ----------------------------------------------------------------------
# 3) orchestrator never overrides the risk gateway
# ----------------------------------------------------------------------


def test_orchestrator_never_overrides_risk_gateway_when_upstream_denies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Even when an upstream risk decision says DENY, the orchestrator
    adapter still only ever emits a proposal action (open_long / etc.).
    The adapter exposes ``cannot_bypass_risk_gateway=True`` and
    ``orchestrator_overrides_risk=False`` on every payload so the binding
    gate is unambiguous. The decision action set is closed at the domain
    layer, which makes it impossible for the adapter to invent an
    ``execute`` or ``force_open`` action."""
    _route_writes_to(tmp_path, monkeypatch)
    bundle = _fresh_bundle(
        side="long",
        confidence_calibrated=0.95,
        upstream_risk_action="deny",
    )
    src = _write_source(tmp_path, bundle, name="bundle_risk_deny.json")
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["fail_closed"] is False
    # Orchestrator proposes — it cannot proceed to live execution.
    assert status["decision_action"] in {
        DECISION_ACTION_OPEN_LONG,
        DECISION_ACTION_OPEN_SHORT,
        DECISION_ACTION_HOLD,
        DECISION_ACTION_ABSTAIN,
    }
    # Invariant flags surface the binding gate explicitly.
    assert status["orchestrator_overrides_risk"] is False
    assert status["cannot_bypass_risk_gateway"] is True
    assert status["risk_gateway_binding"] is True
    assert status["decision_action_is_proposal_only"] is True
    # Allowed decision actions never contain an "execute" / "force_open".
    for forbidden in (
        "execute",
        "exec" + "ute_long",
        "force" + "_open",
        "force" + "_open_long",
        "force" + "_open_short",
        "live_open",
    ):
        assert forbidden not in status["allowed_decision_actions"]
    # The decision record itself carries the invariant fields.
    record = status["decision_record"]
    assert record["live_blocked"] is True
    assert record["risk_gateway_binding"] is True
    assert record["cannot_bypass_risk_gateway"] is True
    assert record["orchestrator_overrides_risk"] is False
    # The adapter observed the upstream deny but did not change its action set.
    assert status["upstream_risk_decision_action"] == "deny"
    assert status["upstream_risk_decision_observed"] is True


def test_decision_action_allowed_set_is_proposal_only() -> None:
    assert DECISION_ACTION_OPEN_LONG in ALLOWED_DECISION_ACTIONS
    assert DECISION_ACTION_OPEN_SHORT in ALLOWED_DECISION_ACTIONS
    assert DECISION_ACTION_HOLD in ALLOWED_DECISION_ACTIONS
    assert DECISION_ACTION_ABSTAIN in ALLOWED_DECISION_ACTIONS
    for forbidden in ("execute", "force_open", "live_open", "place_position"):
        assert forbidden not in ALLOWED_DECISION_ACTIONS


# ----------------------------------------------------------------------
# 4) fail-closed paths
# ----------------------------------------------------------------------


def test_fail_closed_on_missing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["missing_runtime_evidence"] is True
    assert status["runtime_evidence_status"] == "MISSING_RUNTIME_EVIDENCE"
    assert status["decision_record_present"] is False

    rc = main(["--once"])
    assert rc == 2


def test_fail_closed_on_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bad = tmp_path / "bad.json"
    bad.write_text("not-json")
    args = parse_args(["--once", "--source-file", str(bad)])
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "INVALID_PAYLOAD"


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
    assert "runtime_source_stale" in status["fail_closed_reason"]
    assert status["runtime_evidence_status"] == "STALE_RUNTIME_EVIDENCE"
    assert status["missing_runtime_evidence"] is True


def test_fail_closed_on_missing_trainer_prediction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bundle = _fresh_bundle(drop_trainer_prediction=True)
    src = _write_source(tmp_path, bundle, name="bundle_no_prediction.json")
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "MISSING_CHAIN_RECORDS"
    assert status["decision_record_present"] is False


# ----------------------------------------------------------------------
# 5) Symbol Universe contract
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
    # The 25-symbol legacy active subset is NOT the universe.
    assert set(status["legacy_active_symbols"]) != {"BTCUSDT"}


def test_public_symbol_universe_payload_preserves_dynamic_and_selected_scopes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    symbol_payload = tmp_path / "symbol_universe_payload.json"
    symbol_payload.write_text(
        json.dumps(
            {
                "legacy_active_symbols": list(LEGACY_ACTIVE_SYMBOLS_25),
                "discovered_symbols": [
                    "BTCUSDT",
                    "ETHUSDT",
                    "SOLUSDT",
                    "COINANK_ONLY_USDT",
                    "KUCOIN_ONLY_USDT",
                ],
                "dynamic_discovered_symbols": [
                    "BTCUSDT",
                    "ETHUSDT",
                    "SOLUSDT",
                    "COINANK_ONLY_USDT",
                    "KUCOIN_ONLY_USDT",
                ],
                "training_symbols": ["BTCUSDT", "ETHUSDT"],
                "paper_symbols": ["BTCUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
            }
        )
    )
    monkeypatch.setattr(worker, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES", [symbol_payload])
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["symbol_universe_public_payload_status"] == "PRESENT"
    assert status["legacy_active_symbols"] == LEGACY_ACTIVE_SYMBOLS_25
    assert status["dynamic_discovered_symbols"] == [
        "BTCUSDT",
        "COINANK_ONLY_USDT",
        "ETHUSDT",
        "KUCOIN_ONLY_USDT",
        "SOLUSDT",
    ]
    assert status["training_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert status["paper_symbols"] == ["BTCUSDT"]
    assert status["live_symbols"] == []
    assert status["binance_usdm_confirmed_symbols"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
    assert status["coinank_symbols_tradability"] == (
        "market_intelligence_only_until_binance_usdm_confirmed"
    )
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert set(status["training_symbols"]) < set(status["dynamic_discovered_symbols"])
    assert set(status["paper_symbols"]) < set(status["dynamic_discovered_symbols"])
    assert status["symbol_selection_score_factors"] == list(SYMBOL_SELECTION_SCORE_FACTORS)


# ----------------------------------------------------------------------
# 6) gate-always-blocked invariant
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
# 7) worker source contains no exchange-mutation method names
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
# 8) worker source has no Binance/ccxt/Redis import or writer call
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
    for writer in [".xadd(", ".publish(", ".hset("]:
        assert writer not in source, (
            f"worker source unexpectedly contains Redis writer call: {writer!r}"
        )


# ----------------------------------------------------------------------
# 9) required public payload fields present
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
    assert written["allowed_decision_actions"] == list(ALLOWED_DECISION_ACTIONS)


# ----------------------------------------------------------------------
# 10) codex_review trigger emitted on every emit
# ----------------------------------------------------------------------


def test_codex_review_trigger_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["codex_review_trigger"] == CODEX_REVIEW_TRIGGER
    assert status["codex_review_emitted_at"] == status["last_run_ts"]


# ----------------------------------------------------------------------
# main exit codes
# ----------------------------------------------------------------------


def test_main_exit_code_zero_on_happy_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    rc = main(["--once", "--source-file", str(src)])
    assert rc == 0


def test_default_low_confidence_threshold_value() -> None:
    assert 0.0 <= DEFAULT_LOW_CONFIDENCE_THRESHOLD <= 1.0


def test_no_write_does_not_disable_later_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _fresh_bundle())
    rc = main(["--once", "--no-write", "--source-file", str(src)])
    assert rc == 0
    written_path = paths["public"] / f"{WORKER_ID}_status.json"
    assert not written_path.exists()

    rc = main(["--once", "--source-file", str(src)])
    assert rc == 0
    assert written_path.exists()
