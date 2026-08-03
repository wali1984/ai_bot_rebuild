"""Integration tests for the v2_feature_pipeline_and_ta_worker CLI worker.

Covers:
  1. unified_features_built_from_snapshot_into_v2_namespaced_data_plane
  2. ta_indicators_preserve_legacy_indicator_set
  3. ohlcv_resampler_writes_six_fields_with_legacy_tf_expiry_map
  4. universe_validation_uses_legacy_freshness_thresholds_and_retry_window
  5. paralysis_detector_emits_sustained_bucket_alert_into_public_payload
  6. no_old_redis_write_contract
  7. no_real_exchange_mutating_method_invoked_contract
  8. baseline_sha256_matches_copied_baseline_manifest_contract
 9. live_gate_is_always_blocked_human_only
10. data_plane_keys_use_v2_features_prefix_only
 11. symbol_universe_contract_required
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_feature_pipeline_and_ta_worker as worker
from v2.backend.app.cli.v2_feature_pipeline_and_ta_worker import (
    LEGACY_BASELINE_SHA256,
    LIVE_GATE_STATUS,
    WORKER_ID,
    main,
    parse_args,
    run_once,
    verify_baseline_shas,
)
from v2.backend.app.services.feature_pipeline_and_ta.service import (
    FAST_TIMEFRAMES,
    LEGACY_TA_INDICATOR_FAMILIES_PRESERVED,
    LEGACY_FEATURE_FAMILIES_DEFERRED_WITH_REASON,
    LEGACY_FEATURE_FAMILIES_PRESERVED,
    LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON,
    LEGACY_TA_LIBRARY,
    OHLCV_RESAMPLER_TF_EXPIRY_SEC,
    PARALYSIS_DETECTOR_DEFAULT_MINUTES,
    SLOW_TIMEFRAMES,
    STARTUP_VALIDATE_RETRIES,
    STARTUP_VALIDATE_SLEEP_SEC,
    V2_KEY_PREFIX,
    VALIDATE_FAST_TF_MAX_AGE_SEC,
    VALIDATE_MIN_CANDLES,
    VALIDATE_ORDERBOOK_STALE_SEC,
    VALIDATE_SLOW_TF_MAX_AGE_SEC,
    FeaturePipelineAndTAService,
)
from v2.backend.app.services.symbol_universe.service import (
    LEGACY_ACTIVE_SYMBOLS_25,
    SYMBOL_SELECTION_SCORE_FACTORS,
)


# ----------------------------------------------------------------------
# helpers / fixtures
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
    monkeypatch.setattr(
        worker,
        "WORKER_STATUS_FILE",
        worker_dir / f"{WORKER_ID}_from_legacy_baseline_status.json",
    )
    monkeypatch.setattr(
        worker,
        "DATA_PLANE_FILE",
        local_dir / "v2_feature_pipeline_and_ta_data_plane.json",
    )
    monkeypatch.setattr(
        worker,
        "SYMBOL_UNIVERSE_PUBLIC_PAYLOAD_CANDIDATES",
        [
            tmp_path / "v2" / "frontend" / "public" / "operator_runtime" / "symbol_universe" / "latest" / "symbol_universe_status.json",
            tmp_path / "v2" / "frontend" / "public" / "symbol_universe" / "latest" / "symbol_universe_status.json",
        ],
    )
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _build_candles(count: int, base: float = 60_000.0, ts_start_ms: int = 1_715_500_000_000) -> List[Dict[str, Any]]:
    candles: List[Dict[str, Any]] = []
    price = base
    for i in range(count):
        # Smooth trend with small oscillation so RSI/MACD/ATR are well-defined.
        price = base + (i * 5.0) + ((-1) ** i) * 2.0
        candles.append(
            {
                "ts_ms": ts_start_ms + i * 60_000,
                "open": price - 1.0,
                "high": price + 3.0,
                "low": price - 3.0,
                "close": price,
                "volume": 1.0 + i * 0.01,
            }
        )
    return candles


def _build_snapshot(symbols: List[str], timeframes: List[str], *, fresh_now_ms: int) -> Dict[str, Any]:
    per_symbol: Dict[str, Any] = {}
    for sym in symbols:
        tfs: Dict[str, Any] = {}
        for tf in timeframes:
            candles = _build_candles(120, ts_start_ms=fresh_now_ms - 120 * 60_000)
            last = candles[-1]
            tfs[tf] = {
                "market": {
                    "open": last["open"],
                    "high": last["high"],
                    "low": last["low"],
                    "close": last["close"],
                    "volume": last["volume"],
                    "timestamp": last["ts_ms"],
                },
                "unified": {"ts_ms": fresh_now_ms},
                "ohlcv_list": candles,
            }
        per_symbol[sym] = {
            "orderbook_top": {
                "bid": 60_049.9,
                "ask": 60_050.1,
                "ts_ms": fresh_now_ms,
            },
            "mark": {
                "mark_price": 60_051.0,
                "index_price": 60_045.0,
                "basis_pct": 0.001,
                "last_funding_rate": 0.0001,
            },
            "timeframes": tfs,
        }
    return {
        "symbols": symbols,
        "timeframes": timeframes,
        "per_symbol": per_symbol,
        "snapshot_source": "test_fixture",
    }


@pytest.fixture
def freshly_built_snapshot_file(tmp_path: Path) -> Path:
    fresh_now_ms = 1_715_500_120_000
    snap = _build_snapshot(["BTCUSDT"], ["1m"], fresh_now_ms=fresh_now_ms)
    path = tmp_path / "snapshot.json"
    path.write_text(json.dumps(snap))
    return path


# ----------------------------------------------------------------------
# 1) unified features built into v2 namespaced data plane
# ----------------------------------------------------------------------


def test_unified_features_built_from_snapshot_into_v2_namespaced_data_plane(
    freshly_built_snapshot_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once", "--input-file", str(freshly_built_snapshot_file)])
    status = run_once(args)
    assert status["worker_id"] == WORKER_ID

    unified_keys = status["v2_keys_written"]["unified_features"]
    assert any(k.endswith(":BTCUSDT:1m:unified") for k in unified_keys)
    for k in unified_keys:
        assert k.startswith(V2_KEY_PREFIX), f"unified key not v2-namespaced: {k!r}"

    # Persisted on disk
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    assert written["worker_id"] == WORKER_ID
    data_plane = json.loads(
        (paths["local"] / "v2_feature_pipeline_and_ta_data_plane.json").read_text()
    )
    assert any(k.startswith(f"{V2_KEY_PREFIX}:BTCUSDT") for k in data_plane.keys())


def test_symbol_universe_contract_required_in_public_payload(
    freshly_built_snapshot_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    snapshot = json.loads(freshly_built_snapshot_file.read_text())
    snapshot["dynamic_discovered_symbols"] = [
        "BTCUSDT",
        "ETHUSDT",
        "SOLUSDT",
        "COINANK_ONLY_USDT",
        "KUCOIN_ONLY_USDT",
    ]
    snapshot["training_symbols"] = ["BTCUSDT", "ETHUSDT"]
    snapshot["paper_symbols"] = ["BTCUSDT"]
    scoped_snapshot = tmp_path / "scoped_snapshot.json"
    scoped_snapshot.write_text(json.dumps(snapshot))

    args = parse_args(["--once", "--input-file", str(scoped_snapshot)])
    status = run_once(args)

    assert status["symbol_universe_contract"] == "SYMBOL_UNIVERSE_CONTRACT_REQUIRED"
    assert status["symbol_universe_source_path"] == "v2/backend/app/services/symbol_universe/service.py"
    assert status["symbol_universe_public_payload_status"] == "MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD"
    assert status["legacy_active_symbol_source"] == "legacy_config.py_SYMBOLS_current_25"
    assert status["legacy_active_symbols"] == LEGACY_ACTIVE_SYMBOLS_25
    assert status["observed_symbols"] == ["BTCUSDT"]
    assert status["dynamic_discovered_symbols"] == [
        "BTCUSDT",
        "COINANK_ONLY_USDT",
        "ETHUSDT",
        "KUCOIN_ONLY_USDT",
        "SOLUSDT",
    ]
    assert status["discovered_symbols"] == status["dynamic_discovered_symbols"]
    assert status["training_symbols"] == ["BTCUSDT", "ETHUSDT"]
    assert status["paper_symbols"] == ["BTCUSDT"]
    assert status["live_symbols"] == []
    assert set(status["live_blocked_symbols"]) == set(status["dynamic_discovered_symbols"])
    assert status["binance_usdm_confirmed_symbols"] == []
    assert status["symbol_scope_policy"] == "do_not_train_or_trade_all_discovered_symbols_automatically"
    assert status["passive_monitor_all_discovered_symbols"] is True
    assert status["train_all_discovered_symbols"] is False
    assert status["trade_all_discovered_symbols"] is False
    assert status["live_symbol_policy"] == "none_live_blocked_human_only"
    assert status["symbol_selection_score_factors"] == SYMBOL_SELECTION_SCORE_FACTORS
    assert set(status["training_symbols"]) < set(status["dynamic_discovered_symbols"])
    assert set(status["paper_symbols"]) < set(status["dynamic_discovered_symbols"])


# ----------------------------------------------------------------------
# 2) TA indicator set preserved
# ----------------------------------------------------------------------


def test_ta_indicators_preserve_legacy_indicator_set(
    freshly_built_snapshot_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once", "--input-file", str(freshly_built_snapshot_file)])
    status = run_once(args)

    # Service constant declares which legacy library the V2 worker preserves
    # naming from (talib).
    assert LEGACY_TA_LIBRARY == "talib"
    for family in ("RSI", "MACD", "ATR", "SMA", "EMA"):
        assert family in LEGACY_TA_INDICATOR_FAMILIES_PRESERVED

    # The TA payload uses the legacy ta_* naming convention.
    svc = FeaturePipelineAndTAService()
    candles = _build_candles(120)
    res = svc.compute_ta_indicators("BTCUSDT", "1m", candles)
    assert "ta_RSI_14" in res.indicators
    assert "ta_MACD_12_26_9_macd" in res.indicators
    assert "ta_MACD_12_26_9_signal" in res.indicators
    assert "ta_MACD_12_26_9_hist" in res.indicators
    assert "ta_ATR_14" in res.indicators
    assert "ta_SMA_20" in res.indicators
    assert "ta_EMA_20" in res.indicators

    ta_keys = status["v2_keys_written"]["ta"]
    assert any(k.endswith(":BTCUSDT:1m:ta") for k in ta_keys)


def test_legacy_ta_surface_has_explicit_coverage_or_defer_reason() -> None:
    legacy_whitelist_families = {
        "AD",
        "ADX",
        "AROON",
        "ATR",
        "BOP",
        "CCI",
        "CDL_PATTERNS",
        "EMA",
        "HT_TRENDMODE",
        "MACD",
        "MINUS_DI",
        "MOM",
        "NATR",
        "OBV",
        "PLUS_DI",
        "RSI",
        "SMA",
        "STOCHRSI",
        "TRIX",
        "ULTOSC",
        "WILLR",
    }
    implemented = set(LEGACY_TA_INDICATOR_FAMILIES_PRESERVED)
    deferred = set(LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON)
    assert implemented | deferred == legacy_whitelist_families
    assert implemented & deferred == set()
    assert all(LEGACY_TA_INDICATOR_FAMILIES_DEFERRED_WITH_REASON[f] for f in deferred)


def test_legacy_feature_surface_has_explicit_coverage_or_defer_reason() -> None:
    legacy_feature_families = {
        "binance_tape",
        "btc_correlation",
        "coinank_endpoint_family",
        "coinapi_wsds_depth",
        "cross_timeframe_context",
        "kline_taker_buy_ratios",
        "mark_funding",
        "ohlcv",
        "orderbook_top",
        "pressure",
        "ta_passthrough",
        "volatility",
    }
    implemented = set(LEGACY_FEATURE_FAMILIES_PRESERVED)
    deferred = set(LEGACY_FEATURE_FAMILIES_DEFERRED_WITH_REASON)
    assert implemented | deferred == legacy_feature_families
    assert implemented & deferred == set()
    assert all(LEGACY_FEATURE_FAMILIES_DEFERRED_WITH_REASON[f] for f in deferred)


# ----------------------------------------------------------------------
# 3) OHLCV resampler 6 fields + legacy TF expiry map preserved
# ----------------------------------------------------------------------


def test_ohlcv_resampler_writes_six_fields_with_legacy_tf_expiry_map() -> None:
    svc = FeaturePipelineAndTAService()
    market = {
        "open": 60000.0,
        "high": 60100.0,
        "low": 59900.0,
        "close": 60050.0,
        "volume": 12.34,
        "timestamp": 1_715_500_120_000,
    }
    for tf, expected_expiry in OHLCV_RESAMPLER_TF_EXPIRY_SEC.items():
        res = svc.resample_ohlcv("BTCUSDT", tf, market)
        assert sorted(res.fields.keys()) == sorted(["open", "high", "low", "close", "volume", "ts_ms"])
        assert res.expiry_seconds == expected_expiry
        assert res.v2_key is not None
        assert res.v2_key.startswith(V2_KEY_PREFIX)

    # Legacy expiry map is preserved verbatim:
    assert OHLCV_RESAMPLER_TF_EXPIRY_SEC == {"5m": 600, "15m": 1800, "1h": 7200, "4h": 28800}


# ----------------------------------------------------------------------
# 4) Universe validation thresholds + retry window preserved
# ----------------------------------------------------------------------


def test_universe_validation_uses_legacy_freshness_thresholds_and_retry_window() -> None:
    # Legacy default thresholds (validate_symbol_universe_data.py L70-76).
    assert VALIDATE_ORDERBOOK_STALE_SEC == 10.0
    assert VALIDATE_FAST_TF_MAX_AGE_SEC == 90.0
    assert VALIDATE_SLOW_TF_MAX_AGE_SEC == 600.0
    assert VALIDATE_MIN_CANDLES == 50
    # Legacy retry window (start_all_services_production.sh L646-647).
    assert STARTUP_VALIDATE_RETRIES == 10
    assert STARTUP_VALIDATE_SLEEP_SEC == 15

    svc = FeaturePipelineAndTAService()
    fresh_now_ms = 1_715_500_120_000

    # Fresh snapshot should pass validation:
    fresh_snap = _build_snapshot(["BTCUSDT"], ["1m"], fresh_now_ms=fresh_now_ms)
    fresh_result = svc.validate_universe_coverage(
        fresh_snap, now_ms=fresh_now_ms, symbols=["BTCUSDT"], timeframes=["1m"]
    )
    assert fresh_result.passed, f"unexpected issues: {[i.code for i in fresh_result.issues]}"

    # Stale orderbook (20s old) violates the 10s default threshold:
    stale_snap = _build_snapshot(["BTCUSDT"], ["1m"], fresh_now_ms=fresh_now_ms)
    stale_snap["per_symbol"]["BTCUSDT"]["orderbook_top"]["ts_ms"] = fresh_now_ms - 20_000
    stale_result = svc.validate_universe_coverage(
        stale_snap, now_ms=fresh_now_ms, symbols=["BTCUSDT"], timeframes=["1m"]
    )
    assert not stale_result.passed
    assert any("orderbook:stale" in i.code for i in stale_result.issues)

    # Default retry/sleep are surfaced on the result:
    assert fresh_result.retries_remaining == STARTUP_VALIDATE_RETRIES
    assert fresh_result.sleep_seconds_between_retries == STARTUP_VALIDATE_SLEEP_SEC


# ----------------------------------------------------------------------
# 5) Paralysis detector sustained-bucket alerts via public payload (NOT
#    legacy redis stream)
# ----------------------------------------------------------------------


def test_paralysis_detector_emits_sustained_bucket_alert_into_public_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fresh_now_ms = 1_715_500_120_000
    snap = _build_snapshot(["BTCUSDT"], ["1m"], fresh_now_ms=fresh_now_ms)
    # 5 sustained MICROSTRUCTURE_FAIL_CLOSED events spread across 5 minute
    # buckets (one per minute) — matches legacy "sustained" definition:
    snap["paralysis_events"] = [
        {"ts_ms": fresh_now_ms - i * 60_000, "reason_code": "MICROSTRUCTURE_FAIL_CLOSED"}
        for i in range(5)
    ]
    paths = _route_writes_to(tmp_path, monkeypatch)
    snap_path = tmp_path / "snap.json"
    snap_path.write_text(json.dumps(snap))
    args = parse_args(
        [
            "--once",
            "--input-file",
            str(snap_path),
            "--paralysis-window-minutes",
            "5.0",
        ]
    )
    status = run_once(args)
    paralysis = status["paralysis_detector"]["result"]
    alerts = paralysis["alerts"]
    assert any(a["reason"] == "MICROSTRUCTURE_FAIL_CLOSED" for a in alerts)
    sustained_alert = [a for a in alerts if a["reason"] == "MICROSTRUCTURE_FAIL_CLOSED"][0]
    assert sustained_alert["sustained_buckets"] >= 5

    # Alerts surface via the public payload, NOT via a legacy Redis stream.
    written = json.loads((paths["public"] / f"{WORKER_ID}_status.json").read_text())
    assert written["paralysis_detector"]["result"]["alerts"]


# ----------------------------------------------------------------------
# 6) no legacy redis writes contract
# ----------------------------------------------------------------------


def test_no_old_redis_write_contract() -> None:
    forbidden_key_substrings = [
        '"market:',
        "'market:",
        '"unified_features:',
        "'unified_features:",
        '"ta:',
        "'ta:",
        '"latest:binance:',
        "'latest:binance:",
        '"price:',
        "'price:",
        '"ohlcv:list:',
        "'ohlcv:list:",
        '"orderbook:top:',
        "'orderbook:top:",
        '"signals:execution:skips',
        "'signals:execution:skips",
        '"executed_signals',
        "'executed_signals",
        '"portfolio:equity:',
        "'portfolio:equity:",
        '"features:resampler:',
        "'features:resampler:",
        '"features:coinank:',
        "'features:coinank:",
        '"features:coinank_endpoint:',
        "'features:coinank_endpoint:",
        '"msnap:coinapi_wsds:',
        "'msnap:coinapi_wsds:",
        '"msnap:binance_tape:',
        "'msnap:binance_tape:",
        '"metrics:coinapi:',
        "'metrics:coinapi:",
    ]
    cli_source = Path(worker.__file__).read_text()
    from v2.backend.app.services.feature_pipeline_and_ta import service as svc_module

    svc_source = Path(svc_module.__file__).read_text()
    for forbidden in forbidden_key_substrings:
        assert forbidden not in cli_source, f"legacy redis key write found in CLI: {forbidden}"
        assert forbidden not in svc_source, f"legacy redis key write found in service: {forbidden}"

    # And: V2 prefix is used.
    assert "v2:features" in svc_source
    assert V2_KEY_PREFIX == "v2:features"


# ----------------------------------------------------------------------
# 7) no real-exchange mutating method invoked contract
# ----------------------------------------------------------------------


def test_no_real_exchange_mutating_method_invoked_contract() -> None:
    forbidden_methods = [
        "futures_create" + "_order",
        "futures_change" + "_leverage",
        "futures_change" + "_margin_type",
        "create" + "_order",
        "cancel" + "_order",
        "set" + "_leverage",
        "set" + "_margin_mode",
    ]
    cli_source = Path(worker.__file__).read_text()
    from v2.backend.app.services.feature_pipeline_and_ta import service as svc_module

    svc_source = Path(svc_module.__file__).read_text()
    for sub in forbidden_methods:
        assert sub not in cli_source, f"forbidden exchange mutating method in CLI: {sub}"
        assert sub not in svc_source, f"forbidden exchange mutating method in service: {sub}"


# ----------------------------------------------------------------------
# 8) baseline SHA256 matches copied_baseline_manifest contract
# ----------------------------------------------------------------------


def test_baseline_sha256_matches_copied_baseline_manifest_contract() -> None:
    manifest_path = (
        REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "legacy_startup_baseline_v2_migration"
        / "latest"
        / "copied_baseline_manifest.json"
    )
    assert manifest_path.exists(), f"manifest not found at {manifest_path}"
    manifest = json.loads(manifest_path.read_text())
    by_path = {
        rec["v2_preserved_path"]: rec["sha256"]
        for rec in manifest.get("records", [])
        if rec.get("v2_preserved_path") and rec.get("sha256")
    }
    for v2_path, expected in LEGACY_BASELINE_SHA256.items():
        assert v2_path in by_path, f"baseline path missing from manifest: {v2_path}"
        assert by_path[v2_path] == expected, (
            f"SHA mismatch for {v2_path}: manifest={by_path[v2_path]} vs expected={expected}"
        )

    # And: the verify_baseline_shas helper agrees.
    report = verify_baseline_shas(manifest_path)
    assert report["ok"] is True
    assert report["mismatches"] == []

    # And: the SHA we embed actually matches a recomputed SHA on disk.
    for v2_path, expected in LEGACY_BASELINE_SHA256.items():
        on_disk = REPO_ROOT / v2_path
        if on_disk.exists():
            digest = hashlib.sha256(on_disk.read_bytes()).hexdigest()
            assert digest == expected, (
                f"on-disk SHA for {v2_path}={digest} but constant says {expected}"
            )


# ----------------------------------------------------------------------
# 9) live gate is permanently blocked_human_only
# ----------------------------------------------------------------------


def test_live_gate_is_always_blocked_human_only(
    freshly_built_snapshot_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once", "--input-file", str(freshly_built_snapshot_file)])
    status = run_once(args)
    assert status["live_gate"] == LIVE_GATE_STATUS == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"


# ----------------------------------------------------------------------
# 10) data plane keys must use v2:features prefix only
# ----------------------------------------------------------------------


def test_data_plane_keys_use_v2_features_prefix_only(
    freshly_built_snapshot_file: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    args = parse_args(["--once", "--input-file", str(freshly_built_snapshot_file)])
    run_once(args)
    data_plane = json.loads(
        (paths["local"] / "v2_feature_pipeline_and_ta_data_plane.json").read_text()
    )
    for key in data_plane.keys():
        assert key.startswith(V2_KEY_PREFIX), f"non-V2 key persisted: {key!r}"


# ----------------------------------------------------------------------
# extra coverage: lane intervals and TA cadence preserved
# ----------------------------------------------------------------------


def test_lane_intervals_preserve_legacy_dual_speed_pipeline_constants() -> None:
    assert FAST_TIMEFRAMES == ("1m", "5m")
    assert SLOW_TIMEFRAMES == ("15m", "1h", "4h")


def test_paralysis_default_window_matches_legacy_default() -> None:
    assert PARALYSIS_DETECTOR_DEFAULT_MINUTES == 5.0


def test_main_returns_exit_code_2_when_validation_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    fresh_now_ms = 1_715_500_120_000
    snap = _build_snapshot(["BTCUSDT"], ["1m"], fresh_now_ms=fresh_now_ms)
    # Force validation failure by stripping ohlcv_list (must have >= MIN_CANDLES)
    snap["per_symbol"]["BTCUSDT"]["timeframes"]["1m"]["ohlcv_list"] = []
    snap_path = tmp_path / "bad.json"
    snap_path.write_text(json.dumps(snap))
    rc = main(["--once", "--input-file", str(snap_path)])
    assert rc == 2
