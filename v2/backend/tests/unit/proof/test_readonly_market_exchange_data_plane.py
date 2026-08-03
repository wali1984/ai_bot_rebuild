from __future__ import annotations

from pathlib import Path

import pytest

from v2.backend.app.proof.readonly_market_exchange_data_plane import (
    BinanceReadonlyConnector,
    ExchangeMutationForbidden,
    GO_NO_GO_MARKER,
    ReadonlyExchangeConnector,
    build_operator_payload,
    classify_freshness,
    write_readonly_market_exchange_data_plane,
)


def test_forbidden_exchange_mutations_fail_closed() -> None:
    connector = ReadonlyExchangeConnector()
    for method_name in [
        "create_order",
        "cancel_order",
        "change_leverage",
        "change_margin",
        "change_position_mode",
    ]:
        with pytest.raises(ExchangeMutationForbidden):
            getattr(connector, method_name)()


def test_freshness_classification_uses_source_type_and_age() -> None:
    assert classify_freshness(
        generated_at="now",
        last_event_at="now",
        age_seconds=10,
        source="feed",
        source_type="READONLY_MARKET_FEED",
        source_pointer="ptr",
    ).freshness_state == "fresh"
    assert classify_freshness(
        generated_at="now",
        last_event_at="old",
        age_seconds=1000,
        source="feed",
        source_type="READONLY_MARKET_FEED",
        source_pointer="ptr",
    ).freshness_state == "warn"
    assert classify_freshness(
        generated_at="now",
        last_event_at="missing",
        age_seconds=0,
        source="feed",
        source_type="MISSING",
        source_pointer="ptr",
    ).freshness_state == "missing"


def test_fixture_payload_labels_static_sources_and_blocks_orders() -> None:
    payload = build_operator_payload(fetch_binance=False)
    assert payload["feed_health"]["source_type"] == "STATIC_PROOF_FIXTURE"
    assert payload["feed_health"]["order_capability"] == "BLOCKED"
    assert payload["market_candles"][0]["freshness"]["source_type"] == "STATIC_PROOF_FIXTURE"
    assert payload["paper_runtime_market_feed"]["places_orders"] is False
    assert payload["paper_runtime_market_feed"]["writes_legacy_redis"] is False


def test_binance_public_fetcher_uses_get_only_injected_http_client() -> None:
    called: list[str] = []

    def fake_http_get(url: str):
        called.append(url)
        if "klines" in url:
            return [[1_700_000_000_000, "1", "2", "0.5", "1.5", "100"]]
        if "ticker" in url:
            return {"symbol": "BTCUSDT", "lastPrice": "1.5", "priceChangePercent": "2.0"}
        if "fundingRate" in url:
            return [{"symbol": "BTCUSDT", "fundingRate": "0.0001"}]
        return {"symbol": "BTCUSDT", "openInterest": "1000"}

    connector = BinanceReadonlyConnector(http_get=fake_http_get)
    assert connector.fetch_market_candles(symbol="BTCUSDT", limit=1)[0].freshness.source_type == "READONLY_MARKET_FEED"
    assert connector.fetch_market_ticker()["price"] == "1.5"
    assert connector.fetch_funding_rate()["funding_rate"] == "0.0001"
    assert connector.fetch_open_interest()["open_interest"] == "1000"
    assert all("/fapi/v1/" in url for url in called)
    assert all("order" not in url.lower() for url in called)


def test_default_binance_http_fetcher_requires_rest_fallback_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINANCE_REST_FALLBACK_ALLOWED", raising=False)
    connector = BinanceReadonlyConnector()

    with pytest.raises(
        RuntimeError,
        match="BINANCE_REST_FALLBACK_DISABLED_WEBSOCKET_PRIMARY",
    ):
        connector.fetch_market_ticker(symbol="BTCUSDT")


def test_writer_emits_required_artifacts_and_public_copy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    workspace = Path.cwd()
    output = workspace / "claude_worklog/final_readiness/readonly_market_exchange_data_plane/latest"
    public = workspace / "v2/frontend/public/readonly_market_exchange_data_plane/latest"
    write_readonly_market_exchange_data_plane(output, public_output_dir=public, fetch_binance=False)

    required = [
        "PHASE2Z_READONLY_MARKET_EXCHANGE_DATA_PLANE_REPORT.md",
        "GO_NO_GO.md",
        "MARKET_DATA_CONTRACTS.md",
        "EXCHANGE_CONNECTOR_READONLY_POLICY.md",
        "FEED_FRESHNESS_REPORT.md",
        "CHART_DATA_WIRING_REPORT.md",
        "ACCOUNT_READONLY_WIRING_REPORT.md",
        "PAPER_RUNTIME_MARKET_FEED_REPORT.md",
        "operator_dashboard_payload.json",
    ]
    for rel in required:
        assert (output / rel).exists()
        assert (public / rel).exists()
    assert (output / "GO_NO_GO.md").read_text().strip() == GO_NO_GO_MARKER
