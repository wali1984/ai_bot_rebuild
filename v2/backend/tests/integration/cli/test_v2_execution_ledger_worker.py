"""Integration tests for the v2_execution_ledger_worker CLI worker.

Covers the required test cases:

  1. append-only invariant (re-run is no-op; no truncation)
  2. tail payload reflects last N events
  3. fail-closed on unwritable ledger directory
  4. no truncation (pre-existing lines byte-preserved)
  5. action-set rejection (input_risk_action outside {allow, deny})
  6. fail-closed missing source (rc 2)
  7. fail-closed when upstream paper worker reports missing evidence
  8. required public payload fields all present (status + on disk)
  9. gate-always-blocked invariant across allow/deny matrix
 10. Symbol Universe contract emitted on every payload
 11. no real exchange-mutation method names in source
 12. no Binance/ccxt/Redis imports and no Redis writer calls in source
 13. no codepath unblocks the live gate
 14. no exchange-client attribute reachable on the worker module
 15. event_id == paper_trade_id
 16. deny entries are appended (audit visibility)
 17. tail payload reflects new event after a successful run
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_execution_ledger_worker as worker
from v2.backend.app.cli.v2_execution_ledger_worker import (
    ACCEPTED_ACTIONS,
    DEFAULT_TAIL_SIZE,
    EXCHANGE_CALL_INVARIANT,
    LEGACY_PAPER_SOURCE_PATHS,
    LIVE_GATE_STATUS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SOURCE_WORKER_ID,
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


def _route_writes_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Dict[str, Path]:
    public_dir = tmp_path / "public"
    local_dir = tmp_path / "local"
    worker_dir = tmp_path / "worker"
    ledger_dir = tmp_path / "ledger"
    ledger_file = ledger_dir / "paper_events.jsonl"
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
    monkeypatch.setattr(worker, "LEDGER_DIR", ledger_dir)
    monkeypatch.setattr(worker, "LEDGER_FILE", ledger_file)
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_symbol_universe_payload.json"],
    )
    monkeypatch.setattr(
        worker,
        "PAPER_STATUS_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_paper_status_payload.json"],
    )
    return {
        "public": public_dir,
        "local": local_dir,
        "worker": worker_dir,
        "ledger_dir": ledger_dir,
        "ledger_file": ledger_file,
    }


def _paper_status_payload(
    *,
    input_risk_action: str = "allow",
    input_risk_reason_code: str = "allow_proceed_long",
    ledger_action: str = "record_allow",
    ledger_reason_code: str = "mirror_allow_proceed_long",
    symbol: str = "BTCUSDT",
    risk_decision_id: str = "rd_1",
    decision_id: str = "decision_1",
    prediction_id: str = "prediction_1",
    feature_snapshot_id: str = "feature_1",
    paper_trade_id: Optional[str] = None,
    paper_trade_ts_ms: int = 1_715_500_001_000,
    fill_recorded: bool = True,
    side: str = "long",
    notional_usdt: float = 100.0,
    fee_usdt: float = 0.05,
    slippage_bps: float = 5.0,
    runtime_evidence_status: str = "PRESENT",
    missing_runtime_evidence: bool = False,
) -> Dict[str, Any]:
    if paper_trade_id is None:
        paper_trade_id = f"pt_{risk_decision_id}"
    return {
        "worker_id": SOURCE_WORKER_ID,
        "last_run_ts": "2026-05-14T04:40:48Z",
        "last_paper_trade_id": paper_trade_id,
        "last_paper_trade_ts": "2026-05-14T04:40:49Z",
        "last_paper_trade_ts_ms": paper_trade_ts_ms,
        "last_risk_decision_id": risk_decision_id,
        "decision_id": decision_id,
        "prediction_id": prediction_id,
        "feature_snapshot_id": feature_snapshot_id,
        "ledger_action": ledger_action,
        "ledger_reason_code": ledger_reason_code,
        "input_risk_action": input_risk_action,
        "input_risk_reason_code": input_risk_reason_code,
        "symbol": symbol,
        "runtime_evidence_status": runtime_evidence_status,
        "missing_runtime_evidence": missing_runtime_evidence,
        "live_gate": LIVE_GATE_STATUS,
        "current_gate_state": LIVE_GATE_STATUS,
        "simulated_fill": {
            "side": side,
            "fill_recorded": fill_recorded,
            "notional_usdt": notional_usdt,
            "fee_usdt": fee_usdt,
            "slippage_bps": slippage_bps,
            "exchange_action_taken": False,
            "exchange_call_invariant": "NO_REAL_EXCHANGE_CALL_FROM_PAPER_PATH",
        },
    }


def _write_source(tmp_path: Path, payload: Dict[str, Any], name: str = "src.json") -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload))
    return path


def _read_ledger_lines(path: Path) -> List[str]:
    if not path.exists():
        return []
    text = path.read_text()
    return [line for line in text.splitlines() if line.strip()]


# ----------------------------------------------------------------------
# 1) append-only invariant: re-run with same source is a no-op
# ----------------------------------------------------------------------


def test_append_only_invariant_repeat_is_noop(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _paper_status_payload(risk_decision_id="rd_alpha"))
    args = parse_args(["--once", "--source-file", str(src)])

    s1 = run_once(args)
    assert s1["entries_appended_this_run"] == 1
    assert s1["entries_total"] == 1
    assert s1["duplicate_skipped"] is False
    assert s1["fail_closed"] is False
    assert s1["runtime_evidence_status"] == "PRESENT"
    assert s1["fail_closed_reason"] == ""

    lines_after_first = _read_ledger_lines(paths["ledger_file"])
    bytes_after_first = paths["ledger_file"].read_bytes()
    assert len(lines_after_first) == 1
    assert json.loads(lines_after_first[0])["event_id"] == "pt_rd_alpha"

    s2 = run_once(args)
    assert s2["entries_appended_this_run"] == 0
    assert s2["entries_total"] == 1
    assert s2["duplicate_skipped"] is True
    assert s2["fail_closed"] is False
    assert s2["runtime_evidence_status"] == "PRESENT"
    assert s2["fail_closed_reason"] == ""

    lines_after_second = _read_ledger_lines(paths["ledger_file"])
    bytes_after_second = paths["ledger_file"].read_bytes()
    assert lines_after_first == lines_after_second
    assert bytes_after_first == bytes_after_second


# ----------------------------------------------------------------------
# 2) tail payload reflects last N events
# ----------------------------------------------------------------------


def test_tail_payload_reflects_last_n(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    paths["ledger_dir"].mkdir(parents=True, exist_ok=True)
    # Pre-populate 25 deterministic events directly into the ledger file.
    with paths["ledger_file"].open("a", encoding="utf-8") as fh:
        for i in range(25):
            row = {
                "event_id": f"pt_pre_{i:03d}",
                "event_ts_ms": 1_715_500_000_000 + i,
                "source_worker_id": SOURCE_WORKER_ID,
                "input_risk_action": "allow",
                "ledger_action": "record_allow",
                "symbol": "BTCUSDT",
                "side": "long",
            }
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    pre_lines = _read_ledger_lines(paths["ledger_file"])
    assert len(pre_lines) == 25

    src = _write_source(
        tmp_path, _paper_status_payload(risk_decision_id="rd_new_001")
    )
    args = parse_args(["--once", "--source-file", str(src), "--tail-size", "20"])
    status = run_once(args)

    assert status["entries_appended_this_run"] == 1
    assert status["entries_total"] == 26
    assert status["tail_size"] == 20
    assert len(status["tail"]) == 20
    # Tail must end with the newly appended event:
    assert status["tail"][-1]["event_id"] == "pt_rd_new_001"
    # Tail must contain the last 19 pre-existing events too:
    expected_pre_tail = [f"pt_pre_{i:03d}" for i in range(6, 25)]
    actual_pre_tail = [row["event_id"] for row in status["tail"][:-1]]
    assert actual_pre_tail == expected_pre_tail


# ----------------------------------------------------------------------
# 3) fail-closed on unwritable ledger directory
# ----------------------------------------------------------------------


def test_fail_closed_on_unwritable_ledger_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    # Make the configured ledger dir un-creatable by placing a regular file
    # at one of its parent path components.
    blocker = tmp_path / "blocker_file"
    blocker.write_text("not a directory")
    bad_ledger_dir = blocker / "ledger_sub"
    bad_ledger_file = bad_ledger_dir / "paper_events.jsonl"
    monkeypatch.setattr(worker, "LEDGER_DIR", bad_ledger_dir)
    monkeypatch.setattr(worker, "LEDGER_FILE", bad_ledger_file)

    src = _write_source(tmp_path, _paper_status_payload(risk_decision_id="rd_ro"))
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "UNWRITABLE_LEDGER_DIR"
    assert status["ledger_path_writable"] is False
    assert status["entries_appended_this_run"] == 0
    # The blocker file itself must still exist and be unchanged.
    assert blocker.read_text() == "not a directory"
    # CLI exit code is 2.
    rc = main(["--once", "--source-file", str(src)])
    assert rc == 2


# ----------------------------------------------------------------------
# 4) no truncation: pre-existing lines are byte-preserved across runs
# ----------------------------------------------------------------------


def test_no_truncation_pre_existing_lines_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    paths["ledger_dir"].mkdir(parents=True, exist_ok=True)
    seed_rows = [
        {"event_id": f"pt_seed_{i}", "event_ts_ms": 1_715_500_000_000 + i, "marker": True}
        for i in range(5)
    ]
    with paths["ledger_file"].open("a", encoding="utf-8") as fh:
        for row in seed_rows:
            fh.write(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n")
    seed_bytes = paths["ledger_file"].read_bytes()

    src = _write_source(
        tmp_path, _paper_status_payload(risk_decision_id="rd_post_seed")
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["entries_appended_this_run"] == 1
    assert status["entries_total"] == 6

    new_bytes = paths["ledger_file"].read_bytes()
    # The seed bytes must appear at the start of the new file (no truncation).
    assert new_bytes.startswith(seed_bytes)
    # The appended line is at the end.
    new_lines = _read_ledger_lines(paths["ledger_file"])
    assert new_lines[:5] == _read_ledger_lines_from_bytes(seed_bytes)
    last_row = json.loads(new_lines[-1])
    assert last_row["event_id"] == "pt_rd_post_seed"


def _read_ledger_lines_from_bytes(data: bytes) -> List[str]:
    return [line for line in data.decode("utf-8").splitlines() if line.strip()]


# ----------------------------------------------------------------------
# 4b) worker source never opens the ledger file in 'w' mode
# ----------------------------------------------------------------------


def test_worker_source_never_opens_ledger_in_write_mode() -> None:
    source = Path(worker.__file__).read_text()
    # Append mode is allowed; write/truncate is not.
    for forbidden in ['open("w"', "open('w'", '"w", encoding', "'w', encoding"]:
        assert forbidden not in source, (
            f"worker source unexpectedly contains write-mode open: {forbidden!r}"
        )


# ----------------------------------------------------------------------
# 5) action-set rejection (input_risk_action outside {allow, deny})
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_action",
    ["noop", "abstain", "execute", "", "ALLOW", "hold", "ignore"],
)
def test_action_set_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, bad_action: str
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    paths["ledger_dir"].mkdir(parents=True, exist_ok=True)
    src = _write_source(
        tmp_path,
        _paper_status_payload(
            input_risk_action=bad_action,
            risk_decision_id=f"rd_bad_{bad_action or 'empty'}",
        ),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "INVALID_ACTION"
    assert status["entries_appended_this_run"] == 0
    assert "outside_accepted_set" in status["input_action_rejected_reason"]
    assert status["input_risk_action_accepted_set"] == list(ACCEPTED_ACTIONS)
    # Nothing was appended to the ledger.
    assert _read_ledger_lines(paths["ledger_file"]) == []


# ----------------------------------------------------------------------
# 6) fail-closed when no source is provided/found (rc 2)
# ----------------------------------------------------------------------


def test_fail_closed_missing_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once"])
    status = run_once(args)
    assert status["missing_runtime_evidence"] is True
    assert status["runtime_evidence_status"] == "MISSING_RUNTIME_EVIDENCE"
    assert status["entries_appended_this_run"] == 0
    assert _read_ledger_lines(paths["ledger_file"]) == []

    rc = main(["--once"])
    assert rc == 2


# ----------------------------------------------------------------------
# 7) fail-closed when upstream paper worker reports missing evidence
# ----------------------------------------------------------------------


def test_fail_closed_upstream_missing_runtime_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _paper_status_payload(
            risk_decision_id="rd_missing",
            runtime_evidence_status="MISSING_RUNTIME_EVIDENCE",
            missing_runtime_evidence=True,
        ),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "MISSING_RUNTIME_EVIDENCE"
    assert status["entries_appended_this_run"] == 0
    assert _read_ledger_lines(paths["ledger_file"]) == []


# ----------------------------------------------------------------------
# 8) required public payload fields all present (status + on disk)
# ----------------------------------------------------------------------


def test_required_public_payload_fields_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _paper_status_payload(risk_decision_id="rd_fields"))
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status, f"missing required field in status: {field!r}"

    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in written, f"missing required field on disk: {field!r}"


# ----------------------------------------------------------------------
# 9) gate-always-blocked invariant across the allow/deny matrix
# ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_risk_action,input_risk_reason_code,ledger_action,ledger_reason_code,side,fill_recorded",
    [
        ("allow", "allow_proceed_long", "record_allow", "mirror_allow_proceed_long", "long", True),
        ("allow", "allow_proceed_short", "record_allow", "mirror_allow_proceed_short", "short", True),
        ("deny", "deny_orchestrator_held", "record_deny", "mirror_deny_orchestrator_held", "none", False),
        (
            "deny",
            "deny_orchestrator_abstained",
            "record_deny",
            "mirror_deny_orchestrator_abstained",
            "none",
            False,
        ),
    ],
)
def test_gate_always_blocked_invariant(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    input_risk_action: str,
    input_risk_reason_code: str,
    ledger_action: str,
    ledger_reason_code: str,
    side: str,
    fill_recorded: bool,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _paper_status_payload(
            input_risk_action=input_risk_action,
            input_risk_reason_code=input_risk_reason_code,
            ledger_action=ledger_action,
            ledger_reason_code=ledger_reason_code,
            side=side,
            fill_recorded=fill_recorded,
            notional_usdt=100.0 if fill_recorded else 0.0,
            fee_usdt=0.05 if fill_recorded else 0.0,
            risk_decision_id=f"rd_{input_risk_action}_{input_risk_reason_code}",
        ),
        name=f"src_{input_risk_action}_{input_risk_reason_code}.json",
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    assert status["gate_always_blocked_invariant"] is True
    assert status["exchange_call_invariant"] == EXCHANGE_CALL_INVARIANT
    assert status["exchange_action_taken"] is False
    assert status["live_blocked"] is True


# ----------------------------------------------------------------------
# 10) Symbol Universe contract emitted on every payload
# ----------------------------------------------------------------------


def test_symbol_universe_contract_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _paper_status_payload(risk_decision_id="rd_su"))
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
    assert "binance_usdm_confirmed_symbols" in status
    assert "training_symbols" in status
    assert "paper_symbols" in status
    assert "live_blocked_symbols" in status
    assert "dynamic_discovered_symbols" in status
    assert "BTCUSDT" in status["observed_symbols"]
    assert set(status["legacy_active_symbols"]) != {"BTCUSDT"}


def test_symbol_universe_public_payload_branch_used(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    symbol_payload = tmp_path / "symbol_universe_status.json"
    symbol_payload.write_text(
        json.dumps(
            {
                "legacy_active_symbols": list(LEGACY_ACTIVE_SYMBOLS_25),
                "discovered_symbols": [
                    "BTCUSDT",
                    "ETHUSDT",
                    "COINANKONLYUSDT",
                    "KUCOINONLYUSDT",
                ],
                "dynamic_discovered_symbols": [
                    "BTCUSDT",
                    "ETHUSDT",
                    "COINANKONLYUSDT",
                    "KUCOINONLYUSDT",
                ],
                "training_symbols": ["BTCUSDT"],
                "paper_symbols": ["ETHUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT"],
                "live_blocked_symbols": [
                    "BTCUSDT",
                    "ETHUSDT",
                    "COINANKONLYUSDT",
                    "KUCOINONLYUSDT",
                ],
            }
        )
    )
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [symbol_payload],
    )

    src = _write_source(tmp_path, _paper_status_payload(risk_decision_id="rd_su_public"))
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)

    assert status["symbol_universe_public_payload_status"] == "PRESENT"
    assert status["symbol_universe_source_path"] == str(symbol_payload)
    assert status["legacy_active_symbols"] == LEGACY_ACTIVE_SYMBOLS_25
    assert status["dynamic_discovered_symbols"] == [
        "BTCUSDT",
        "COINANKONLYUSDT",
        "ETHUSDT",
        "KUCOINONLYUSDT",
    ]
    assert status["training_symbols"] == ["BTCUSDT"]
    assert status["paper_symbols"] == ["ETHUSDT"]
    assert status["live_symbols"] == []
    assert status["live_blocked_symbols"] == [
        "BTCUSDT",
        "COINANKONLYUSDT",
        "ETHUSDT",
        "KUCOINONLYUSDT",
    ]
    assert status["binance_usdm_confirmed_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert (
        status["coinank_symbols_tradability"]
        == "market_intelligence_only_until_binance_usdm_confirmed"
    )


# ----------------------------------------------------------------------
# 11) no real exchange-mutation method names appear in worker source
# ----------------------------------------------------------------------


def test_worker_has_no_real_exchange_method_names() -> None:
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
            f"worker source unexpectedly contains forbidden method: {token!r}"
        )


# ----------------------------------------------------------------------
# 12) no Binance/ccxt/Redis import and no Redis writer call in source
# ----------------------------------------------------------------------


def test_worker_has_no_exchange_client_import() -> None:
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
            f"worker source unexpectedly contains forbidden import token: {token!r}"
        )
    for writer in [".set(", ".hset(", ".xadd(", ".publish("]:
        assert writer not in source, (
            f"worker source unexpectedly contains Redis writer call: {writer!r}"
        )


# ----------------------------------------------------------------------
# 13) no codepath unblocks the live gate
# ----------------------------------------------------------------------


def test_no_codepath_unblocks_live_gate() -> None:
    source = Path(worker.__file__).read_text()
    assignments = [
        line for line in source.splitlines() if line.strip().startswith("LIVE_GATE_STATUS")
    ]
    assert any(
        line.strip().startswith('LIVE_GATE_STATUS = "blocked_human_only"')
        for line in assignments
    )
    forbidden_substrings = [
        "un" + "block",
        "enable" + "_live",
        "approval" + "_token",
    ]
    for token in forbidden_substrings:
        assert token not in source, (
            f"worker source unexpectedly contains forbidden token: {token!r}"
        )


# ----------------------------------------------------------------------
# 14) no exchange-client attribute reachable on the worker module
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


# ----------------------------------------------------------------------
# 15) event_id == paper_trade_id
# ----------------------------------------------------------------------


def test_event_id_equals_paper_trade_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    rid = "rd_xyz_42"
    src = _write_source(tmp_path, _paper_status_payload(risk_decision_id=rid))
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["entries_appended_this_run"] == 1
    assert status["last_appended_event_id"] == f"pt_{rid}"
    line = _read_ledger_lines(paths["ledger_file"])[-1]
    row = json.loads(line)
    assert row["event_id"] == f"pt_{rid}"
    assert row["paper_trade_id"] == f"pt_{rid}"


# ----------------------------------------------------------------------
# 16) deny entries are appended (audit visibility)
# ----------------------------------------------------------------------


def test_deny_entries_are_appended(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path,
        _paper_status_payload(
            input_risk_action="deny",
            input_risk_reason_code="deny_orchestrator_abstained",
            ledger_action="record_deny",
            ledger_reason_code="mirror_deny_orchestrator_abstained",
            side="none",
            fill_recorded=False,
            notional_usdt=0.0,
            fee_usdt=0.0,
            slippage_bps=0.0,
            risk_decision_id="rd_deny_1",
        ),
    )
    args = parse_args(["--once", "--source-file", str(src)])
    status = run_once(args)
    assert status["entries_appended_this_run"] == 1
    assert status["entries_total"] == 1
    assert status["fail_closed"] is False
    assert status["runtime_evidence_status"] == "PRESENT"
    assert status["fail_closed_reason"] == ""
    lines = _read_ledger_lines(paths["ledger_file"])
    assert len(lines) == 1
    row = json.loads(lines[0])
    assert row["input_risk_action"] == "deny"
    assert row["ledger_action"] == "record_deny"
    assert row["fill_recorded"] is False
    assert row["side"] == "none"
    assert row["event_id"] == "pt_rd_deny_1"


# ----------------------------------------------------------------------
# 17) tail payload reflects the freshly appended event
# ----------------------------------------------------------------------


def test_tail_reflects_freshly_appended_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(
        tmp_path, _paper_status_payload(risk_decision_id="rd_tail_top")
    )
    args = parse_args(["--once", "--source-file", str(src), "--tail-size", "5"])
    status = run_once(args)
    assert status["tail_size"] == 5
    assert len(status["tail"]) == 1
    assert status["tail"][-1]["event_id"] == "pt_rd_tail_top"
    assert status["tail"][-1]["input_risk_action"] == "allow"
    assert status["tail"][-1]["ledger_action"] == "record_allow"
