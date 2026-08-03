"""P0.5 integration tests: native ingestors verification."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]


def _venv_python() -> str:
    cand = REPO / ".venv/bin/python"
    return str(cand) if cand.exists() else sys.executable


def test_registry_lists_all_required_ingestors() -> None:
    from v2.backend.app.services.native_ingestors import INGESTOR_REGISTRY

    required = {
        "live_binance", "live_binance_liquidations", "live_coinank",
        "live_coinank_global_aggregator", "live_kucoin", "live_coinapi_v1",
        "live_coinapi_wsds", "live_technical_analysis",
        "realtime_price_provider", "liquidation_bridge",
        "liquidation_levels_engine", "ccxt_historical",
    }
    names = {row[0] for row in INGESTOR_REGISTRY}
    assert required.issubset(names), f"missing names: {required - names}"


def test_classify_all_ingestors_uses_allowed_classifications() -> None:
    from v2.backend.app.services.native_ingestors import (
        IngestorRecord,
        classify_all_ingestors,
    )

    allowed = {
        "NATIVE_V2", "NATIVE_V2_READONLY_PUBLIC_DATA",
        "READONLY_BRIDGED", "MISSING_IN_V2",
        "BLOCKED_BY_SECRET_OR_API", "BLOCKED_BY_RATE_LIMIT",
        "OPERATOR_DECISION_REQUIRED",
        "OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN",
    }
    records = classify_all_ingestors()
    assert len(records) >= 12
    for r in records:
        assert isinstance(r, IngestorRecord)
        assert r.classification.classification in allowed
        assert r.classification.public_market_data_only is True


def test_ingestors_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.native_ingestors import (
        ingestors_invariants_snapshot,
    )

    s = ingestors_invariants_snapshot()
    assert s["imports_redis"] is False
    assert s["imports_exchange_sdk"] is False
    assert s["performs_network_io"] is False
    assert s["writes_legacy_redis"] is False
    assert s["places_exchange_orders"] is False
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []


def test_cli_writes_status_payload(tmp_path: Path) -> None:
    out = tmp_path / "v2_native_ingestors_status.json"
    cmd = [
        _venv_python(),
        "-m",
        "v2.backend.app.cli.v2_native_ingestors_worker",
        "--write-evidence",
        "--out",
        str(out),
    ]
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert out.exists()
    body = json.loads(out.read_text())
    assert body["worker_id"] == "v2_native_ingestors"
    assert body["live_gate"] == "blocked_human_only"
    assert body["live_symbols"] == []
    assert body["approves_live"] is False
    assert body["ingestor_count"] >= 12
    classes = {r["classification"] for r in body["ingestors"]}
    assert classes.issubset({
        "NATIVE_V2", "NATIVE_V2_READONLY_PUBLIC_DATA",
        "READONLY_BRIDGED", "MISSING_IN_V2",
        "BLOCKED_BY_SECRET_OR_API", "BLOCKED_BY_RATE_LIMIT",
        "OPERATOR_DECISION_REQUIRED",
        "OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN",
    })
