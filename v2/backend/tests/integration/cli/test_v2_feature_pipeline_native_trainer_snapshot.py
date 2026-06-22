"""Trainer-consumable snapshot tests for the V2 native feature pipeline."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


def _venv_python() -> str:
    cand = REPO / ".venv/bin/python"
    return str(cand) if cand.exists() else sys.executable


# ----------------------------------------------------------- service-level


def test_emit_trainer_consumable_snapshot_has_required_keys() -> None:
    from v2.backend.app.services.feature_pipeline_native.service import (
        FeaturePipelineNativeService,
    )

    svc = FeaturePipelineNativeService()
    inputs = svc.build_deterministic_default_inputs("BTCUSDT", "1m", "2026-05-16T00:00:00+00:00")
    out = svc.emit_trainer_consumable_snapshot(inputs)
    for key in (
        "schema_version",
        "worker_id",
        "feature_snapshot_id",
        "generated_at",
        "symbol",
        "timeframe",
        "features",
        "feature_count",
        "categories_present",
        "missing_feature_flags",
        "stale_feature_flags",
        "source_inputs",
        "source_freshness_seconds",
        "feature_freshness_state",
        "trainer_consumable",
        "live_gate",
        "live_symbols",
        "approves_live",
        "approves_canary",
        "approves_legacy_shutdown",
    ):
        assert key in out, f"missing key: {key}"
    assert out["schema_version"] == "v2_native_feature_snapshot_v1"
    assert out["worker_id"] == "v2_feature_pipeline_native"
    assert out["feature_snapshot_id"].startswith("v2_fsnap_")
    assert out["trainer_consumable"] is True
    assert out["live_gate"] == "blocked_human_only"
    assert out["live_symbols"] == []
    assert out["approves_live"] is False
    assert out["approves_canary"] is False
    assert out["approves_legacy_shutdown"] is False


def test_emit_trainer_consumable_snapshot_features_non_empty_categories_non_empty() -> None:
    from v2.backend.app.services.feature_pipeline_native.service import (
        FeaturePipelineNativeService,
    )

    svc = FeaturePipelineNativeService()
    inputs = svc.build_deterministic_default_inputs("BTCUSDT", "1m", "2026-05-16T00:00:00+00:00")
    out = svc.emit_trainer_consumable_snapshot(inputs)
    assert isinstance(out["features"], dict) and len(out["features"]) >= 10
    assert isinstance(out["categories_present"], list) and len(out["categories_present"]) >= 1


def test_feature_snapshot_id_deterministic_for_same_inputs() -> None:
    from v2.backend.app.services.feature_pipeline_native.service import (
        FeaturePipelineNativeService,
    )

    svc = FeaturePipelineNativeService()
    inputs1 = svc.build_deterministic_default_inputs("BTCUSDT", "1m", "2026-05-16T00:00:00+00:00")
    inputs2 = svc.build_deterministic_default_inputs("BTCUSDT", "1m", "2026-05-16T00:00:00+00:00")
    a = svc.emit_trainer_consumable_snapshot(inputs1)
    b = svc.emit_trainer_consumable_snapshot(inputs2)
    # generated_at is from inputs.generated_utc so identical when fed the same arg
    assert a["feature_snapshot_id"] == b["feature_snapshot_id"]


def test_missing_and_stale_flags_are_explicit_arrays() -> None:
    from v2.backend.app.services.feature_pipeline_native.service import (
        FeaturePipelineNativeService,
        NativeFeatureInputs,
    )

    svc = FeaturePipelineNativeService()
    empty = NativeFeatureInputs(symbol="BTCUSDT", timeframe="1m", generated_utc="2026-05-16T00:00:00+00:00")
    out = svc.emit_trainer_consumable_snapshot(empty)
    assert isinstance(out["missing_feature_flags"], list) and len(out["missing_feature_flags"]) >= 1
    assert isinstance(out["stale_feature_flags"], list)
    assert out["feature_freshness_state"] in {"CURRENT", "STALE", "MISSING"}
    assert out["trainer_consumable"] is True
    assert out["live_gate"] == "blocked_human_only"
    assert out["live_symbols"] == []


def test_no_redis_or_exchange_imports_in_service_module() -> None:
    text = (REPO / "v2/backend/app/services/feature_pipeline_native/service.py").read_text()
    for forbidden in ("import redis", "from redis", "import ccxt", "from ccxt", "import binance"):
        assert forbidden not in text


# ----------------------------------------------------------- CLI-level


def test_cli_emit_latest_snapshot_creates_both_files(tmp_path: Path) -> None:
    public_out = tmp_path / "public_snapshot.json"
    runtime_out = tmp_path / "runtime_snapshot.json"
    status_out = tmp_path / "status.json"
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    cmd = [
        _venv_python(),
        "-m",
        "v2.backend.app.cli.v2_feature_pipeline_native",
        "--emit-latest-snapshot",
        "--symbol",
        "BTCUSDT",
        "--timeframe",
        "1m",
        "--snapshot-public-out",
        str(public_out),
        "--snapshot-runtime-out",
        str(runtime_out),
        "--out",
        str(status_out),
    ]
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert public_out.exists()
    assert runtime_out.exists()
    public_payload = json.loads(public_out.read_text())
    runtime_payload = json.loads(runtime_out.read_text())
    assert public_payload == runtime_payload
    assert public_payload["trainer_consumable"] is True
    assert public_payload["feature_snapshot_id"].startswith("v2_fsnap_")
    assert isinstance(public_payload["features"], dict) and len(public_payload["features"]) >= 10
    assert isinstance(public_payload["categories_present"], list) and len(public_payload["categories_present"]) >= 1
    assert public_payload["live_gate"] == "blocked_human_only"
    assert public_payload["live_symbols"] == []
    assert public_payload["approves_live"] is False


def test_cli_emit_latest_snapshot_also_writes_status(tmp_path: Path) -> None:
    public_out = tmp_path / "public_snapshot.json"
    runtime_out = tmp_path / "runtime_snapshot.json"
    status_out = tmp_path / "status.json"
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    cmd = [
        _venv_python(),
        "-m",
        "v2.backend.app.cli.v2_feature_pipeline_native",
        "--emit-latest-snapshot",
        "--snapshot-public-out",
        str(public_out),
        "--snapshot-runtime-out",
        str(runtime_out),
        "--out",
        str(status_out),
    ]
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert status_out.exists()
    status_payload = json.loads(status_out.read_text())
    assert status_payload["live_gate"] == "blocked_human_only"
    assert status_payload["live_symbols"] == []
    assert status_payload["approves_live"] is False


def test_cli_emit_latest_snapshot_default_inputs_yield_categories_and_freshness_current(tmp_path: Path) -> None:
    public_out = tmp_path / "public_snapshot.json"
    runtime_out = tmp_path / "runtime_snapshot.json"
    status_out = tmp_path / "status.json"
    env = {"PYTHONPATH": str(REPO), "PATH": "/usr/bin:/bin"}
    cmd = [
        _venv_python(),
        "-m",
        "v2.backend.app.cli.v2_feature_pipeline_native",
        "--emit-latest-snapshot",
        "--snapshot-public-out",
        str(public_out),
        "--snapshot-runtime-out",
        str(runtime_out),
        "--out",
        str(status_out),
    ]
    result = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    payload = json.loads(public_out.read_text())
    # The deterministic defaults seed FRESH ages, so the freshness state is CURRENT.
    assert payload["feature_freshness_state"] == "CURRENT"
    for cat in (
        "ohlcv_derived",
        "ta_indicators",
        "multi_timeframe",
        "microstructure",
        "funding_oi_liquidation",
        "portfolio_aware",
        "freshness",
    ):
        assert cat in payload["categories_present"]
