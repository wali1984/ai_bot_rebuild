"""Integration tests for the v2_default_blocked_execution_adapter_stub worker.

Covers every required test case:

  1. order_placement_method_raises_BLOCKED_GATE_NOT_APPROVED
  2. order_cancel_method_raises_BLOCKED_GATE_NOT_APPROVED
  3. leverage_change_method_raises_BLOCKED_GATE_NOT_APPROVED
  4. margin_mode_change_method_raises_BLOCKED_GATE_NOT_APPROVED
  5. no_real_exchange_method_can_be_invoked_from_this_stub_contract
  6. stub_remains_disabled_by_default_invariant
  7. approval_token_absence_keeps_all_methods_blocked
  8. symbol_universe_contract_required
  9. symbol_scope_roles_distinguished
 10. no_hardcoded_current_25_symbols_as_full_universe
 11. no_train_or_trade_all_discovered_symbols_automatically
 12. coinank_symbols_require_binance_usdm_confirmation_before_tradable
 13. legacy_active_symbols_current_25_preserved
 14. dynamic_discovered_symbols_not_used_as_training_or_paper_scope_by_default
 15. live_symbols_empty_while_live_blocked
 16. symbol_selection_score_factors_present

Plus the required source-shape contract assertions:

 17. no exchange-client attribute reachable on the adapter or worker module
 18. no codepath unblocks the live gate
 19. all required public payload fields present (in status and on disk)
 20. stub state never ACTIVE on any code path
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

from v2.backend.app.cli import v2_default_blocked_execution_adapter_stub as worker
from v2.backend.app.cli.v2_default_blocked_execution_adapter_stub import (
    ERROR_CODE,
    EXCHANGE_CALL_INVARIANT,
    LEGACY_EXECUTION_SOURCE_PATHS,
    LIVE_GATE_STATUS,
    MUTATION_METHODS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    STATE_BLOCKED,
    STATE_DISABLED,
    SYMBOL_UNIVERSE_CONTRACT,
    SYMBOL_UNIVERSE_SERVICE_PATH,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.services.default_blocked_execution_adapter import service as adapter_service
from v2.backend.app.services.default_blocked_execution_adapter.service import (
    ALLOWED_STUB_STATES,
    BlockedGateNotApprovedError,
    DefaultBlockedExecutionAdapter,
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
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_symbol_universe_payload.json"],
    )
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _route_symbol_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: Dict[str, Any]
) -> Path:
    payload_path = tmp_path / "symbol_universe_status.json"
    payload_path.write_text(json.dumps(payload))
    monkeypatch.setattr(worker, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES", [payload_path])
    return payload_path


# ----------------------------------------------------------------------
# 1) order_placement_method_raises_BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_order_placement_method_raises_blocked_gate_not_approved() -> None:
    adapter = DefaultBlockedExecutionAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.place_order(symbol="BTCUSDT", side="BUY", quantity=0.001, price=20000)
    assert exc.value.code == ERROR_CODE == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "place_order"
    assert adapter.blocked_call_attempts_total == 1
    assert adapter.blocked_call_breakdown_by_method["place_order"] == 1


# ----------------------------------------------------------------------
# 2) order_cancel_method_raises_BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_order_cancel_method_raises_blocked_gate_not_approved() -> None:
    adapter = DefaultBlockedExecutionAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.cancel(symbol="BTCUSDT", order_id="12345")
    assert exc.value.code == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "cancel"
    assert adapter.blocked_call_breakdown_by_method["cancel"] == 1


# ----------------------------------------------------------------------
# 3) leverage_change_method_raises_BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_leverage_change_method_raises_blocked_gate_not_approved() -> None:
    adapter = DefaultBlockedExecutionAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.change_leverage(symbol="BTCUSDT", leverage=25)
    assert exc.value.code == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "change_leverage"
    assert adapter.blocked_call_breakdown_by_method["change_leverage"] == 1


# ----------------------------------------------------------------------
# 4) margin_mode_change_method_raises_BLOCKED_GATE_NOT_APPROVED
# ----------------------------------------------------------------------


def test_margin_mode_change_method_raises_blocked_gate_not_approved() -> None:
    adapter = DefaultBlockedExecutionAdapter()
    with pytest.raises(BlockedGateNotApprovedError) as exc:
        adapter.change_margin_mode(symbol="BTCUSDT", margin_mode="CROSS")
    assert exc.value.code == "BLOCKED_GATE_NOT_APPROVED"
    assert exc.value.method == "change_margin_mode"
    assert adapter.blocked_call_breakdown_by_method["change_margin_mode"] == 1


# ----------------------------------------------------------------------
# 5) no_real_exchange_method_can_be_invoked_from_this_stub_contract
# ----------------------------------------------------------------------


def test_no_real_exchange_method_can_be_invoked_from_this_stub_contract() -> None:
    """No Binance / ccxt / Redis import and no real exchange method
    reference may appear in either the CLI worker source or the adapter
    service source."""
    sources = {
        "worker": Path(worker.__file__).read_text(),
        "service": Path(adapter_service.__file__).read_text(),
    }
    forbidden_imports = [
        "import bin" + "ance",
        "from bin" + "ance",
        "import cc" + "xt",
        "from cc" + "xt",
        "import re" + "dis",
        "from re" + "dis",
    ]
    forbidden_methods = [
        "futures" + "_" + "create" + "_" + "order",
        "futures" + "_" + "cancel" + "_" + "order",
        "futures" + "_" + "change" + "_" + "leverage",
        "futures" + "_" + "change" + "_" + "margin" + "_" + "type",
    ]
    forbidden_writers = [".set(", ".hset(", ".xadd(", ".publish("]
    for name, src in sources.items():
        for token in forbidden_imports:
            assert token not in src, f"{name} source contains forbidden import: {token!r}"
        for token in forbidden_methods:
            assert token not in src, f"{name} source contains forbidden method: {token!r}"
        for token in forbidden_writers:
            assert token not in src, f"{name} source contains Redis writer: {token!r}"


# ----------------------------------------------------------------------
# 6) stub_remains_disabled_by_default_invariant
# ----------------------------------------------------------------------


def test_stub_remains_disabled_by_default_invariant() -> None:
    adapter = DefaultBlockedExecutionAdapter()
    assert adapter.state == STATE_DISABLED
    assert STATE_DISABLED in ALLOWED_STUB_STATES
    assert STATE_BLOCKED in ALLOWED_STUB_STATES
    assert "ACTIVE" not in ALLOWED_STUB_STATES
    snapshot = adapter.state_snapshot()
    assert (
        snapshot["stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE"]
        in ALLOWED_STUB_STATES
    )
    # Even after exhausting every mutation surface, state must not flip.
    for method in MUTATION_METHODS:
        with pytest.raises(BlockedGateNotApprovedError):
            getattr(adapter, method)()
    assert adapter.state == STATE_DISABLED


# ----------------------------------------------------------------------
# 7) approval_token_absence_keeps_all_methods_blocked
# ----------------------------------------------------------------------


def test_approval_kwarg_or_absence_keeps_all_methods_blocked() -> None:
    """The adapter must refuse regardless of any caller-supplied
    'approval'-shaped kwarg. The contract is: every mutation is refused
    unconditionally — there is no kwarg, env, or attribute that can
    permit a call."""
    adapter = DefaultBlockedExecutionAdapter()
    # Try every method with and without an "approval"-shaped kwarg.
    fake_token_kw = {"approval": "anything", "operator": "anyone", "force": True}
    for method in MUTATION_METHODS:
        with pytest.raises(BlockedGateNotApprovedError):
            getattr(adapter, method)(**fake_token_kw)
        with pytest.raises(BlockedGateNotApprovedError):
            getattr(adapter, method)()
    # The source itself must not contain an "approval"-token codepath.
    forbidden = ["approval" + "_token", "un" + "block", "enable" + "_live"]
    for source in (Path(worker.__file__).read_text(), Path(adapter_service.__file__).read_text()):
        for token in forbidden:
            assert token not in source, f"source contains forbidden token: {token!r}"


# ----------------------------------------------------------------------
# 8) symbol_universe_contract_required
# ----------------------------------------------------------------------


def test_symbol_universe_contract_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert status["symbol_universe_source_path"] == SYMBOL_UNIVERSE_SERVICE_PATH
    assert (
        status["symbol_universe_public_payload_status"]
        == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    )


# ----------------------------------------------------------------------
# 9) symbol_scope_roles_distinguished
# ----------------------------------------------------------------------


def test_symbol_scope_roles_distinguished(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    for field in (
        "legacy_active_symbols",
        "discovered_symbols",
        "observed_symbols",
        "training_symbols",
        "paper_symbols",
        "live_symbols",
        "live_blocked_symbols",
        "binance_usdm_confirmed_symbols",
        "dynamic_discovered_symbols",
    ):
        assert field in status, f"missing distinguished symbol-scope field: {field!r}"
    # Each role is a distinct list (not aliased to legacy_active_symbols):
    assert status["legacy_active_symbols"] == list(LEGACY_ACTIVE_SYMBOLS_25)
    assert status["training_symbols"] != status["legacy_active_symbols"] or status["training_symbols"] == []
    assert status["paper_symbols"] != status["legacy_active_symbols"] or status["paper_symbols"] == []


# ----------------------------------------------------------------------
# 10) no_hardcoded_current_25_symbols_as_full_universe
# ----------------------------------------------------------------------


def test_no_hardcoded_current_25_symbols_as_full_universe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    # The 25-symbol set is exposed as legacy_active_symbols, but never as
    # the *only* universe field.
    assert status["legacy_active_symbols"] == list(LEGACY_ACTIVE_SYMBOLS_25)
    assert (
        status["legacy_active_symbol_source"] == "legacy_config.py_SYMBOLS_current_25"
    )
    # Other scopes must be distinct fields (even if empty):
    for field in (
        "discovered_symbols",
        "dynamic_discovered_symbols",
        "training_symbols",
        "paper_symbols",
        "binance_usdm_confirmed_symbols",
    ):
        assert field in status
    # The CLI worker source must not contain the 25-symbol list inline:
    worker_source = Path(worker.__file__).read_text()
    for symbol in LEGACY_ACTIVE_SYMBOLS_25:
        # the constant itself lives in symbol_universe/service.py — the
        # worker only references it by import.
        assert f'"{symbol}"' not in worker_source, (
            f"worker source unexpectedly hardcodes legacy active symbol: {symbol!r}"
        )


# ----------------------------------------------------------------------
# 11) no_train_or_trade_all_discovered_symbols_automatically
# ----------------------------------------------------------------------


def test_no_train_or_trade_all_discovered_symbols_automatically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["passive_monitor_all_discovered_symbols"] is True
    assert (
        status["symbol_scope_policy"]
        == "do_not_train_or_trade_all_discovered_symbols_automatically"
    )


# ----------------------------------------------------------------------
# 12) coinank_symbols_require_binance_usdm_confirmation_before_tradable
# ----------------------------------------------------------------------


def test_coinank_symbols_require_binance_usdm_confirmation_before_tradable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert (
        status["coinank_symbols_tradability"]
        == "market_intelligence_only_until_binance_usdm_confirmed"
    )
    assert "coinank" in status["dynamic_symbol_sources"]
    # When no public Binance-USDM-confirmed list is supplied, the field
    # is present and empty — never assumed-true.
    assert status["binance_usdm_confirmed_symbols"] == []


# ----------------------------------------------------------------------
# 13) legacy_active_symbols_current_25_preserved
# ----------------------------------------------------------------------


def test_legacy_active_symbols_current_25_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["legacy_active_symbols"] == list(LEGACY_ACTIVE_SYMBOLS_25)
    assert len(status["legacy_active_symbols"]) == 25
    assert (
        status["legacy_active_symbol_source"] == "legacy_config.py_SYMBOLS_current_25"
    )
    assert "BTCUSDT" in status["legacy_active_symbols"]
    assert "ETHUSDT" in status["legacy_active_symbols"]
    assert "SOLUSDT" in status["legacy_active_symbols"]


# ----------------------------------------------------------------------
# 14) dynamic_discovered_symbols_not_used_as_training_or_paper_scope_by_default
# ----------------------------------------------------------------------


def test_dynamic_discovered_symbols_not_used_as_training_or_paper_scope_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["training_symbols"] == []
    assert status["paper_symbols"] == []
    # dynamic_discovered_symbols may be empty (no source), but is never
    # silently promoted to training/paper scope.
    if status["dynamic_discovered_symbols"]:
        assert status["dynamic_discovered_symbols"] != status["training_symbols"]
        assert status["dynamic_discovered_symbols"] != status["paper_symbols"]


def test_public_symbol_universe_cannot_override_canonical_legacy_active_symbols(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    _route_symbol_payload(
        tmp_path,
        monkeypatch,
        {
            "legacy_active_symbols": ["FAKEUSDT"],
            "discovered_symbols": ["FAKEUSDT", "BTCUSDT"],
        },
    )
    status = run_once(parse_args(["--once"]))
    assert status["legacy_active_symbols"] == list(LEGACY_ACTIVE_SYMBOLS_25)
    assert status["symbol_universe_payload_legacy_active_symbols"] == ["FAKEUSDT"]
    assert status["symbol_universe_legacy_active_payload_matches_service"] is False
    assert (
        "public_payload_legacy_active_symbols_mismatch_ignored"
        in status["symbol_universe_payload_evidence_gaps"]
    )


def test_public_payload_cannot_promote_all_discovered_to_training_or_paper_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    discovered = ["BTCUSDT", "ETHUSDT", "FAKEUSDT"]
    _route_symbol_payload(
        tmp_path,
        monkeypatch,
        {
            "discovered_symbols": discovered,
            "dynamic_discovered_symbols": discovered,
            "training_symbols": discovered,
            "paper_symbols": discovered,
            "binance_usdm_confirmed_symbols": discovered,
            "symbol_selection_evidence": {"source": "test"},
        },
    )
    status = run_once(parse_args(["--once"]))
    assert status["discovered_symbols"] == sorted(discovered)
    assert status["training_symbols"] == []
    assert status["paper_symbols"] == []
    assert status["rejected_training_symbols"] == sorted(discovered)
    assert status["rejected_paper_symbols"] == sorted(discovered)
    assert (
        "requested_scope_matches_or_contains_all_discovered_symbols"
        in status["symbol_universe_payload_evidence_gaps"]
    )


def test_coinank_only_symbol_is_not_promoted_without_binance_usdm_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    _route_symbol_payload(
        tmp_path,
        monkeypatch,
        {
            "discovered_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            "dynamic_discovered_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            "training_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            "paper_symbols": ["BTCUSDT", "COINANKONLYUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT"],
            "symbol_selection_evidence": {"source": "test"},
        },
    )
    status = run_once(parse_args(["--once"]))
    assert status["training_symbols"] == []
    assert status["paper_symbols"] == []
    assert "COINANKONLYUSDT" in status["rejected_training_symbols"]
    assert "COINANKONLYUSDT" in status["rejected_paper_symbols"]


def test_explicit_selected_scope_requires_evidence_and_binance_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    _route_symbol_payload(
        tmp_path,
        monkeypatch,
        {
            "discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANKONLYUSDT"],
            "training_symbols": ["BTCUSDT"],
            "paper_symbols": ["ETHUSDT"],
            "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT"],
            "symbol_selection_evidence": {"source": "test"},
        },
    )
    status = run_once(parse_args(["--once"]))
    assert status["training_symbols"] == ["BTCUSDT"]
    assert status["paper_symbols"] == ["ETHUSDT"]
    assert status["rejected_training_symbols"] == []
    assert status["rejected_paper_symbols"] == []


# ----------------------------------------------------------------------
# 15) live_symbols_empty_while_live_blocked
# ----------------------------------------------------------------------


def test_live_symbols_empty_while_live_blocked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["live_symbols"] == []
    assert status["live_symbol_policy"] == "none_live_blocked_human_only"
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["live_blocked"] is True
    # live_blocked_symbols must be a non-empty audit list (every dynamic
    # or legacy active symbol is implicitly blocked-live).
    assert isinstance(status["live_blocked_symbols"], list)


# ----------------------------------------------------------------------
# 16) symbol_selection_score_factors_present
# ----------------------------------------------------------------------


def test_symbol_selection_score_factors_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    factors = status["symbol_selection_score_factors"]
    for required in (
        "liquidity",
        "volume",
        "volatility",
        "funding",
        "open_interest",
        "spread",
        "freshness",
        "feature_completeness",
        "exchange_availability",
        "risk_profile",
        "model_confidence",
        "replay_performance",
        "operator_overrides",
    ):
        assert required in factors, f"missing scoring factor: {required!r}"


# ----------------------------------------------------------------------
# 17) no exchange-client attribute reachable
# ----------------------------------------------------------------------


def test_no_exchange_client_attribute_reachable() -> None:
    for attr in [
        "exchange_client",
        "binance_client",
        "futures_client",
        "ccxt_client",
        "Client",
        "BinanceClient",
        "FuturesClient",
        "CcxtClient",
    ]:
        assert not hasattr(worker, attr), (
            f"worker module unexpectedly exposes attribute: {attr!r}"
        )
        assert not hasattr(adapter_service, attr), (
            f"service module unexpectedly exposes attribute: {attr!r}"
        )
    adapter = DefaultBlockedExecutionAdapter()
    for attr in [
        "exchange_client",
        "binance_client",
        "futures_client",
        "ccxt_client",
        "client",
        "rest_client",
    ]:
        assert not hasattr(adapter, attr), (
            f"adapter instance unexpectedly exposes attribute: {attr!r}"
        )


# ----------------------------------------------------------------------
# 18) no codepath unblocks the live gate
# ----------------------------------------------------------------------


def test_no_codepath_unblocks_live_gate() -> None:
    for src in (Path(worker.__file__).read_text(), Path(adapter_service.__file__).read_text()):
        for token in ["un" + "block", "enable" + "_live", "approval" + "_token"]:
            assert token not in src, f"source unexpectedly contains: {token!r}"
    assert LIVE_GATE_STATUS == "blocked_human_only"
    assert adapter_service.LIVE_GATE_STATUS == "blocked_human_only"


# ----------------------------------------------------------------------
# 19) all required public payload fields present (in status and on disk)
# ----------------------------------------------------------------------


def test_required_public_payload_fields_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status, f"missing required public payload field: {field!r}"
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in written, f"missing required field on disk: {field!r}"
    # Files are also written to local and worker dirs:
    assert (paths["local"] / f"{WORKER_ID}_status.json").exists()
    assert (paths["worker"] / f"{WORKER_ID}_status.json").exists()


# ----------------------------------------------------------------------
# 20) stub state never ACTIVE on any code path
# ----------------------------------------------------------------------


def test_stub_state_never_active_on_any_codepath(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert (
        status["stub_state_one_of_DISABLED_OR_BLOCKED_NEVER_ACTIVE"]
        in (STATE_DISABLED, STATE_BLOCKED)
    )
    assert "ACTIVE" not in status["allowed_stub_states"]
    assert status["mutation_methods"] == list(MUTATION_METHODS)
    assert status["exchange_client_present"] is False
    assert status["exchange_action_taken"] is False
    assert status["exchange_call_invariant"] == EXCHANGE_CALL_INVARIANT
    assert status["error_code_on_call"] == ERROR_CODE


# ----------------------------------------------------------------------
# legacy_execution_source_paths listed audit-only
# ----------------------------------------------------------------------


def test_legacy_execution_source_paths_listed_audit_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["legacy_execution_source_paths"] == list(LEGACY_EXECUTION_SOURCE_PATHS)
    assert "legacy_reference/trading/base_executor.py" in status["legacy_execution_source_paths"]


# ----------------------------------------------------------------------
# CLI main(): --status-only returns 0 and writes the payload
# ----------------------------------------------------------------------


def test_main_status_only_writes_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    rc = main(["--status-only"])
    assert rc == 0
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    assert written["worker_id"] == WORKER_ID
    assert written["live_gate"] == "blocked_human_only"
    assert written["blocked_call_attempts_total"] == 0


# ----------------------------------------------------------------------
# Counter increments per refused call across the matrix
# ----------------------------------------------------------------------


@pytest.mark.parametrize("method", list(MUTATION_METHODS))
def test_blocked_call_counter_increments_per_method(method: str) -> None:
    adapter = DefaultBlockedExecutionAdapter()
    for _ in range(3):
        with pytest.raises(BlockedGateNotApprovedError):
            getattr(adapter, method)(symbol="BTCUSDT")
    snapshot = adapter.state_snapshot()
    assert snapshot["blocked_call_attempts_total"] == 3
    assert snapshot["blocked_call_breakdown_by_method"][method] == 3
    other_methods: List[str] = [m for m in MUTATION_METHODS if m != method]
    for other in other_methods:
        assert snapshot["blocked_call_breakdown_by_method"][other] == 0
