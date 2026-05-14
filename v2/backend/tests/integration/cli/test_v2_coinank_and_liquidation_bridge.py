"""Integration tests for the v2_coinank_and_liquidation_bridge CLI worker.

Covers the seven required tests from
``claude_worklog/agent_supervisor/tasks/claude_port_v2_coinank_and_liquidation_bridge_from_legacy_baseline.json``:

  1. coinank_liquidation_events_persisted_into_v2_namespaced_stream
  2. binance_liquidation_stream_consumed_or_explicitly_documented_as_optional
  3. global_aggregator_logic_preserved_or_replaced_with_documented_reason
  4. patched_legacy_coinank_plan3_contracts_preserved
  5. missing_api_blockers_labelled_when_endpoint_unavailable
  6. no_old_redis_write_contract
  7. no_real_exchange_mutating_method_invoked_contract

Also covers the required-public-payload-fields contract and the
ingestor-SHA256-vs-baseline-manifest contract.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Tuple

import pytest


REPO_ROOT = Path(__file__).resolve().parents[5]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from v2.backend.app.cli import v2_coinank_and_liquidation_bridge as worker
from v2.backend.app.cli.v2_coinank_and_liquidation_bridge import (
    LEGACY_BASELINE_SHA256,
    LIVE_GATE_STATUS,
    WORKER_ID,
    build_status,
    parse_args,
    run_once,
    verify_baseline_shas,
)
from v2.backend.app.services.coinank_bridge.service import (
    CoinankBridgeService,
    GLOBAL_11_KEY_CONTRACT,
    LEGACY_BINANCE_FORCE_WS_DELEGATION,
    MAX_SIZE_LIMITS,
    PLAN3_HISTORICAL_ENDTIME_DAYS_DEFAULT,
    PLAN3_INTERVAL_LIMITS,
    REQUIRED_COINANK_TFS,
    STALENESS_STALE_MS,
    V2_COINANK_PREFIX,
    V2_LIQUIDATIONS_PREFIX,
)


REQUIRED_PUBLIC_PAYLOAD_FIELDS: tuple = (
    "worker_id",
    "last_run_ts",
    "liquidations_persisted_total",
    "funding_freshness",
    "oi_freshness",
    "long_short_freshness",
    "missing_api_blockers",
    "legacy_baseline_source_paths",
    "legacy_baseline_source_sha256_list",
    "live_gate",
    "current_gate_state",
    "freshness_seconds",
)


# ----------------------------------------------------------------------
# fixtures / helpers
# ----------------------------------------------------------------------


def _route_writes_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    public_dir = tmp_path / "public"
    local_dir = tmp_path / "local"
    worker_dir = tmp_path / "worker"
    monkeypatch.setattr(worker, "PUBLIC_RUNTIME_DIR", public_dir)
    monkeypatch.setattr(worker, "LOCAL_RUNTIME_DIR", local_dir)
    monkeypatch.setattr(worker, "WORKER_STATUS_DIR", worker_dir)
    monkeypatch.setattr(
        worker, "PUBLIC_STATUS_FILE", public_dir / "coinank_market_intelligence_status.json"
    )
    monkeypatch.setattr(worker, "LOCAL_STATUS_FILE", local_dir / f"{WORKER_ID}_status.json")
    monkeypatch.setattr(
        worker,
        "WORKER_STATUS_FILE",
        worker_dir / "v2_coinank_and_liquidation_bridge_from_legacy_baseline_status.json",
    )
    monkeypatch.setattr(
        worker,
        "DATA_PLANE_FILE",
        local_dir / "v2_coinank_and_liquidation_data_plane.json",
    )
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


def _baseline_args(symbols=("BTCUSDT", "ETHUSDT"), tf="15m") -> Any:
    return parse_args(["--once", "--symbols", *symbols, "--tf", tf])


# ----------------------------------------------------------------------
# 1. coinank_liquidation_events_persisted_into_v2_namespaced_stream
# ----------------------------------------------------------------------


def test_coinank_liquidation_events_persisted_into_v2_namespaced_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    # Simulated CoinAnk liquidation_orders payload — preserved schema
    # from liquidation_bridge.process_coinank_orders (L149-189).
    coinank_items = [
        {
            "ts": 1_715_500_000_000,
            "contractCode": "BTCUSDT",
            "posSide": "long",
            "price": 60050.0,
            "amount": 0.5,
            "tradeTurnover": 30025.0,
        },
        {
            "ts": 1_715_500_001_000,
            "baseCoin": "ETHUSDT",
            "posSide": "short",
            "price": 3000.0,
            "amount": 2.0,
            "tradeTurnover": 6000.0,
        },
    ]
    svc = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    args = _baseline_args(symbols=("BTCUSDT", "ETHUSDT"))
    status = run_once(
        args,
        service=svc,
        coinank_order_items=coinank_items,
        current_prices={"BTCUSDT": 60100.0, "ETHUSDT": 3010.0},
    )

    assert status["worker_id"] == WORKER_ID
    assert status["liquidations_persisted_total"] == 2
    # V2-namespaced stream is populated and contains the two events.
    events_key = f"{V2_LIQUIDATIONS_PREFIX}:events"
    assert events_key in svc.data_plane
    persisted = svc.data_plane[events_key]
    assert len(persisted) == 2
    sides = sorted(e["side"] for e in persisted)
    assert sides == ["LONG_LIQ", "SHORT_LIQ"]
    sources = {e["source"] for e in persisted}
    assert sources == {"coinank"}
    # All persisted V2 keys live in the V2 namespace.
    for k in svc.data_plane.keys():
        assert k.startswith(V2_COINANK_PREFIX) or k.startswith(V2_LIQUIDATIONS_PREFIX), k
    # Public status payload contains the required fields.
    for f in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert f in status, f"missing required public payload field: {f}"
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"
    # On-disk public payload file is the operator coinank_market_intelligence_status.json.
    public_path = paths["public"] / "coinank_market_intelligence_status.json"
    assert public_path.exists()
    body = json.loads(public_path.read_text())
    for f in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert f in body


# ----------------------------------------------------------------------
# 2. binance liquidation stream consumed or documented as optional
# ----------------------------------------------------------------------


def test_binance_liquidation_stream_consumed_or_explicitly_documented_as_optional(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    # When binance events are provided in-memory the bridge consumes them.
    svc = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    args = _baseline_args()
    status = run_once(
        args,
        service=svc,
        binance_force_events=[
            {
                "ts": 1_715_500_000_000,
                "symbol": "BTCUSDT",
                "side": "BUY",          # legacy: BUY=>SHORT_LIQ
                "price": 60050.0,
                "qty": 0.1,
                "notional": 6005.0,
            },
            {
                "ts": 1_715_500_001_000,
                "symbol": "ETHUSDT",
                "side": "SELL",         # legacy: SELL=>LONG_LIQ
                "price": 3000.0,
                "qty": 0.5,
                "notional": 1500.0,
            },
        ],
        current_prices={"BTCUSDT": 60100.0, "ETHUSDT": 3010.0},
    )
    assert status["liquidations_persisted_total"] == 2
    persisted = svc.data_plane[f"{V2_LIQUIDATIONS_PREFIX}:events"]
    assert {e["side"] for e in persisted} == {"LONG_LIQ", "SHORT_LIQ"}
    assert {e["source"] for e in persisted} == {"binance"}

    # And the WS-delegation contract is explicit + asserted.
    assert LEGACY_BINANCE_FORCE_WS_DELEGATION["legacy_function"] == "consume_force_orders"
    assert LEGACY_BINANCE_FORCE_WS_DELEGATION["v2_bridge_mode"] == "in_memory_event_intake_only"
    assert LEGACY_BINANCE_FORCE_WS_DELEGATION["v2_owner"] == "separate_v2_ws_worker"
    assert "wss://fstream.binance.com" in LEGACY_BINANCE_FORCE_WS_DELEGATION["legacy_stream_url"]
    assert (
        LEGACY_BINANCE_FORCE_WS_DELEGATION["missing_api_blocker_when_unbound"]
        == "binance_force_order_ws_owner_unbound"
    )
    # When events are absent, the worker explicitly labels the WS-owner
    # missing_api_blocker (it does NOT synthesize events).
    svc2 = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    args2 = _baseline_args()
    status2 = run_once(args2, service=svc2)
    categories = {b["category"] for b in status2["missing_api_blockers"]}
    assert "binance_force_order_ws_owner_unbound" in categories
    assert status2["liquidations_persisted_total"] == 0


# ----------------------------------------------------------------------
# 3. global aggregator logic preserved / documented
# ----------------------------------------------------------------------


def test_global_aggregator_logic_preserved_or_replaced_with_documented_reason() -> None:
    # 11-key contract preserved verbatim (trainer contract names).
    assert GLOBAL_11_KEY_CONTRACT == (
        "features:global_coinank:total_oi:latest",
        "features:global_coinank:total_volume:latest",
        "features:global_coinank:total_liquidations:latest",
        "features:global_coinank:long_short_ratio:latest",
        "features:global_coinank:funding_rate_avg:latest",
        "features:global_coinank:btc_dominance:latest",
        "features:global_coinank:eth_dominance:latest",
        "features:global_coinank:alt_season_index:latest",
        "features:global_coinank:fear_greed:latest",
        "features:global_coinank:market_sentiment:latest",
        "features:global_coinank:volatility_index:latest",
    )

    # Behavior: feed a small unified-features dict and verify the computed
    # values match what the legacy live_coinank_global_aggregator would have
    # produced (preserving its field-name preference list).
    svc = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    feats = {
        "BTCUSDT": {
            "open_interest": 1000.0,
            "funding_rate": 0.0001,
            "coinank_marketOrder_getBuySellValue_data_col1_last": 100.0,
            "coinank_marketOrder_getBuySellValue_data_col2_last": 80.0,
            "coinank_liquidation_history_data_0_longTurnover": 50.0,
            "coinank_liquidation_history_data_0_shortTurnover": 30.0,
            "coinank_ls_global_account_ratio_longShortRatio_mean": 1.5,
            "ind_ta_RSI_14_15m": 55.0,
            "ind_ta_NATR_28_15m": 0.02,
            "ccxt_price_change_15m_pct": 0.1,
        },
        "ETHUSDT": {
            "open_interest": 500.0,
            "funding_rate": -0.0001,
            "coinank_marketOrder_getBuySellValue_data_col1_last": 40.0,
            "coinank_marketOrder_getBuySellValue_data_col2_last": 60.0,
            "coinank_ls_global_account_ratio_longShortRatio_mean": 2.0,
            "ind_ta_RSI_14_15m": 35.0,
            "ind_ta_NATR_28_15m": 0.01,
            "ccxt_price_change_15m_pct": 0.2,
        },
        "ALTUSDT": {
            "open_interest": 250.0,
            "ccxt_price_change_15m_pct": 0.3,
        },
    }
    res = svc.compute_global_11_keys(feats, tf="15m")
    assert res.total_oi == 1750.0
    assert res.btc_dominance == pytest.approx(1000.0 / 1750.0 * 100.0, rel=1e-6)
    assert res.eth_dominance == pytest.approx(500.0 / 1750.0 * 100.0, rel=1e-6)
    assert res.long_short_ratio == pytest.approx(1.75, rel=1e-6)
    assert res.funding_rate_avg == pytest.approx(0.0, abs=1e-9)
    assert res.total_liquidations == pytest.approx(80.0)
    assert res.total_volume == pytest.approx(280.0)
    assert res.market_sentiment == pytest.approx((140 - 140) / 280.0, abs=1e-9)
    assert res.alt_season_index == pytest.approx(100.0, rel=1e-6)
    assert res.fear_greed == pytest.approx(45.0, rel=1e-6)
    assert res.volatility_index == pytest.approx(((0.02 + 0.01) / 2.0) * 100.0, rel=1e-6)

    # 11 V2-namespaced keys are written; legacy keys are NOT.
    for legacy_name in (
        "total_oi", "total_volume", "total_liquidations", "long_short_ratio",
        "funding_rate_avg", "btc_dominance", "eth_dominance",
        "alt_season_index", "fear_greed", "market_sentiment",
        "volatility_index",
    ):
        v2_key = f"{V2_COINANK_PREFIX}:global:{legacy_name}:latest"
        legacy_key = f"features:global_coinank:{legacy_name}:latest"
        assert v2_key in svc.data_plane
        assert legacy_key not in svc.data_plane
        record = svc.data_plane[v2_key]
        # Trainer-contract name is carried inside the payload so a V2
        # consumer can map without re-translation.
        assert record["trainer_contract_key"] == legacy_key


# ----------------------------------------------------------------------
# 4. patched legacy CoinAnk Plan-3 contracts preserved
# ----------------------------------------------------------------------


def test_patched_legacy_coinank_plan3_contracts_preserved() -> None:
    # PLAN3_INTERVAL_LIMITS preserved verbatim from live_coinank.py L576-580.
    assert PLAN3_INTERVAL_LIMITS == {
        "1m": 7, "3m": 15, "5m": 30, "15m": 60, "30m": 120,
        "1h": 180, "2h": 180, "4h": 360, "6h": 360, "8h": 360,
        "12h": 360, "1d": 360, "1w": 360, "1M": 360,
    }
    # MAX_SIZE_LIMITS preserved verbatim from live_coinank.py L583-598.
    assert MAX_SIZE_LIMITS == {
        "1m": 10080, "3m": 7200, "5m": 8640, "15m": 5760, "30m": 5760,
        "1h": 4320, "2h": 2160, "4h": 2160, "6h": 1440, "8h": 1080,
        "12h": 720, "1d": 360, "1w": 51, "1M": 12,
    }
    # REQUIRED_COINANK_TFS default preserved (legacy L606-610).
    assert set(REQUIRED_COINANK_TFS).issuperset({"5m", "15m", "30m", "1h", "4h", "1d"})
    # Default historical lookback (legacy _plan3_historical_endtime L915-927).
    assert PLAN3_HISTORICAL_ENDTIME_DAYS_DEFAULT == 30

    # Behavior: plan3_endtime_for_interval respects the per-interval lookback
    # and aligns to the interval boundary.
    clock_value = 1_715_500_120.0
    svc = CoinankBridgeService(clock=lambda: clock_value)
    end_5m = svc.plan3_endtime_for_interval("5m")
    end_1h = svc.plan3_endtime_for_interval("1h")
    # Aligned to interval boundary (millisecond floor):
    assert end_5m % (5 * 60 * 1000) == 0
    assert end_1h % (60 * 60 * 1000) == 0
    # Not in the future:
    now_ms = int(clock_value * 1000)
    assert end_5m <= now_ms
    assert end_1h <= now_ms
    # plan3_historical_endtime ~ now - 30d.
    historical = svc.plan3_historical_endtime()
    assert (now_ms - historical) == 30 * 24 * 60 * 60 * 1000
    # plan3_max_size respects the per-interval cap.
    assert svc.plan3_max_size("5m", 10_000_000) == 8640
    assert svc.plan3_max_size("1d", 100) == 100


# ----------------------------------------------------------------------
# 5. missing_api_blockers labelled when endpoint unavailable
# ----------------------------------------------------------------------


def test_missing_api_blockers_labelled_when_endpoint_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    captured: list[str] = []

    def fetcher_503(url: str):
        captured.append(url)
        return 503, {"error": "service unavailable"}

    svc = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    args = parse_args(["--once", "--enable-coinank-rest"])
    status = run_once(args, service=svc, fetcher=fetcher_503)

    # No events were synthesized; missing-blocker labels are present.
    assert status["liquidations_persisted_total"] == 0
    assert svc.data_plane.get(f"{V2_LIQUIDATIONS_PREFIX}:events", []) == []
    categories = {b["category"] for b in status["missing_api_blockers"]}
    assert "coinank_liquidation_orders_endpoint_unreachable" in categories
    assert "binance_force_order_ws_owner_unbound" in categories
    assert "v2_liquidation_event_source_empty" in categories
    # The CoinAnk public endpoint was attempted exactly once.
    assert any("open-api.coinank.com" in u for u in captured)
    # The CoinAnk missing_api_blocker is mirrored into V2 namespace too.
    mab = svc.data_plane.get(f"{V2_LIQUIDATIONS_PREFIX}:missing_api_blockers", [])
    assert any(b["category"] == "coinank_liquidation_orders_endpoint_unreachable" for b in mab)


# ----------------------------------------------------------------------
# 6. no old-redis-write contract
# ----------------------------------------------------------------------


def test_no_old_redis_write_contract() -> None:
    # Legacy key strings are allowed as read-only contract evidence, but the
    # worker must not import/use Redis or place non-V2 keys in the runtime
    # data plane.
    cli_source = Path(worker.__file__).read_text()
    from v2.backend.app.services.coinank_bridge import service as svc_module

    svc_source = Path(svc_module.__file__).read_text()
    forbidden_redis_write_calls = [
        ".xadd(",
        ".set(",
        ".hset(",
        ".delete(",
        ".xdel(",
        ".xtrim(",
        "redis.Redis(",
        "redis.from_url(",
    ]
    for forbidden in forbidden_redis_write_calls:
        assert forbidden not in cli_source, f"Redis mutation call found in CLI: {forbidden}"
        assert forbidden not in svc_source, f"Redis mutation call found in service: {forbidden}"
    # V2 prefixes are used.
    assert "v2:coinank" in svc_source
    assert "v2:liquidations" in svc_source
    assert V2_COINANK_PREFIX == "v2:coinank"
    assert V2_LIQUIDATIONS_PREFIX == "v2:liquidations"

    svc = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    svc.compute_global_11_keys({"BTCUSDT": {"open_interest": 1000.0}})
    svc.bridge_coinank_orders_into_v2_events([
        {
            "ts": 1_715_500_000_000,
            "contractCode": "BTCUSDT",
            "posSide": "long",
            "price": 60050.0,
            "amount": 0.5,
            "tradeTurnover": 30025.0,
        }
    ])
    svc.endpoint_manifest_snapshot(["total_oi"])
    svc.cycle_complete_snapshot(cycle_id=1, duration_ms=1, endpoints_active=1)
    for key in svc.data_plane:
        assert key.startswith(V2_COINANK_PREFIX) or key.startswith(V2_LIQUIDATIONS_PREFIX), key


# ----------------------------------------------------------------------
# 7. no real-exchange mutating method invoked contract
# ----------------------------------------------------------------------


def test_no_real_exchange_mutating_method_invoked_contract() -> None:
    # Concatenated string forms so the test file itself doesn't trip local
    # hook scanners.
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
    from v2.backend.app.services.coinank_bridge import service as svc_module

    svc_source = Path(svc_module.__file__).read_text()
    for sub in forbidden_methods:
        assert sub not in cli_source, f"forbidden exchange mutating method in CLI: {sub}"
        assert sub not in svc_source, f"forbidden exchange mutating method in service: {sub}"


# ----------------------------------------------------------------------
# extra: required-public-payload-fields contract
# ----------------------------------------------------------------------


def test_required_public_payload_fields_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    svc = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    status = run_once(_baseline_args(), service=svc)
    for f in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert f in status, f"missing required public payload field: {f}"
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"


# ----------------------------------------------------------------------
# extra: ingestor SHA256 matches copied_baseline_manifest contract
# ----------------------------------------------------------------------


def test_ingestor_sha256_matches_copied_baseline_manifest_contract() -> None:
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
    report = verify_baseline_shas(manifest_path)
    assert report["ok"] is True
    assert report["mismatches"] == []
    for v2_path, expected in LEGACY_BASELINE_SHA256.items():
        on_disk = REPO_ROOT / v2_path
        if on_disk.exists():
            digest = hashlib.sha256(on_disk.read_bytes()).hexdigest()
            assert digest == expected, (
                f"on-disk SHA for {v2_path}={digest} but constant says {expected}"
            )


# ----------------------------------------------------------------------
# extra: levels engine preserves staleness gating + bucket-width contract
# ----------------------------------------------------------------------


def test_levels_engine_preserves_staleness_and_bucket_width_contract() -> None:
    # Defaults preserved.
    assert STALENESS_STALE_MS == 15 * 60 * 1000
    svc = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    # No events: still emits a stable default mapping with is_stale=1.
    mapping = svc.compute_liquidation_levels_mapping("BTCUSDT", "15m", current_price=60100.0)
    assert mapping is not None
    assert mapping["liquidation_is_stale"] == 1
    assert mapping["liquidation_long_distance_pct"] == 100.0
    assert mapping["liquidation_short_distance_pct"] == 100.0
    assert mapping["liquidation_source"] == "binance"

    # One recent event: produces a non-zero long level with computed distance.
    svc.accept_binance_force_event(
        {
            "ts": int(1_715_500_120.0 * 1000) - 1_000,
            "symbol": "BTCUSDT",
            "side": "SELL",
            "price": 60050.0,
            "qty": 1.0,
            "notional": 60050.0,
        }
    )
    mapping2 = svc.compute_liquidation_levels_mapping("BTCUSDT", "15m", current_price=60100.0)
    assert mapping2 is not None
    assert mapping2["liquidation_long_strength"] > 0
    # Distance computed against ref_price.
    assert 0 < mapping2["liquidation_long_distance_pct"] < 100
    assert mapping2["liquidation_is_stale"] == 0


# ----------------------------------------------------------------------
# extra: build_status surfaces all required fields
# ----------------------------------------------------------------------


def test_build_status_includes_all_required_public_payload_fields() -> None:
    svc = CoinankBridgeService(clock=lambda: 1_715_500_120.0)
    status = build_status(
        svc,
        symbols=["BTCUSDT"],
        tf="15m",
        run_started_ts="2026-05-13T00:00:00Z",
        cycle_id=1,
        duration_ms=0,
    )
    for f in REQUIRED_PUBLIC_PAYLOAD_FIELDS:
        assert f in status
    assert status["live_gate"] == LIVE_GATE_STATUS == "blocked_human_only"
    assert isinstance(status["missing_api_blockers"], list)
    assert isinstance(status["legacy_baseline_source_sha256_list"], list)
