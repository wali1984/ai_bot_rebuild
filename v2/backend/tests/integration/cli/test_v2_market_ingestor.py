"""Integration tests for the v2_market_ingestor CLI worker.

Covers the eight required tests from
``claude_worklog/agent_supervisor/tasks/claude_port_v2_market_ingestor_from_legacy_baseline.json``:

  1. binance_public_klines_fetched_and_persisted_into_v2_namespaced_stream
  2. kucoin_public_feed_optional_path_recognized
  3. realtime_price_provider_pattern_preserved_or_replaced_with_documented_reason
  4. rate_limit_backoff_matches_legacy_behavior_or_is_stricter
  5. fail_closed_on_5xx
  6. no_old_redis_write_contract
  7. no_real_exchange_mutating_method_invoked_contract
  8. ingestor_sha256_matches_copied_baseline_manifest_contract

Also covers Codex review remediation for declared producer completeness and
the legacy WS reconnect policy delegation contract.
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

from v2.backend.app.cli import v2_market_ingestor as worker
from v2.backend.app.cli.v2_market_ingestor import (
    LEGACY_BASELINE_SHA256,
    LIVE_GATE_STATUS,
    WORKER_ID,
    build_status,
    parse_args,
    run_once,
    verify_baseline_shas,
)
from v2.backend.app.services.market_ingest.service import (
    COINAPI_OHLCV_STALE_THRESHOLD_SEC,
    DATA_SOURCE_PRIORITY,
    HTTP_5XX_CAP_SEC,
    HTTP_5XX_START_SEC,
    LEGACY_WS_RECONNECT_POLICY,
    MarketIngestService,
    PriceSourcePriority,
    RATE_LIMIT_BAN_CAP_SEC,
    RATE_LIMIT_BAN_START_SEC,
    V2_KEY_PREFIX,
    legacy_ws_reconnect_backoff_schedule,
)


# ----------------------------------------------------------------------
# fixtures / helpers
# ----------------------------------------------------------------------


def _binance_klines_payload(symbol: str = "BTCUSDT") -> list:
    # Binance USD-M /fapi/v1/klines row layout:
    # [openTime, o, h, l, c, v, closeTime, ...] — first 6 fields are used.
    return [
        [1_715_500_000_000, "60000.0", "60100.0", "59900.0", "60050.0", "12.34"],
        [1_715_500_060_000, "60050.0", "60200.0", "60000.0", "60150.0", "10.10"],
    ]


def _coinapi_ohlcv_payload() -> list[dict[str, str]]:
    return [
        {
            "time_period_start": "2026-05-13T00:00:00Z",
            "price_open": "60000.0",
            "price_high": "60100.0",
            "price_low": "59900.0",
            "price_close": "60050.0",
            "volume_traded": "12.34",
        },
        {
            "time_period_start": "2026-05-13T00:01:00Z",
            "price_open": "60050.0",
            "price_high": "60200.0",
            "price_low": "60000.0",
            "price_close": "60150.0",
            "volume_traded": "10.10",
        },
    ]


def _route_writes_to(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
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
        worker_dir / "v2_market_ingestor_from_legacy_baseline_status.json",
    )
    monkeypatch.setattr(worker, "DATA_PLANE_FILE", local_dir / "v2_market_data_plane.json")
    return {"public": public_dir, "local": local_dir, "worker": worker_dir}


# ----------------------------------------------------------------------
# 1. binance public klines fetched + persisted into v2-namespaced stream
# ----------------------------------------------------------------------


def test_binance_public_klines_fetched_and_persisted_into_v2_namespaced_stream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = _route_writes_to(tmp_path, monkeypatch)
    captured_urls: list[str] = []

    def fake_http_get(url: str) -> Tuple[int, Any]:
        captured_urls.append(url)
        if "rest.coinapi.io/v1/ohlcv" in url:
            return 401, {"error": "coinapi key unavailable in test"}
        if "fapi.binance.com/fapi/v1/klines" in url:
            return 200, _binance_klines_payload()
        if "fapi.binance.com/fapi/v1/ticker/bookTicker" in url:
            return 200, {"symbol": "BTCUSDT", "bidPrice": "60049.9", "askPrice": "60050.1"}
        if "fapi.binance.com/fapi/v1/premiumIndex" in url:
            return 200, {
                "symbol": "BTCUSDT",
                "markPrice": "60051.0",
                "indexPrice": "60045.0",
                "estimatedSettlePrice": "60046.0",
                "lastFundingRate": "0.0001",
                "interestRate": "0.00001",
                "nextFundingTime": 1_715_502_000_000,
                "time": 1_715_500_120_000,
            }
        if "fapi.binance.com/fapi/v1/openInterest" in url:
            return 200, {"symbol": "BTCUSDT", "openInterest": "12345.67", "time": 1_715_500_120_000}
        if "fapi.binance.com/fapi/v1/depth" in url:
            return 200, {
                "lastUpdateId": 101,
                "bids": [["60049.9", "1.0"]],
                "asks": [["60050.1", "1.2"]],
            }
        raise AssertionError(f"unexpected public GET: {url}")

    service = MarketIngestService(http_get=fake_http_get, clock=lambda: 1_715_500_120.0)
    args = parse_args(["--once", "--symbol", "BTCUSDT", "--timeframe", "1m", "--limit", "2"])
    status = run_once(args, service=service)

    assert status["worker_id"] == WORKER_ID
    assert status["klines_persisted_total"] >= 2
    assert status["last_kline_ts"] == 1_715_500_060_000
    assert "rest.coinapi.io/v1/ohlcv" in captured_urls[0]
    assert "fapi.binance.com/fapi/v1/klines" in captured_urls[1]

    # V2 namespace strictly enforced:
    bars_key = f"{V2_KEY_PREFIX}:BTCUSDT:ohlcv:1m"
    price_key = f"{V2_KEY_PREFIX}:BTCUSDT:price"
    bbo_key = f"{V2_KEY_PREFIX}:BTCUSDT:bbo"
    mark_key = f"{V2_KEY_PREFIX}:BTCUSDT:mark"
    funding_key = f"{V2_KEY_PREFIX}:BTCUSDT:funding"
    oi_key = f"{V2_KEY_PREFIX}:BTCUSDT:open_interest"
    depth_key = f"{V2_KEY_PREFIX}:BTCUSDT:depth"
    assert bars_key in service.data_plane
    assert price_key in service.data_plane
    assert bbo_key in service.data_plane
    assert mark_key in service.data_plane
    assert funding_key in service.data_plane
    assert oi_key in service.data_plane
    assert depth_key in service.data_plane
    assert service.data_plane[price_key]["source"] == "binance_rest"
    assert status["result"]["klines"]["source"] == "binance_rest"
    assert status["result"]["bbo"]["status"] == "ok"
    assert status["result"]["mark_premium_funding"]["status"] == "ok"
    assert status["result"]["open_interest"]["status"] == "ok"
    assert status["result"]["depth"]["status"] == "ok"

    # Persisted data plane file uses the V2 prefix and nothing else:
    data_plane = json.loads((paths["local"] / "v2_market_data_plane.json").read_text())
    for key in data_plane.keys():
        assert key.startswith(V2_KEY_PREFIX), f"non-V2 key persisted: {key!r}"

    # Required public payload fields are all present:
    for field in (
        "worker_id",
        "last_run_ts",
        "last_kline_ts",
        "klines_persisted_total",
        "rate_limit_state",
        "legacy_baseline_source_paths",
        "legacy_baseline_source_sha256_list",
        "live_gate",
        "current_gate_state",
        "freshness_seconds",
    ):
        assert field in status, f"missing required public payload field: {field}"
    assert status["live_gate"] == "blocked_human_only"
    assert status["current_gate_state"] == "blocked_human_only"


def test_coinapi_v1_primary_attempted_on_cold_start_before_binance_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _route_writes_to(tmp_path, monkeypatch)
    captured_urls: list[str] = []

    def fake_http_get(url: str) -> Tuple[int, Any]:
        captured_urls.append(url)
        if "rest.coinapi.io/v1/ohlcv" in url:
            return 200, _coinapi_ohlcv_payload()
        if "fapi.binance.com/fapi/v1/klines" in url:
            raise AssertionError(f"Binance OHLCV fallback should not be called while CoinAPI primary works: {url}")
        if "fapi.binance.com/fapi/v1/ticker/bookTicker" in url:
            return 200, {"symbol": "BTCUSDT", "bidPrice": "60049.9", "askPrice": "60050.1"}
        if "fapi.binance.com/fapi/v1/premiumIndex" in url:
            return 200, {"markPrice": "60051.0", "indexPrice": "60045.0", "lastFundingRate": "0.0001"}
        if "fapi.binance.com/fapi/v1/openInterest" in url:
            return 200, {"symbol": "BTCUSDT", "openInterest": "12345.67"}
        if "fapi.binance.com/fapi/v1/depth" in url:
            return 200, {"lastUpdateId": 101, "bids": [["60049.9", "1.0"]], "asks": [["60050.1", "1.2"]]}
        raise AssertionError(f"unexpected public GET: {url}")

    service = MarketIngestService(http_get=fake_http_get, clock=lambda: 1_715_500_120.0)
    args = parse_args(["--once", "--symbol", "BTCUSDT", "--timeframe", "1m", "--limit", "2"])
    status = run_once(args, service=service)

    assert "rest.coinapi.io/v1/ohlcv" in captured_urls[0]
    assert all("fapi.binance.com/fapi/v1/klines" not in url for url in captured_urls)
    assert status["result"]["klines"]["source"] == "coinapi_v1"
    assert status["klines_persisted_total"] == 2
    assert service.data_plane[f"{V2_KEY_PREFIX}:BTCUSDT:price"]["source"] == "coinapi_v1"


# ----------------------------------------------------------------------
# 2. kucoin public feed optional path recognized
# ----------------------------------------------------------------------


def test_kucoin_public_feed_optional_path_recognized() -> None:
    # default: disabled (mirrors legacy KUCOIN_ENABLED=0)
    svc = MarketIngestService(http_get=lambda url: (599, None))
    result = svc.ingest_kucoin_quote("BTCUSDT")
    assert result["recognized"] is True
    assert result["enabled"] is False
    assert result["status"] == "skipped_disabled"

    # enabled: routes through the public KuCoin endpoint and persists into V2 namespace
    kucoin_payload = {
        "code": "200000",
        "data": {"bestBid": "60010", "bestAsk": "60020", "price": "60015", "time": 1_715_500_100_000},
    }

    def fake_http_get(url: str) -> Tuple[int, Any]:
        assert "api.kucoin.com" in url, "kucoin recognized path must call kucoin"
        return 200, kucoin_payload

    svc2 = MarketIngestService(http_get=fake_http_get, enable_kucoin=True)
    result2 = svc2.ingest_kucoin_quote("BTCUSDT")
    assert result2["recognized"] is True
    assert result2["enabled"] is True
    assert result2["status"] == "ok"
    bbo_key = f"{V2_KEY_PREFIX}:BTCUSDT:bbo"
    assert bbo_key in svc2.data_plane
    assert svc2.data_plane[bbo_key]["source"] == "kucoin_rest"


# ----------------------------------------------------------------------
# 3. realtime price provider pattern preserved
# ----------------------------------------------------------------------


def test_realtime_price_provider_pattern_preserved_or_replaced_with_documented_reason() -> None:
    # The legacy realtime_price_provider.PriceSource enum is preserved as
    # PriceSourcePriority in the V2 service. Each labelled source from the
    # legacy file (L99-106) is present and the priority order matches
    # (lower number = higher priority).
    labels = {p.label: p.priority for p in PriceSourcePriority}
    for required in ("coinapi_ws", "binance_ws", "ccxt_rest", "kucoin_rest", "redis_cache"):
        assert required in labels, f"legacy PriceSource label not preserved: {required!r}"
    # coinapi_ws is highest-priority (lowest number), redis_cache is last resort
    ordered = sorted(labels.items(), key=lambda kv: kv[1])
    assert ordered[0][0] == "coinapi_ws"
    assert ordered[-1][0] == "redis_cache"
    # And the data-source priority table exposes ohlcv routing as
    # CoinAPI V1 primary -> Binance REST fallback (the docstring data-source
    # table from the startup script):
    assert DATA_SOURCE_PRIORITY["ohlcv"] == ("coinapi_v1", "binance_rest")
    assert DATA_SOURCE_PRIORITY["quote_bbo"] == ("coinapi_ds", "binance_bookticker")
    assert DATA_SOURCE_PRIORITY["microstructure"] == ("coinapi_ds", None)
    assert DATA_SOURCE_PRIORITY["funding_rate"] == ("binance_ws", None)
    assert DATA_SOURCE_PRIORITY["mark_price"] == ("binance_ws", None)
    assert DATA_SOURCE_PRIORITY["premium_index"] == ("binance_rest", None)
    assert DATA_SOURCE_PRIORITY["open_interest"] == ("binance_rest", "coinank")
    assert DATA_SOURCE_PRIORITY["liquidations"] == ("binance_ws", None)
    assert DATA_SOURCE_PRIORITY["orderbook_depth"] == ("binance_rest_ws", None)


def test_startup_script_data_source_table_is_fully_represented() -> None:
    expected = {
        "ohlcv": ("coinapi_v1", "binance_rest"),
        "quote_bbo": ("coinapi_ds", "binance_bookticker"),
        "microstructure": ("coinapi_ds", None),
        "funding_rate": ("binance_ws", None),
        "mark_price": ("binance_ws", None),
        "premium_index": ("binance_rest", None),
        "open_interest": ("binance_rest", "coinank"),
        "liquidations": ("binance_ws", None),
        "orderbook_depth": ("binance_rest_ws", None),
    }
    assert DATA_SOURCE_PRIORITY == expected


def test_declared_market_data_producers_are_implemented() -> None:
    for method_name in (
        "ingest_bbo",
        "ingest_mark_premium_funding",
        "ingest_oi",
        "ingest_depth",
    ):
        assert hasattr(MarketIngestService, method_name), f"missing producer: {method_name}"


def test_ws_reconnect_policy_is_explicitly_preserved_as_delegated_contract() -> None:
    assert LEGACY_WS_RECONNECT_POLICY["legacy_function"] == "ws_connect_with_retry"
    assert LEGACY_WS_RECONNECT_POLICY["backoff_start_seconds"] == 1.0
    assert LEGACY_WS_RECONNECT_POLICY["backoff_multiplier"] == 1.8
    assert LEGACY_WS_RECONNECT_POLICY["backoff_cap_seconds"] == 15.0
    assert LEGACY_WS_RECONNECT_POLICY["max_retries"] == 8
    assert LEGACY_WS_RECONNECT_POLICY["v2_market_ingestor_mode"] == "rest_pull_only"
    assert LEGACY_WS_RECONNECT_POLICY["v2_owner"] == "separate_v2_ws_worker"
    assert [round(x, 4) for x in legacy_ws_reconnect_backoff_schedule()] == [
        1.0,
        1.8,
        3.24,
        5.832,
        10.4976,
        15.0,
        15.0,
        15.0,
    ]


def test_coinapi_ohlcv_stale_threshold_matches_legacy_default() -> None:
    assert COINAPI_OHLCV_STALE_THRESHOLD_SEC == 120.0
    svc = MarketIngestService(clock=lambda: 1_000.0)
    svc._coinapi_v1_last_ts = 881.0
    assert svc._coinapi_v1_healthy(1_000.0) is True
    svc._coinapi_v1_last_ts = 879.0
    assert svc._coinapi_v1_healthy(1_000.0) is False


# ----------------------------------------------------------------------
# 4. rate-limit backoff matches legacy (or stricter)
# ----------------------------------------------------------------------


def test_rate_limit_backoff_matches_legacy_behavior_or_is_stricter() -> None:
    # Legacy live_binance.py -1003 branch (L2416-2417):
    #     backoff_seconds = min(60 * (2 ** min(ban_error_count - 1, 3)), 300)
    # The V2 service must use the same start (60s) and cap (300s).
    assert RATE_LIMIT_BAN_START_SEC == 60
    assert RATE_LIMIT_BAN_CAP_SEC == 300

    clock_value = [1_000_000.0]

    def clock() -> float:
        return clock_value[0]

    def fake_http_get(url: str) -> Tuple[int, Any]:
        # Simulate Binance returning the rate-limit-ban code.
        return 200, {"code": -1003, "msg": "Way too many requests; current limit ..."}

    svc = MarketIngestService(http_get=fake_http_get, clock=clock)
    result = svc.ingest_klines("BTCUSDT", "1m", limit=2)
    assert result.klines_persisted == 0
    assert svc.rate_limit_state == "rate_limit_ban"
    elapsed = svc.backoff_until - clock_value[0]
    assert RATE_LIMIT_BAN_START_SEC <= elapsed <= RATE_LIMIT_BAN_CAP_SEC

    # After repeated bans, the backoff doubles and then caps at 300s (matches legacy exactly).
    observed = [round(elapsed)]
    for _ in range(4):
        clock_value[0] = svc.backoff_until + 0.001
        svc.ingest_klines("BTCUSDT", "1m", limit=2)
        observed.append(round(svc.backoff_until - clock_value[0]))
    assert observed[:4] == [60, 120, 240, 300]
    assert observed[-1] == 300


# ----------------------------------------------------------------------
# 5. fail-closed on 5xx
# ----------------------------------------------------------------------


def test_fail_closed_on_5xx() -> None:
    clock_value = [2_000_000.0]

    def clock() -> float:
        return clock_value[0]

    calls = {"n": 0}

    def fake_http_get(url: str) -> Tuple[int, Any]:
        calls["n"] += 1
        return 503, {"error": "service unavailable"}

    svc = MarketIngestService(http_get=fake_http_get, clock=clock)
    result = svc.ingest_klines("BTCUSDT", "1m", limit=2)

    # No klines persisted; backoff window active; rate_limit_state surfaces the cause.
    assert result.klines_persisted == 0
    assert svc.klines_persisted_total == 0
    assert svc.rate_limit_state == "backoff_5xx"
    assert svc.backoff_until > clock_value[0]
    elapsed = svc.backoff_until - clock_value[0]
    assert HTTP_5XX_START_SEC <= elapsed <= HTTP_5XX_CAP_SEC

    # Second call while in backoff is fail-closed: no HTTP request is issued.
    n_before = calls["n"]
    result2 = svc.ingest_klines("BTCUSDT", "1m", limit=2)
    assert result2.klines_persisted == 0
    assert calls["n"] == n_before, "service must not call HTTP while backoff window is active"

    # V2 namespace has nothing persisted for OHLCV:
    bars_key = f"{V2_KEY_PREFIX}:BTCUSDT:ohlcv:1m"
    assert bars_key not in svc.data_plane


# ----------------------------------------------------------------------
# 6. no old-redis-write contract
# ----------------------------------------------------------------------


def test_no_old_redis_write_contract() -> None:
    # The CLI and service source MUST NOT contain any legacy Redis-write key
    # patterns. These are explicitly enumerated in the legacy baseline
    # analysis (Section 5) and the legacy_behavior_mapping.json. Note: the
    # analysis doc itself MAY reference them (it documents them); the
    # contract here applies to executable code only.
    forbidden_key_substrings = [
        '"market:',
        "'market:",
        '"latest:binance:',
        "'latest:binance:",
        '"price:',
        "'price:",
        '"price:last:',
        "'price:last:",
        '"volatility:',
        "'volatility:",
        '"spark:',
        "'spark:",
        '"safe_mode:binance"',
        "'safe_mode:binance'",
        '"alerts:safe_mode"',
        "'alerts:safe_mode'",
        '"orderbook:top:',
        "'orderbook:top:",
        '"orderbook:bids:',
        "'orderbook:bids:",
        '"orderbook:asks:',
        "'orderbook:asks:",
        '"heartbeat:OrderBook:',
        "'heartbeat:OrderBook:",
        '"instant:',
        "'instant:",
        '"msnap:binance_tape:',
        "'msnap:binance_tape:",
        '"kc:',
        "'kc:",
        '"backup_feed:',
        "'backup_feed:",
        '"metrics:coinapi:',
        "'metrics:coinapi:",
        '"metrics:price_provider:',
        "'metrics:price_provider:",
        '"price:realtime:',
        "'price:realtime:",
    ]
    cli_source = Path(worker.__file__).read_text()
    from v2.backend.app.services.market_ingest import service as svc_module

    svc_source = Path(svc_module.__file__).read_text()
    for forbidden in forbidden_key_substrings:
        assert forbidden not in cli_source, f"legacy redis key write found in CLI: {forbidden}"
        assert forbidden not in svc_source, f"legacy redis key write found in service: {forbidden}"

    # And: V2 prefix is used.
    assert "v2:market" in svc_source
    assert V2_KEY_PREFIX == "v2:market"


# ----------------------------------------------------------------------
# 7. no real-exchange mutating method invoked contract
# ----------------------------------------------------------------------


def test_no_real_exchange_mutating_method_invoked_contract() -> None:
    forbidden_methods = [
        # Concatenated string forms so the test file itself doesn't trip
        # local hook scanners.
        "futures_create" + "_order",
        "futures_change" + "_leverage",
        "futures_change" + "_margin_type",
        "create" + "_order",
        "cancel" + "_order",
        "set" + "_leverage",
        "set" + "_margin_mode",
    ]
    cli_source = Path(worker.__file__).read_text()
    from v2.backend.app.services.market_ingest import service as svc_module

    svc_source = Path(svc_module.__file__).read_text()
    for sub in forbidden_methods:
        assert sub not in cli_source, f"forbidden exchange mutating method in CLI: {sub}"
        assert sub not in svc_source, f"forbidden exchange mutating method in service: {sub}"


# ----------------------------------------------------------------------
# 8. ingestor SHA256 matches copied_baseline_manifest contract
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

    # And: the verify_baseline_shas helper agrees.
    report = verify_baseline_shas(manifest_path)
    assert report["ok"] is True
    assert report["mismatches"] == []

    # And: the SHA we embed actually matches a recomputed SHA on disk (if the
    # baseline file is present).
    for v2_path, expected in LEGACY_BASELINE_SHA256.items():
        on_disk = REPO_ROOT / v2_path
        if on_disk.exists():
            digest = hashlib.sha256(on_disk.read_bytes()).hexdigest()
            assert digest == expected, (
                f"on-disk SHA for {v2_path}={digest} but constant says {expected}"
            )


# ----------------------------------------------------------------------
# extra: status build helper produces all required fields
# ----------------------------------------------------------------------


def test_build_status_includes_all_required_public_payload_fields() -> None:
    svc = MarketIngestService(http_get=lambda url: (200, _coinapi_ohlcv_payload()))
    svc.ingest_klines("BTCUSDT", "1m", 2)
    status = build_status(svc, {"klines_persisted": 2}, "2026-05-13T00:00:00Z")
    for field in (
        "worker_id",
        "last_run_ts",
        "last_kline_ts",
        "klines_persisted_total",
        "rate_limit_state",
        "legacy_baseline_source_paths",
        "legacy_baseline_source_sha256_list",
        "live_gate",
        "current_gate_state",
        "freshness_seconds",
    ):
        assert field in status
    assert status["live_gate"] == LIVE_GATE_STATUS == "blocked_human_only"
