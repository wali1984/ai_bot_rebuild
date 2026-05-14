"""Integration tests for the v2_replay_worker CLI worker.

Covers the required test cases:

  1.  happy replay: in-window entries become steps + summary, fail_closed False
  2.  invariant: replay output never overwrites operator_runtime/paper_online/
  3.  fail-closed when the source file is missing
  4.  fail-closed when the source file is unparseable JSON
  5.  fail-closed when the window contains zero entries
  6.  window filter drops entries outside [window_start, window_end]
  7.  paper_trade_id narrow replay returns one matched step
  8.  paper_trade_id not in window fail-closes
  9.  v2_paper_execution_worker status payload is accepted as a single-entry source
 10.  invalid ledger reason fails closed via service validator
 11.  contract: no real exchange-mutation method names appear in worker source
 12.  contract: no Binance/ccxt/Redis imports in worker source
 13.  gate-always-blocked invariant in payload
 14.  Symbol Universe contract emitted on every payload
 15.  required public payload fields present (status + on disk)
16.  legacy source paths cited
17.  steps sorted by ledger_entry_ts_ms ascending
18.  legacy redis writers are not introduced
 19.  public Symbol Universe payload cannot override canonical legacy 25
 20.  legacy fetch_executions equivalent indexes executions by signal id
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_replay_worker as worker
from v2.backend.app.cli.v2_replay_worker import (
    DEFAULT_STALE_THRESHOLD_SECONDS,
    DEFAULT_WARN_THRESHOLD_SECONDS,
    EXCHANGE_CALL_INVARIANT,
    LEGACY_SOURCE_PATHS,
    LIVE_GATE_STATUS,
    PAPER_ONLINE_FORBIDDEN_FRAGMENT,
    REPLAY_OUTPUT_INVARIANT,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SYMBOL_UNIVERSE_CONTRACT,
    SYMBOL_UNIVERSE_SERVICE_PATH,
    UPSTREAM_PAPER_EXECUTION_WORKER_ID,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.services.symbol_universe.service import (
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
)


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------


def _route_writes_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Dict[str, Path]:
    public_dir = tmp_path / "public" / "operator_runtime" / WORKER_ID / "latest"
    local_dir = tmp_path / "runtime" / WORKER_ID / "latest"
    worker_dir = tmp_path / "claude_worklog" / "workers"
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
    monkeypatch.setattr(
        worker,
        "PAPER_LEDGER_PUBLIC_PAYLOAD_CANDIDATES",
        [tmp_path / "no_such_paper_ledger_payload.json"],
    )
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _entry(
    *,
    paper_trade_id: str,
    ledger_entry_ts_ms: int,
    symbol: str = "BTCUSDT",
    ledger_action: str = "record_allow",
    ledger_reason_code: str = "mirror_allow_proceed_long",
    input_risk_action: str = "allow",
    input_risk_reason_code: str = "allow_proceed_long",
    risk_decision_id: str | None = None,
    decision_id: str | None = None,
    prediction_id: str | None = None,
    feature_snapshot_id: str | None = None,
    signal_id: str | None = None,
) -> Dict[str, Any]:
    record = {
        "paper_trade_id": paper_trade_id,
        "risk_decision_id": risk_decision_id or f"rd_{paper_trade_id}",
        "decision_id": decision_id or f"dec_{paper_trade_id}",
        "prediction_id": prediction_id or f"pred_{paper_trade_id}",
        "feature_snapshot_id": feature_snapshot_id or f"snap_{paper_trade_id}",
        "symbol": symbol,
        "ledger_entry_ts_ms": ledger_entry_ts_ms,
        "ledger_action": ledger_action,
        "ledger_reason_code": ledger_reason_code,
        "input_risk_action": input_risk_action,
        "input_risk_reason_code": input_risk_reason_code,
        "live_blocked": True,
    }
    if signal_id is not None:
        record["signal_id"] = signal_id
    return record


def _write_entries_file(
    tmp_path: Path,
    entries: List[Dict[str, Any]],
    *,
    name: str = "entries.json",
) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps({"paper_ledger_entries": entries}, indent=2))
    return path


# ----------------------------------------------------------------------
# 1) happy replay
# ----------------------------------------------------------------------


def test_happy_replay_produces_steps_and_summary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    routes = _route_writes_to(tmp_path, monkeypatch)
    entries = [
        _entry(paper_trade_id="pt_a", ledger_entry_ts_ms=1_700_000_001_000),
        _entry(
            paper_trade_id="pt_b",
            ledger_entry_ts_ms=1_700_000_002_000,
            ledger_action="record_deny",
            ledger_reason_code="mirror_deny_orchestrator_held",
            input_risk_action="deny",
            input_risk_reason_code="deny_orchestrator_held",
        ),
    ]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_happy",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["fail_closed"] is False, status
    assert status["fail_closed_reason"] == ""
    assert status["replay_steps_count"] == 2
    summary = status["replay_summary"]
    assert summary["total_steps_count"] == 2
    assert summary["record_allow_steps_count"] == 1
    assert summary["record_deny_steps_count"] == 1
    assert summary["mirror_allow_proceed_long_steps_count"] == 1
    assert summary["mirror_deny_orchestrator_held_steps_count"] == 1
    # status was persisted to all replay-scoped paths
    public_path = routes["public"] / f"{WORKER_ID}_status.json"
    local_path = routes["local"] / f"{WORKER_ID}_status.json"
    worker_path = routes["worker"] / f"{WORKER_ID}_status.json"
    assert public_path.exists()
    assert local_path.exists()
    assert worker_path.exists()


# ----------------------------------------------------------------------
# 2) replay output never overwrites operator_runtime/paper_online/
# ----------------------------------------------------------------------


def test_replay_output_paths_never_contain_paper_online(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [_entry(paper_trade_id="pt_a", ledger_entry_ts_ms=1_700_000_000_500)]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_invariant",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000001000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["replay_output_path_invariant"] == REPLAY_OUTPUT_INVARIANT
    paths = status["replay_output_paths"]
    for path in paths:
        assert PAPER_ONLINE_FORBIDDEN_FRAGMENT not in path, path
    assert status["replay_output_paths_must_not_contain_paper_online"] is True


def test_write_status_raises_when_target_is_paper_online(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forbidden = tmp_path / "operator_runtime" / "paper_online" / "latest" / "evil.json"
    monkeypatch.setattr(worker, "PUBLIC_STATUS_FILE", forbidden)
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", tmp_path / "local.json")
    monkeypatch.setattr(worker, "WORKER_STATUS_FILE", tmp_path / "worker.json")
    with pytest.raises(RuntimeError) as exc_info:
        worker.write_status({"worker_id": WORKER_ID})
    assert REPLAY_OUTPUT_INVARIANT in str(exc_info.value)


# ----------------------------------------------------------------------
# 3) fail-closed when source file is missing
# ----------------------------------------------------------------------


def test_fail_closed_when_source_file_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_missing",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000010000",
            "--source-file",
            str(tmp_path / "absent.json"),
        ]
    )
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["missing_runtime_evidence"] is True
    assert status["runtime_evidence_status"] == "MISSING_RUNTIME_EVIDENCE"
    rc = main(
        [
            "--once",
            "--replay-run-id",
            "rr_missing",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000010000",
            "--source-file",
            str(tmp_path / "absent.json"),
        ]
    )
    assert rc == 2


# ----------------------------------------------------------------------
# 4) fail-closed when source file is unparseable JSON
# ----------------------------------------------------------------------


def test_fail_closed_when_source_file_invalid_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = tmp_path / "garbage.json"
    src.write_text("{not json")
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_bad",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000010000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "INVALID_PAPER_LEDGER_ENTRY"
    assert status["replay_steps"] == []


# ----------------------------------------------------------------------
# 5) fail-closed when window contains zero entries
# ----------------------------------------------------------------------


def test_fail_closed_when_window_is_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_entries_file(tmp_path, [])
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_empty",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000010000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["fail_closed_reason"] == "no_paper_ledger_entries_in_window"
    assert status["entries_in_window_count"] == 0
    assert status["replay_summary"]["total_steps_count"] == 0


# ----------------------------------------------------------------------
# 6) window filter drops entries outside [start, end]
# ----------------------------------------------------------------------


def test_window_filter_drops_entries_outside_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [
        _entry(paper_trade_id="pt_pre", ledger_entry_ts_ms=1_699_999_999_000),
        _entry(paper_trade_id="pt_in", ledger_entry_ts_ms=1_700_000_001_500),
        _entry(paper_trade_id="pt_post", ledger_entry_ts_ms=1_700_000_011_000),
    ]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_window",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000010000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["entries_total_count"] == 3
    assert status["entries_in_window_count"] == 1
    assert status["entries_filtered_outside_window_count"] == 2
    assert status["replay_steps_count"] == 1
    assert status["replay_steps"][0]["paper_trade_id"] == "pt_in"


# ----------------------------------------------------------------------
# 7) paper_trade_id narrow replay returns the single matched step
# ----------------------------------------------------------------------


def test_paper_trade_id_narrow_replay_returns_single_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [
        _entry(paper_trade_id="pt_a", ledger_entry_ts_ms=1_700_000_001_000),
        _entry(paper_trade_id="pt_b", ledger_entry_ts_ms=1_700_000_002_000),
    ]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_narrow",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--paper-trade-id",
            "pt_b",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["fail_closed"] is False
    assert status["replay_steps_count"] == 1
    assert status["replay_steps"][0]["paper_trade_id"] == "pt_b"


# ----------------------------------------------------------------------
# 8) paper_trade_id not present in window fail-closes
# ----------------------------------------------------------------------


def test_paper_trade_id_not_in_window_fail_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [_entry(paper_trade_id="pt_a", ledger_entry_ts_ms=1_700_000_001_000)]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_notfound",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--paper-trade-id",
            "pt_missing",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["fail_closed_reason"] == "paper_trade_id_not_in_window"


# ----------------------------------------------------------------------
# 9) v2_paper_execution_worker status payload accepted as a single-entry source
# ----------------------------------------------------------------------


def test_paper_execution_worker_status_payload_accepted_as_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    payload: Dict[str, Any] = {
        "worker_id": UPSTREAM_PAPER_EXECUTION_WORKER_ID,
        "last_run_ts": "2026-05-14T05:00:00Z",
        "last_paper_trade_id": "pt_bridge_1",
        "last_paper_trade_ts_ms": 1_700_000_002_000,
        "last_risk_decision_id": "rd_bridge_1",
        "decision_id": "dec_bridge_1",
        "prediction_id": "pred_bridge_1",
        "feature_snapshot_id": "snap_bridge_1",
        "symbol": "BTCUSDT",
        "ledger_action": "record_allow",
        "ledger_reason_code": "mirror_allow_proceed_long",
        "input_risk_action": "allow",
        "input_risk_reason_code": "allow_proceed_long",
    }
    src = tmp_path / "paper_execution_worker_status.json"
    src.write_text(json.dumps(payload, indent=2))
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_bridge",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000010000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["fail_closed"] is False
    assert status["replay_steps_count"] == 1
    assert status["replay_steps"][0]["paper_trade_id"] == "pt_bridge_1"


# ----------------------------------------------------------------------
# 10) invalid ledger reason → service validator fail-closes the worker
# ----------------------------------------------------------------------


def test_invalid_ledger_reason_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    bogus = _entry(paper_trade_id="pt_bad", ledger_entry_ts_ms=1_700_000_001_000)
    bogus["ledger_reason_code"] = "not_a_real_reason"
    bogus["ledger_action"] = "record_allow"
    bogus["input_risk_action"] = "allow"
    bogus["input_risk_reason_code"] = "allow_proceed_long"
    src = _write_entries_file(tmp_path, [bogus])
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_invalid",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "INVALID_PAPER_LEDGER_ENTRY"


# ----------------------------------------------------------------------
# 11) no real exchange-mutation method names in worker source
# ----------------------------------------------------------------------


def test_no_exchange_mutation_method_names_in_source() -> None:
    text = Path(worker.__file__).read_text(encoding="utf-8")
    forbidden = [
        "create" + "_" + "order(",
        "cancel" + "_" + "order(",
        "create" + "_" + "market" + "_" + "order(",
        "futures" + "_" + "create" + "_" + "order(",
        "futures" + "_" + "cancel" + "_" + "order(",
        "set" + "_leverage(",
        "futures" + "_change_leverage(",
        "futures" + "_change_margin_type(",
    ]
    for name in forbidden:
        assert name not in text, f"forbidden exchange-mutation call in source: {name}"


# ----------------------------------------------------------------------
# 12) no Binance/ccxt/Redis imports in worker source
# ----------------------------------------------------------------------


def test_no_binance_ccxt_or_redis_imports_in_source() -> None:
    text = Path(worker.__file__).read_text(encoding="utf-8")
    for forbidden in (
        re.compile(r"^\s*import\s+redis", re.MULTILINE),
        re.compile(r"^\s*from\s+redis\b", re.MULTILINE),
        re.compile(r"^\s*import\s+ccxt", re.MULTILINE),
        re.compile(r"^\s*from\s+ccxt\b", re.MULTILINE),
        re.compile(r"^\s*from\s+binance\b", re.MULTILINE),
        re.compile(r"^\s*import\s+binance", re.MULTILINE),
    ):
        assert not forbidden.search(text), (
            f"forbidden import found in worker source: {forbidden.pattern}"
        )


# ----------------------------------------------------------------------
# 13) gate-always-blocked invariant
# ----------------------------------------------------------------------


def test_gate_always_blocked_invariant_in_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [_entry(paper_trade_id="pt_gate", ledger_entry_ts_ms=1_700_000_001_000)]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_gate",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["live_gate"] == LIVE_GATE_STATUS
    assert status["current_gate_state"] == LIVE_GATE_STATUS
    assert status["current_gate_state_must_equal_blocked_human_only"] is True
    assert status["gate_always_blocked_invariant"] is True
    assert status["exchange_action_taken"] is False
    assert status["exchange_call_invariant"] == EXCHANGE_CALL_INVARIANT
    assert status["live_blocked"] is True


# ----------------------------------------------------------------------
# 14) Symbol Universe contract on every payload
# ----------------------------------------------------------------------


def test_symbol_universe_contract_in_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [_entry(paper_trade_id="pt_uni", ledger_entry_ts_ms=1_700_000_001_000)]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_uni",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert (
        status["symbol_universe_public_payload_status"]
        == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    )
    assert status["symbol_universe_source_path"] == SYMBOL_UNIVERSE_SERVICE_PATH
    assert status["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert (
        status["legacy_active_symbol_source"]
        == "v2_symbol_universe_service:legacy_config.py_SYMBOLS_current_25"
    )
    assert status["legacy_active_symbols_public_payload_status"] == "NOT_PROVIDED"
    assert status["live_symbols"] == []
    assert status["passive_monitor_all_discovered_symbols"] is True
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["live_symbol_policy"] == "none_live_blocked_human_only"


# ----------------------------------------------------------------------
# 15) required public payload fields present (in payload AND on disk)
# ----------------------------------------------------------------------


def test_required_public_payload_fields_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    routes = _route_writes_to(tmp_path, monkeypatch)
    entries = [_entry(paper_trade_id="pt_req", ledger_entry_ts_ms=1_700_000_001_000)]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_req",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status, f"required field missing from payload: {field}"
    persisted = json.loads(
        (routes["public"] / f"{WORKER_ID}_status.json").read_text()
    )
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in persisted, f"required field missing on disk: {field}"


# ----------------------------------------------------------------------
# 16) legacy source paths cited
# ----------------------------------------------------------------------


def test_legacy_source_paths_cited(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [_entry(paper_trade_id="pt_leg", ledger_entry_ts_ms=1_700_000_001_000)]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_legacy",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["legacy_source_paths"] == list(LEGACY_SOURCE_PATHS)
    assert (
        "legacy_reference/scripts/replay_sanity_check.py"
        in status["legacy_source_paths"]
    )
    assert (
        "legacy_reference/rl/scripts/replay_decision.py"
        in status["legacy_source_paths"]
    )


# ----------------------------------------------------------------------
# 17) steps sorted by ledger_entry_ts_ms ascending
# ----------------------------------------------------------------------


def test_steps_sorted_chronologically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [
        _entry(paper_trade_id="pt_late", ledger_entry_ts_ms=1_700_000_003_000),
        _entry(paper_trade_id="pt_early", ledger_entry_ts_ms=1_700_000_001_000),
        _entry(paper_trade_id="pt_mid", ledger_entry_ts_ms=1_700_000_002_000),
    ]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_sorted",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000010000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    paper_trade_ids = [step["paper_trade_id"] for step in status["replay_steps"]]
    assert paper_trade_ids == ["pt_early", "pt_mid", "pt_late"]


# ----------------------------------------------------------------------
# 18) no legacy redis writer keys are introduced
# ----------------------------------------------------------------------


def test_worker_source_does_not_introduce_legacy_redis_writers() -> None:
    text = Path(worker.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "xadd(",
        "xrevrange(",
        "xrange(",
        "redis.Redis(",
        "Redis(host=",
        "signals:trading",
        "executed_signals",
    ):
        assert forbidden not in text, (
            f"replay worker must not reference legacy redis writer/key: {forbidden}"
        )


# ----------------------------------------------------------------------
# 19) public Symbol Universe payload cannot override canonical legacy 25
# ----------------------------------------------------------------------


def test_public_symbol_universe_payload_cannot_override_legacy_25(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    symbol_payload = tmp_path / "symbol_universe_status.json"
    symbol_payload.write_text(
        json.dumps(
            {
                "legacy_active_symbols": ["BTCUSDT"],
                "discovered_symbols": [
                    "BTCUSDT",
                    "DOGEUSDT",
                    "COINANKONLYUSDT",
                ],
                "dynamic_discovered_symbols": [
                    "BTCUSDT",
                    "DOGEUSDT",
                    "COINANKONLYUSDT",
                    "KUCOINONLYUSDT",
                ],
                "observed_symbols": ["BTCUSDT", "DOGEUSDT"],
                "training_symbols": ["BTCUSDT"],
                "paper_symbols": ["DOGEUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "DOGEUSDT"],
                "live_blocked_symbols": [
                    "BTCUSDT",
                    "DOGEUSDT",
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
    entries = [_entry(paper_trade_id="pt_symbol_payload", ledger_entry_ts_ms=1_700_000_001_000)]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_symbol_payload",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["symbol_universe_public_payload_status"] == "PRESENT"
    assert (
        status["legacy_active_symbols_public_payload_status"]
        == "PUBLIC_PAYLOAD_MISMATCH_IGNORED_CANONICAL_LEGACY_25_PRESERVED"
    )
    assert status["legacy_active_symbols"] == sorted(LEGACY_ACTIVE_SYMBOLS_25)
    assert status["dynamic_discovered_symbols"] == [
        "BTCUSDT",
        "COINANKONLYUSDT",
        "DOGEUSDT",
        "KUCOINONLYUSDT",
    ]
    assert status["training_symbols"] == ["BTCUSDT"]
    assert status["paper_symbols"] == ["DOGEUSDT"]
    assert status["live_symbols"] == []
    assert status["live_blocked_symbols"] == [
        "BTCUSDT",
        "COINANKONLYUSDT",
        "DOGEUSDT",
        "KUCOINONLYUSDT",
    ]
    assert status["coinank_symbols_tradability"] == (
        "market_intelligence_only_until_binance_usdm_confirmed"
    )
    assert status["binance_usdm_confirmed_symbols"] == ["BTCUSDT", "DOGEUSDT"]
    assert status["symbol_selection_score_factors"] == list(
        SYMBOL_SELECTION_SCORE_FACTORS
    )
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False


# ----------------------------------------------------------------------
# 20) legacy fetch_executions equivalent indexes executions by signal id
# ----------------------------------------------------------------------


def test_execution_index_by_signal_id_is_preserved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    entries = [
        _entry(
            paper_trade_id="pt_sig_2",
            ledger_entry_ts_ms=1_700_000_002_000,
            signal_id="sig_abc",
        ),
        _entry(
            paper_trade_id="pt_sig_1",
            ledger_entry_ts_ms=1_700_000_001_000,
            signal_id="sig_abc",
        ),
        _entry(
            paper_trade_id="pt_sig_other",
            ledger_entry_ts_ms=1_700_000_001_500,
            signal_id="sig_other",
        ),
    ]
    src = _write_entries_file(tmp_path, entries)
    args = parse_args(
        [
            "--once",
            "--replay-run-id",
            "rr_signal_index",
            "--symbol",
            "BTCUSDT",
            "--window-start-ms",
            "1700000000000",
            "--window-end-ms",
            "1700000003000",
            "--source-file",
            str(src),
        ]
    )
    status = run_once(args)
    assert status["legacy_fetch_executions_index_preserved"] is True
    assert status["executions_by_signal_id_count"] == 2
    assert status["executions_unindexed_count"] == 0
    assert list(status["executions_by_signal_id"]) == ["sig_abc", "sig_other"]
    assert [
        item["paper_trade_id"]
        for item in status["executions_by_signal_id"]["sig_abc"]
    ] == ["pt_sig_1", "pt_sig_2"]
