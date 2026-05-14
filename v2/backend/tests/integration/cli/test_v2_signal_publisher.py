from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_signal_publisher as worker
from v2.backend.app.cli.v2_signal_publisher import (
    CODEX_REVIEW_TRIGGER,
    CONSUMERS,
    DEFAULT_STALE_THRESHOLD_SECONDS,
    LIVE_GATE_STATUS,
    REQUIRED_PUBLIC_PAYLOAD_FIELDS,
    SYMBOL_UNIVERSE_CONTRACT,
    WORKER_ID,
    main,
    parse_args,
    run_once,
)
from v2.backend.app.services.symbol_universe.service import (
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
)


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
    monkeypatch.setattr(worker, "SOURCE_PAYLOAD_CANDIDATES", [tmp_path / "missing_lineage.json"])
    monkeypatch.setattr(worker, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES", [tmp_path / "missing_symbols.json"])
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _source_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "worker_id": "v2_signal_lineage_worker",
        "last_run_ts": worker.iso_now(),
        "fail_closed": False,
        "decision_record": {
            "decision_id": "dec_pred_001",
            "prediction_id": "pred_001",
            "feature_snapshot_id": "fs_001",
            "symbol": "BTCUSDT",
            "decision_action": "abstain",
            "decision_reason_code": "abstain_worker_unknown",
            "risk_gateway_binding": True,
            "cannot_bypass_risk_gateway": True,
            "orchestrator_overrides_risk": False,
            "live_blocked": True,
        },
        "legacy_active_symbols": list(LEGACY_ACTIVE_SYMBOLS_25),
        "dynamic_discovered_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "COINANK_ONLY_USDT"],
        "discovered_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT", "COINANK_ONLY_USDT"],
        "training_symbols": ["BTCUSDT", "ETHUSDT"],
        "paper_symbols": ["BTCUSDT"],
        "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
    }
    payload.update(overrides)
    return payload


def _write_source(tmp_path: Path, payload: Dict[str, Any]) -> Path:
    path = tmp_path / "source.json"
    path.write_text(json.dumps(payload))
    return path


def test_publishes_to_v2_consumers_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _source_payload())
    status = run_once(parse_args(["--once", "--source-file", str(src)]))

    assert status["fail_closed"] is False
    assert status["signals_published_total"] == len(CONSUMERS)
    assert status["consumer_count"] == len(CONSUMERS)
    assert status["route_to_execution"] is False
    assert status["execution_route_enabled"] is False
    assert status["live_gate"] == LIVE_GATE_STATUS
    for consumer in CONSUMERS:
        assert (paths["public"] / "consumers" / f"{consumer}_signal.json").exists()
        envelope = json.loads((paths["public"] / "consumers" / f"{consumer}_signal.json").read_text())
        assert envelope["consumer"] == consumer
        assert envelope["route_to_execution"] is False


def test_fail_closed_when_lineage_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    status = run_once(parse_args(["--once"]))

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "MISSING_RUNTIME_EVIDENCE"
    assert status["signals_published_total"] == 0


def test_fail_closed_when_upstream_fail_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _source_payload(fail_closed=True))
    status = run_once(parse_args(["--once", "--source-file", str(src)]))

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "UPSTREAM_FAIL_CLOSED"
    assert status["signals_published_total"] == 0


def test_fail_closed_when_source_stale(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _source_payload(last_run_ts="2026-01-01T00:00:00Z"))
    status = run_once(parse_args(["--once", "--source-file", str(src)]))

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "SOURCE_STALE"
    assert status["freshness_seconds"] is not None
    assert status["freshness_seconds"] > DEFAULT_STALE_THRESHOLD_SECONDS


def test_fail_closed_when_signal_identity_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    payload = _source_payload()
    payload["decision_record"].pop("prediction_id")
    src = _write_source(tmp_path, payload)
    status = run_once(parse_args(["--once", "--source-file", str(src)]))

    assert status["fail_closed"] is True
    assert status["runtime_evidence_status"] == "MISSING_SIGNAL_IDENTITY"


def test_symbol_universe_contract_required(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _source_payload())
    status = run_once(parse_args(["--once", "--source-file", str(src)]))

    assert status["symbol_universe_contract"] == SYMBOL_UNIVERSE_CONTRACT
    assert status["symbol_universe_public_payload_status"] == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    assert status["legacy_active_symbols"] == LEGACY_ACTIVE_SYMBOLS_25
    assert len(status["legacy_active_symbols"]) == 25
    assert status["dynamic_discovered_symbols"] == ["BTCUSDT", "COINANK_ONLY_USDT", "ETHUSDT", "SOLUSDT"]
    assert status["training_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert status["paper_symbols"] == ["BTCUSDT"]
    assert status["live_symbols"] == []
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["coinank_symbols_tradability"] == "market_intelligence_only_until_binance_usdm_confirmed"
    assert status["symbol_selection_score_factors"] == list(SYMBOL_SELECTION_SCORE_FACTORS)


def test_public_symbol_payload_overrides_source_scope(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    symbol_path = tmp_path / "symbols.json"
    symbol_path.write_text(
        json.dumps(
            {
                "legacy_active_symbols": list(LEGACY_ACTIVE_SYMBOLS_25),
                "dynamic_discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANK_ONLY_USDT"],
                "discovered_symbols": ["BTCUSDT", "ETHUSDT", "COINANK_ONLY_USDT"],
                "training_symbols": ["ETHUSDT"],
                "paper_symbols": ["BTCUSDT"],
                "binance_usdm_confirmed_symbols": ["BTCUSDT", "ETHUSDT"],
            }
        )
    )
    monkeypatch.setattr(worker, "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES", [symbol_path])
    src = _write_source(tmp_path, _source_payload())
    status = run_once(parse_args(["--once", "--source-file", str(src)]))

    assert status["symbol_universe_public_payload_status"] == "PRESENT"
    assert status["training_symbols"] == ["ETHUSDT"]
    assert status["paper_symbols"] == ["BTCUSDT"]
    assert status["live_symbols"] == []


def test_required_public_payload_fields_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _source_payload())
    status = run_once(parse_args(["--once", "--source-file", str(src)]))

    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in status
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    for field in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert field in written


def test_codex_review_trigger_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _source_payload())
    status = run_once(parse_args(["--once", "--source-file", str(src)]))
    assert status["codex_review_trigger"] == CODEX_REVIEW_TRIGGER


def test_no_write_does_not_emit_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    src = _write_source(tmp_path, _source_payload())
    rc = main(["--once", "--no-write", "--source-file", str(src)])
    assert rc == 0
    assert not (paths["public"] / f"{WORKER_ID}_status.json").exists()


def test_worker_source_no_execution_or_mutation_tokens() -> None:
    source = Path(worker.__file__).read_text()
    forbidden = [
        "create" + "_order",
        "cancel" + "_order",
        "futures" + "_create" + "_order",
        "futures" + "_change" + "_leverage",
        "futures" + "_change" + "_margin_type",
        "import re" + "dis",
        "from re" + "dis",
        ".x" + "add(",
        ".h" + "set(",
    ]
    for token in forbidden:
        assert token not in source
