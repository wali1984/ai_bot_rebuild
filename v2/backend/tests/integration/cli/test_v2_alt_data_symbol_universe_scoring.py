"""Tests for V2 alternative-data symbol-universe scoring.

Paper/shadow only. No provider calls. No old Redis writes. No exchange
mutation. No live/shutdown approval.

Provider roster (operator directive 2026-07-16): coingecko, surf,
coinglass, public_intel, whale_walls. Four retired providers were
removed from the scoring contract and CLI system-wide.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.write_log: list[tuple[str, str, int | None]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.write_log.append((key, value, ex))
        return True


def _svc():
    return importlib.import_module(
        "v2.backend.app.services.alternative_data.symbol_scoring_contract"
    )


def _cli():
    return importlib.import_module(
        "v2.backend.app.cli.v2_alt_data_symbol_universe_scoring"
    )


def _moralis_bridge(symbol: str = "BTCUSDT") -> dict:
    return {
        "schema_version": "moralis_feature_bridge_v1",
        "provider": "moralis",
        "symbol": symbol,
        "timeframe": "1m",
        "generated_at": "2026-07-09T01:00:00Z",
        "available_at": "2026-07-09T01:00:00Z",
        "feature_cutoff": "2026-07-09T01:00:00Z",
        "decision_time_safe": True,
        "status": "CONFIGURED_NO_WATCHLIST",
        "dashboard_color": "GRAY",
        "feature_bridge_ready": False,
        "feature_count": 0,
        "required_feature_count": 15,
        "missing_feature_flags": ["moralis_whale_buy_usd"],
        "stale_feature_flags": [],
        "missing_mask_true": True,
        "stale_mask_true": False,
        "actual_payload_present": False,
        "heartbeat_only": True,
        "token_map_count": 9,
        "wallet_watchlist_count": 0,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }


def _coingecko(symbol: str = "BONKUSDT") -> dict:
    return {
        "schema_version": "v2_altdata_coingecko_symbol_discovery_v1",
        "symbol": symbol,
        "provider": "coingecko",
        "source_status": "API_OK",
        "coingecko_discovery_score": 0.82,
        "coingecko_liquidity_score": 0.75,
        "coingecko_momentum_score": 0.66,
        "coingecko_trend_score": 1.0,
        "provider_freshness_seconds": 60,
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "generated_utc": "2026-06-04T05:00:00Z",
    }


def _surf(symbol: str = "BONKUSDT") -> dict:
    return {
        "schema_version": "v2_altdata_surf_symbol_market_signal_v1",
        "symbol": symbol,
        "provider": "surf",
        "source_status": "API_OK",
        "surf_market_price_signal_score": 0.7,
        "surf_price_observation_count": 20,
        "provider_freshness_seconds": 60,
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "generated_utc": "2026-06-04T05:00:00Z",
    }


def _coinglass(
    symbol: str = "BTCUSDT",
    score: float | None = 0.58,
    source_status: str = "API_OK",
) -> dict:
    return {
        "schema_version": "v2_altdata_coinglass_symbol_signal_v1",
        "symbol": symbol,
        "provider": "coinglass",
        "source_status": source_status,
        "coinglass_derivatives_score": score,
        "provider_freshness_seconds": 60,
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "generated_utc": "2026-06-04T05:00:00Z",
    }


def _public_intel(symbol: str = "AAVEUSDT") -> dict:
    return {
        "schema_version": "v2_altdata_public_intel_symbol_signal_v1",
        "symbol": symbol,
        "provider": "public_intel_free_tier",
        "source_status": "API_OK",
        "public_intel_score": 0.88,
        "defillama_liquidity_score": 0.91,
        "defillama_tvl_momentum_score": 0.58,
        "news_attention_score": 0.7,
        "news_sentiment_score": 0.35,
        "fear_greed_score": 0.72,
        "btc_mempool_pressure_score": None,
        "provider_freshness_seconds": 60,
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "generated_utc": "2026-06-04T05:00:00Z",
    }


def _whale_walls(symbol: str = "BTCUSDT", score: float = 0.84) -> dict:
    return {
        "schema_version": "v2_altdata_whale_wall_symbol_signal_v1",
        "symbol": symbol,
        "provider": "whale_walls",
        "source_status": "DERIVED_OK",
        "whale_wall_score": score,
        "whale_bid_pressure_score": score,
        "whale_ask_pressure_score": 1.0 - score,
        "whale_wall_imbalance_score": (score * 2.0) - 1.0,
        "whale_wall_count_score": 0.5,
        "whale_wall_event_count": 4,
        "whale_bid_wall_notional_usd": 500_000.0,
        "whale_ask_wall_notional_usd": 100_000.0,
        "whale_total_wall_notional_usd": 600_000.0,
        "nearest_bid_wall_distance_bps": 4.0,
        "nearest_ask_wall_distance_bps": 8.0,
        "provider_freshness_seconds": 30,
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "generated_utc": "2026-06-04T05:00:00Z",
    }


def test_symbol_score_combines_providers_without_gate_override() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        coingecko_payload=_coingecko("BTCUSDT"),
        whale_walls_payload=_whale_walls("BTCUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
    )
    assert payload["schema_version"] == "v2_alternative_data_symbol_score_v2"
    assert payload["symbol"] == "BTCUSDT"
    assert payload["altdata_symbol_score"] is not None
    assert payload["coingecko_discovery_score"] == 0.82
    assert payload["whale_wall_score"] == 0.84
    assert payload["provider_availability_score"] == 1.0
    assert payload["providers_consulted"] == ["coingecko", "whale_walls"]
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["may_not_override_strict_paper_fill_gate"] is True
    assert payload["approves_live"] is False
    assert payload["checkpoint_compatibility_claimed"] is False
    assert payload["policy_architecture_parity_claimed"] is False


def test_symbol_score_embeds_moralis_bridge_without_changing_score() -> None:
    svc = _svc()
    baseline = svc.build_symbol_score_payload(
        "BTCUSDT",
        coingecko_payload=_coingecko("BTCUSDT"),
        surf_payload=_surf("BTCUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
    )
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        coingecko_payload=_coingecko("BTCUSDT"),
        surf_payload=_surf("BTCUSDT"),
        feature_payloads={"moralis": _moralis_bridge()},
        generated_utc="2026-06-04T05:05:00Z",
    )

    assert payload["altdata_symbol_score"] == baseline["altdata_symbol_score"]
    assert payload["missing_provider_flags"] == baseline["missing_provider_flags"]
    assert payload["stale_provider_flags"] == baseline["stale_provider_flags"]
    assert payload["input_presence"]["moralis_feature_bridge"] is True
    assert payload["moralis_feature_bridge_status"] == "CONFIGURED_NO_WATCHLIST"
    assert payload["moralis_missing_feature_flags"] == ["moralis_whale_buy_usd"]
    assert payload["moralis_token_map_count"] == 9
    assert payload["moralis_wallet_watchlist_count"] == 0
    assert payload["moralis_decision_time_safe"] is True
    assert payload["moralis_raw_key_exposed"] is False


def test_missing_provider_payloads_remain_explicit_and_do_not_fabricate_score() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "SOLUSDT",
        generated_utc="2026-05-18T05:05:00Z",
    )
    assert payload["altdata_symbol_score"] is None
    assert payload["provider_availability_score"] == 0.0
    assert payload["providers_consulted"] == []
    assert payload["provider_available"] == {}
    assert payload["network_call_attempted"] is False


def test_coingecko_and_surf_payloads_can_rank_alone() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "1000BONKUSDT",
        coingecko_payload=_coingecko("1000BONKUSDT"),
        surf_payload=_surf("1000BONKUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
    )
    assert payload["altdata_symbol_score"] is not None
    assert payload["provider_available"]["coingecko"] is True
    assert payload["provider_available"]["surf"] is True
    assert "coingecko" in payload["providers_consulted"]
    assert "surf" in payload["providers_consulted"]
    assert payload["coingecko_discovery_score"] == 0.82
    assert payload["surf_market_price_signal_score"] == 0.7
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_public_intel_payload_can_rank_alone() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "AAVEUSDT",
        public_intel_payload=_public_intel("AAVEUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
    )
    assert payload["altdata_symbol_score"] is not None
    assert payload["provider_available"]["public_intel"] is True
    assert "public_intel" in payload["providers_consulted"]
    assert payload["public_intel_score"] == 0.88
    assert payload["defillama_liquidity_score"] == 0.91
    assert payload["news_attention_score"] == 0.7
    assert payload["fear_greed_score"] == 0.72
    assert payload["input_presence"]["public_intel"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_whale_wall_payload_can_rank_alone() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        whale_walls_payload=_whale_walls("BTCUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
    )
    assert payload["altdata_symbol_score"] is not None
    assert payload["provider_available"]["whale_walls"] is True
    assert "whale_walls" in payload["providers_consulted"]
    assert payload["whale_wall_score"] == 0.84
    assert payload["whale_bid_pressure_score"] == 0.84
    assert payload["input_presence"]["whale_walls"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_provider_stale_feature_flags_propagate_without_blocking_ranking() -> None:
    """A fresh provider payload that self-reports delayed sub-features
    (stale_feature_flags) must still count for symbol selection while
    the staleness is surfaced honestly in stale_provider_flags."""
    svc = _svc()
    whale = _whale_walls("BTCUSDT")
    whale["stale_feature_flags"] = ["orderbook_snapshot_delayed"]

    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        whale_walls_payload=whale,
        generated_utc="2026-06-04T05:05:00Z",
    )

    assert payload["provider_available"]["whale_walls"] is True
    assert "whale_walls" in payload["providers_consulted"]
    assert (
        "whale_walls_orderbook_snapshot_delayed" in payload["stale_provider_flags"]
    )
    assert payload["stale_signal"] is True
    assert payload["altdata_symbol_score"] is not None
    assert payload["may_not_place_orders"] is True
    assert payload["writes_old_redis"] is False


def test_key_missing_status_is_visible_but_does_not_fabricate_signal() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        coinglass_payload=_coinglass(
            "BTCUSDT", score=None, source_status="KEY_MISSING_NO_NETWORK"
        ),
        generated_utc="2026-06-04T05:05:00Z",
    )
    assert payload["input_presence"]["coinglass"] is True
    assert payload["provider_available"]["coinglass"] is False
    assert payload["providers_consulted"] == []
    assert payload["altdata_symbol_score"] is None
    assert (
        "coinglass_source_status_KEY_MISSING_NO_NETWORK"
        in payload["missing_provider_flags"]
    )


def test_provider_ok_payload_without_symbol_signal_is_not_available() -> None:
    svc = _svc()
    coingecko = _coingecko("DOGEUSDT")
    coingecko["coingecko_discovery_score"] = None
    coingecko["coingecko_liquidity_score"] = None
    coingecko["coingecko_momentum_score"] = None
    coingecko["coingecko_trend_score"] = None
    payload = svc.build_symbol_score_payload(
        "DOGEUSDT",
        coingecko_payload=coingecko,
        generated_utc="2026-06-04T05:05:00Z",
    )
    assert payload["input_presence"]["coingecko"] is True
    assert payload["provider_source_status"]["coingecko"] == "API_OK"
    assert payload["provider_available"]["coingecko"] is False
    assert payload["providers_consulted"] == []
    assert payload["altdata_symbol_score"] is None
    assert (
        "coingecko_coingecko_discovery_score_missing"
        in payload["missing_provider_flags"]
    )


def test_stale_provider_payloads_are_flagged_and_not_consulted() -> None:
    svc = _svc()
    coingecko = _coingecko("BTCUSDT")
    coingecko["provider_freshness_seconds"] = 9_999
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        coingecko_payload=coingecko,
        surf_payload=_surf("BTCUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
        max_provider_age_seconds=1_800,
    )
    assert payload["provider_available"]["coingecko"] is False
    assert payload["provider_available"]["surf"] is True
    assert "coingecko_payload_stale" in payload["stale_reasons"]


def test_symbol_universe_candidates_rank_scores_without_expanding_paper_or_live() -> None:
    svc = _svc()
    generated = "2026-06-04T05:05:00Z"
    btc = svc.build_symbol_score_payload(
        "BTCUSDT",
        coingecko_payload=_coingecko("BTCUSDT"),
        surf_payload=_surf("BTCUSDT"),
        generated_utc=generated,
    )
    eth = svc.build_symbol_score_payload("ETHUSDT", generated_utc=generated)
    candidates = svc.build_symbol_universe_candidates(
        ("ETHUSDT", "BTCUSDT"),
        symbol_scores={"BTCUSDT": btc, "ETHUSDT": eth},
        existing_paper_symbols=("ETHUSDT",),
        generated_utc=generated,
    )
    assert candidates["candidate_symbol_list"][0] == "BTCUSDT"
    assert candidates["paper_symbols_continued"] == ["ETHUSDT"]
    assert candidates["paper_symbols_expanded"] is False
    assert candidates["live_symbols"] == []
    assert candidates["may_not_override_strict_paper_fill_gate"] is True


def test_cli_run_once_reads_v2_inputs_and_writes_only_allowed_outputs(tmp_path: Path) -> None:
    cli = _cli()
    fake = FakeRedis()
    fake.store["v2:altdata:coingecko:symbol:BTCUSDT"] = json.dumps(
        _coingecko("BTCUSDT")
    )
    fake.store["v2:altdata:surf:symbol:BTCUSDT"] = json.dumps(_surf("BTCUSDT"))
    fake.store["v2:altdata:coingecko:symbol:ETHUSDT"] = json.dumps(
        _coingecko("ETHUSDT")
    )
    fake.store["v2:altdata:public_intel:symbol:ETHUSDT"] = json.dumps(
        _public_intel("ETHUSDT")
    )
    fake.store["v2:altdata:whale_walls:symbol:ETHUSDT"] = json.dumps(
        _whale_walls("ETHUSDT")
    )
    public_a = tmp_path / "public_a/status.json"
    public_b = tmp_path / "public_b/status.json"
    payload = cli.run_once(
        symbols=("BTCUSDT", "ETHUSDT"),
        redis_client_override=fake,
        write_redis=True,
        public_paths=(public_a, public_b),
        max_provider_age_seconds=1_800,
    )
    assert payload["go_no_go"] == "V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_READY"
    assert json.loads(public_a.read_text()) == json.loads(public_b.read_text())
    keys = sorted(k for k, _v, _ex in fake.write_log)
    assert keys == [
        "v2:altdata:symbol_score:BTCUSDT",
        "v2:altdata:symbol_score:ETHUSDT",
        "v2:symbol_universe:altdata_candidates",
    ]
    assert all(
        key.startswith("v2:altdata:symbol_score:")
        or key == "v2:symbol_universe:altdata_candidates"
        for key in keys
    )
    assert payload["live_symbols"] == []
    assert payload["paper_symbols_expanded"] is False
    assert payload["provider_network_calls_attempted"] is False
    assert payload["symbol_scores"]["ETHUSDT"]["altdata_symbol_score"] is not None
    assert "coingecko" in payload["symbol_scores"]["ETHUSDT"]["providers_consulted"]
    assert "public_intel" in payload["symbol_scores"]["ETHUSDT"]["providers_consulted"]
    assert "whale_walls" in payload["symbol_scores"]["ETHUSDT"]["providers_consulted"]
    assert payload["symbol_scores"]["ETHUSDT"]["input_presence"]["whale_walls"] is True


def test_status_payload_contains_no_raw_secret_shaped_value(tmp_path: Path) -> None:
    cli = _cli()
    fake = FakeRedis()
    sentinel = "TEST_ONLY_NOT_REAL_SECRET_VALUE_FOR_ALT_SCORE"
    fake.store["v2:altdata:coingecko:symbol:BTCUSDT"] = json.dumps(
        {
            "symbol": "BTCUSDT",
            "source_status": "API_OK",
            "coingecko_discovery_score": 0.5,
        }
    )
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client_override=fake,
        write_redis=True,
        public_paths=(tmp_path / "a.json", tmp_path / "b.json"),
    )
    serialized = json.dumps(payload) + json.dumps(fake.write_log)
    assert sentinel not in serialized
    assert "COINGLASS_API_KEY" not in serialized
    assert "MORALIS_API_KEY" not in serialized


def test_no_network_or_exchange_mutation_imported() -> None:
    for name in ("requests", "httpx", "aiohttp", "websockets", "torch"):
        sys.modules.pop(name, None)
    import inspect

    svc = _svc()
    cli = _cli()
    forbidden = (
        "create" + "_order",
        "cancel" + "_order",
        "modify" + "_order",
        "set" + "_leverage",
        "set" + "_margin" + "_mode",
        "urlopen",
        "requests.",
        "httpx.",
        "websockets.",
    )
    for mod in (svc, cli):
        source = inspect.getsource(mod)
        for token in forbidden:
            assert token not in source
    for name in ("requests", "httpx", "aiohttp", "websockets", "torch"):
        assert name not in sys.modules


# --------------------------------------------------------------------------- #
# V2_ALT_DATA_SYMBOL_UNIVERSE_SCORING_READY field contract regressions        #
# --------------------------------------------------------------------------- #


def test_per_symbol_payload_exposes_user_named_provider_flag_aliases() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        coingecko_payload=_coingecko("BTCUSDT"),
        surf_payload=_surf("BTCUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
    )
    # User-specified field names must exist alongside the legacy aliases.
    assert "missing_provider_flags" in payload
    assert "stale_provider_flags" in payload
    # Same content as the legacy *_reasons lists.
    assert payload["missing_provider_flags"] == payload["missing_reasons"]
    assert payload["stale_provider_flags"] == payload["stale_reasons"]


def test_budget_exhausted_provider_degrades_availability_without_fabrication() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        coinglass_payload=_coinglass(
            "BTCUSDT", score=None, source_status="DAILY_BUDGET_EXHAUSTED"
        ),
        surf_payload=_surf("BTCUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
    )
    assert payload["provider_available"]["coinglass"] is False
    # Provider availability degrades but does not crash.
    assert payload["provider_availability_score"] < 1.0
    # Aggregate score still produced from the available Surf signal
    # only; no fabrication.
    assert payload["altdata_symbol_score"] is not None
    assert (
        "coinglass_source_status_DAILY_BUDGET_EXHAUSTED"
        in payload["missing_provider_flags"]
    )


def test_all_providers_missing_does_not_authorize_live_or_canary() -> None:
    """Even when every provider input is missing or stale, the payload
    safety invariants must remain pinned and no live/canary authorization
    can leak out."""
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        generated_utc="2026-05-21T05:05:00Z",
    )
    assert payload["altdata_symbol_score"] is None
    assert payload["provider_availability_score"] == 0.0
    assert payload["providers_consulted"] == []
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["may_not_override_strict_paper_fill_gate"] is True
    assert payload["may_not_authorize_live_or_canary"] is True


def test_altdata_symbol_rank_stamped_on_candidates_and_back_filled_on_scores() -> None:
    svc = _svc()
    generated = "2026-06-04T05:05:00Z"
    weak_coingecko = _coingecko("ETHUSDT")
    weak_coingecko["coingecko_discovery_score"] = 0.1
    weak_coingecko["coingecko_momentum_score"] = 0.05
    btc = svc.build_symbol_score_payload(
        "BTCUSDT",
        coingecko_payload=_coingecko("BTCUSDT"),
        surf_payload=_surf("BTCUSDT"),
        generated_utc=generated,
    )
    eth = svc.build_symbol_score_payload(
        "ETHUSDT",
        coingecko_payload=weak_coingecko,
        generated_utc=generated,
    )
    sol = svc.build_symbol_score_payload(
        "SOLUSDT",
        generated_utc=generated,
    )
    # Before the candidates pass, rank is None.
    assert btc["altdata_symbol_rank"] is None
    assert eth["altdata_symbol_rank"] is None
    candidates = svc.build_symbol_universe_candidates(
        ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        symbol_scores={"BTCUSDT": btc, "ETHUSDT": eth, "SOLUSDT": sol},
        existing_paper_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        generated_utc=generated,
    )
    rank_map = candidates["altdata_symbol_rank_per_candidate"]
    # BTC has the stronger provider signals, so it must rank above ETH;
    # SOL has no provider data and must rank last.
    assert rank_map["BTCUSDT"] < rank_map["ETHUSDT"]
    assert rank_map["SOLUSDT"] == 3
    # Rank stamped back onto each row.
    for row in candidates["candidate_rows"]:
        assert row["altdata_symbol_rank"] == rank_map[row["symbol"]]
    # And back-filled onto the per-symbol score payloads we passed in.
    assert btc["altdata_symbol_rank"] == rank_map["BTCUSDT"]
    assert eth["altdata_symbol_rank"] == rank_map["ETHUSDT"]
    assert sol["altdata_symbol_rank"] == rank_map["SOLUSDT"]


def test_candidates_payload_keeps_live_blocked_and_does_not_expand_paper_symbols() -> None:
    svc = _svc()
    candidates = svc.build_symbol_universe_candidates(
        ["BTCUSDT", "ETHUSDT", "SOLUSDT"],
        symbol_scores={},
        existing_paper_symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        generated_utc="2026-05-21T05:05:00Z",
    )
    assert candidates["live_symbols"] == []
    assert candidates["live_symbols_continued"] == []
    assert candidates["paper_symbols_expanded"] is False
    assert candidates["may_not_override_strict_paper_fill_gate"] is True
    assert candidates["may_not_authorize_live_or_canary"] is True
    assert candidates["approves_live"] is False
    assert candidates["approves_canary"] is False
    assert candidates["approves_legacy_shutdown"] is False
    assert candidates["approves_redis_trim"] is False
    # paper_symbols_continued preserves the existing set verbatim.
    assert candidates["paper_symbols_continued"] == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


def test_stale_payload_does_not_inflate_provider_availability() -> None:
    svc = _svc()
    stale_coingecko = _coingecko("BTCUSDT")
    stale_coingecko["provider_freshness_seconds"] = 99_999
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        coingecko_payload=stale_coingecko,
        surf_payload=_surf("BTCUSDT"),
        generated_utc="2026-06-04T05:05:00Z",
        max_provider_age_seconds=1_800,
    )
    # Stale CoinGecko → provider_available[coingecko]=False → degraded score.
    assert payload["provider_available"]["coingecko"] is False
    assert payload["provider_availability_score"] < 1.0
    assert "coingecko_payload_stale" in payload["stale_provider_flags"]


# --------------------------------------------------------------------------- #
# Codex regression: input-boundary remediation                                #
#                                                                             #
# These tests prove the scoring lane does NOT read or advertise               #
# v2:paper:* or v2:risk:* inputs.                                             #
# --------------------------------------------------------------------------- #


class _RecordingFakeRedis(FakeRedis):
    def __init__(self) -> None:
        super().__init__()
        self.read_log: list[str] = []

    def get(self, key: str):
        self.read_log.append(key)
        return self.store.get(key)


def test_cli_load_inputs_for_symbol_does_not_read_v2_paper_or_v2_risk_keys() -> None:
    cli = _cli()
    redis = _RecordingFakeRedis()
    cli._load_inputs_for_symbol(redis, "BTCUSDT")
    for key in redis.read_log:
        assert not key.startswith("v2:paper:"), key
        assert not key.startswith("v2:risk:"), key


def test_cli_load_inputs_keys_returned_dict_has_no_paper_or_risk_fields() -> None:
    cli = _cli()
    inputs = cli._load_inputs_for_symbol(_RecordingFakeRedis(), "BTCUSDT")
    assert "paper_payloads" not in inputs
    assert "risk_payloads" not in inputs


def test_run_once_status_payload_does_not_advertise_v2_paper_or_v2_risk_inputs() -> None:
    cli = _cli()
    redis = _RecordingFakeRedis()
    payload = cli.run_once(
        symbols=("BTCUSDT", "ETHUSDT"),
        redis_client_override=redis,
        write_redis=False,
        public_paths=(),
    )
    advertised = payload["allowed_inputs"]
    for entry in advertised:
        assert "v2:paper" not in entry, entry
        assert "v2:risk" not in entry, entry
    # The CLI must explicitly mark these namespaces as forbidden for
    # this lane so an auditor can grep for it.
    forbidden = payload.get("forbidden_input_namespaces_for_alt_data_scoring", [])
    assert "v2:paper:*" in forbidden
    assert "v2:risk:*" in forbidden
    assert "v2:altdata:coingecko:symbol:{symbol}" in advertised
    assert "v2:altdata:coinglass:symbol:{symbol}" in advertised
    assert "v2:altdata:whale_walls:symbol:{symbol}" in advertised
    assert "v2:features:moralis:{symbol}:{timeframe}" in advertised
    assert payload["scoring_input_boundary_remediated"] is True


def test_run_once_reads_no_v2_paper_or_v2_risk_keys_during_full_pipeline() -> None:
    cli = _cli()
    redis = _RecordingFakeRedis()
    # smoke_test=True acknowledges the explicit BTC/ETH/SOL test set; the
    # resolver fail-closes on this triple without an explicit opt-in.
    cli.run_once(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        redis_client_override=redis,
        write_redis=False,
        public_paths=(),
        smoke_test=True,
    )
    for key in redis.read_log:
        assert not key.startswith("v2:paper:"), key
        assert not key.startswith("v2:risk:"), key


def test_build_symbol_score_payload_input_presence_excludes_paper_and_risk() -> None:
    svc = _svc()
    payload = svc.build_symbol_score_payload(
        "BTCUSDT",
        market_payloads={"prices": {"price": 1.0}},
        feature_payloads={"latest": {"f": 1.0}},
        generated_utc="2026-05-21T20:00:00Z",
    )
    assert payload["input_presence"]["coingecko"] is False
    assert payload["input_presence"]["whale_walls"] is False
    assert payload["input_presence"]["market"] is True
    assert payload["input_presence"]["features"] is True
    assert "paper" not in payload["input_presence"]
    assert "risk" not in payload["input_presence"]


def test_build_symbol_score_payload_rejects_paper_or_risk_kwargs() -> None:
    """The contract's public signature must NOT accept paper/risk
    payloads. Passing them should raise TypeError."""
    svc = _svc()
    import pytest

    with pytest.raises(TypeError):
        svc.build_symbol_score_payload(
            "BTCUSDT",
            paper_payloads={"positions": []},  # type: ignore[call-arg]
        )
    with pytest.raises(TypeError):
        svc.build_symbol_score_payload(
            "BTCUSDT",
            risk_payloads={"decisions": []},  # type: ignore[call-arg]
        )


def test_run_once_keeps_safety_pins_after_remediation() -> None:
    cli = _cli()
    redis = _RecordingFakeRedis()
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client_override=redis,
        write_redis=False,
        public_paths=(),
    )
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["paper_symbols_expanded"] is False
    candidates = payload["symbol_universe_candidates"]
    assert candidates["paper_symbols_expanded"] is False
    assert candidates["live_symbols"] == []
    # Every per-symbol score still carries the strict-gate refusals.
    for sym_score in payload["symbol_scores"].values():
        assert sym_score["may_not_override_strict_paper_fill_gate"] is True
        assert sym_score["may_not_authorize_live_or_canary"] is True


def test_run_once_only_writes_to_allowlisted_keys() -> None:
    cli = _cli()
    redis = _RecordingFakeRedis()
    cli.run_once(
        symbols=("BTCUSDT", "ETHUSDT"),
        redis_client_override=redis,
        write_redis=True,
        public_paths=(),
    )
    for key, _value, _ex in redis.write_log:
        assert (
            key.startswith("v2:altdata:symbol_score:")
            or key == "v2:symbol_universe:altdata_candidates"
        ), key
        assert not key.startswith("v2:paper"), key
        assert not key.startswith("v2:risk"), key
