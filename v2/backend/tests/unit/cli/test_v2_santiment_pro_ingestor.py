from __future__ import annotations

import asyncio
import importlib


def _cli():
    return importlib.import_module("v2.backend.app.cli.v2_santiment_pro_ingestor")


def _status(symbol_count: int, successful: int, counts: dict[str, int]) -> dict:
    return {
        "status_payload": {
            "symbol_count": symbol_count,
            "successful_symbol_count": successful,
            "source_status_counts": counts,
        }
    }


def test_all_network_error_true_when_every_symbol_failed_at_network_layer() -> None:
    cli = _cli()
    assert cli._all_network_error([_status(8, 0, {"API_NETWORK_ERROR": 8})]) is True
    assert (
        cli._all_network_error(
            [
                _status(8, 0, {"API_NETWORK_ERROR": 8}),
                _status(140, 0, {"API_NETWORK_ERROR": 140}),
            ]
        )
        is True
    )


def test_all_network_error_false_on_success_rate_limit_or_empty() -> None:
    cli = _cli()
    # Any success means the network is fine: keep the normal cadence.
    assert cli._all_network_error([_status(8, 3, {"API_OK": 8})]) is False
    # Rate-limit/auth failures must NOT trigger the fast retry (budget).
    assert cli._all_network_error([_status(8, 0, {"API_RATE_LIMITED_429": 8})]) is False
    assert cli._all_network_error([_status(8, 0, {"API_GRAPHQL_ERROR": 8})]) is False
    # Mixed statuses are not a pure network outage.
    assert (
        cli._all_network_error(
            [_status(8, 0, {"API_NETWORK_ERROR": 4, "API_GRAPHQL_ERROR": 4})]
        )
        is False
    )
    assert cli._all_network_error([]) is False
    assert cli._all_network_error([_status(0, 0, {})]) is False


def test_base_asset_normalizes_pair_symbols() -> None:
    cli = _cli()
    assert cli._base_asset("BTCUSDT") == "BTC"
    assert cli._base_asset("ETHUSDC") == "ETH"
    assert cli._base_asset("1000PEPEUSDT") == "PEPE"
    assert cli._base_asset("SOL") == "SOL"


def test_split_symbols_by_tier_matches_runtime_pair_symbols() -> None:
    cli = _cli()
    tier_a, tier_b = cli.split_symbols_by_tier(
        ("BTCUSDT", "ETHUSDT", "SUNUSDT", "1000PEPEUSDT", "AAVEUSDT")
    )
    assert tier_a == ("BTCUSDT", "ETHUSDT", "AAVEUSDT")
    assert tier_b == ("SUNUSDT", "1000PEPEUSDT")


def test_run_loop_reconnects_redis_when_client_is_dead(monkeypatch) -> None:
    cli = _cli()

    class DeadClient:
        def ping(self):
            raise ConnectionError("gone")

    fresh_client = object()
    seen_clients: list[object] = []
    monkeypatch.setattr(cli, "_connect_redis", lambda: fresh_client)

    async def fake_run_once_async(**kwargs):
        seen_clients.append(kwargs["redis_client"])
        raise asyncio.CancelledError

    monkeypatch.setattr(cli, "run_once_async", fake_run_once_async)

    async def drive(client):
        try:
            await cli.run_loop_async(
                symbols=("BTCUSDT",),
                metrics=("social_volume_total",),
                redis_client=client,
                interval="1d",
                from_expr="utc_now-30d",
                to_expr="utc_now",
                execution_interval_seconds=1,
            )
        except asyncio.CancelledError:
            pass

    # A dead client at cycle start is replaced by a fresh connection.
    asyncio.run(drive(DeadClient()))
    # A None client (Redis down at process start) is also replaced.
    asyncio.run(drive(None))
    assert seen_clients == [fresh_client, fresh_client]
