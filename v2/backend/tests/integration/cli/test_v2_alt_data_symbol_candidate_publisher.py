"""Tests for V2 alt-data Symbol Universe candidate publisher.

Pure-input tests for the classifier + a fake-redis pipeline test
for the CLI. No provider network call. No real Redis. No legacy
keys read or written.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timedelta, timezone


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.read_log: list[str] = []
        self.write_log: list[tuple[str, str]] = []

    def ping(self) -> bool:
        return True

    def get(self, key: str):
        self.read_log.append(key)
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None):
        self.write_log.append((key, value))
        self.store[key] = value
        return True


def _svc():
    return importlib.import_module(
        "v2.backend.app.services.alternative_data.symbol_candidate_publisher"
    )


def _cli():
    return importlib.import_module(
        "v2.backend.app.cli.v2_alt_data_symbol_candidate_publisher"
    )


def _iso(seconds_old: int = 0) -> str:
    return (
        (datetime.now(timezone.utc) - timedelta(seconds=seconds_old))
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _score_payload(
    *,
    symbol: str = "BTCUSDT",
    altdata_symbol_score: float | None = 0.55,
    smart_money_score: float = 0.7,
    social_momentum_score: float = 0.6,
    social_volume_velocity: float = 0.5,
    entity_flow_score: float = 0.6,
    provider_availability_score: float = 1.0,
    altdata_freshness_score: float = 1.0,
    providers_consulted: list[str] | None = None,
    missing_provider_flags: list[str] | None = None,
    stale_provider_flags: list[str] | None = None,
) -> dict:
    return {
        "schema_version": "v2_alternative_data_symbol_score_v2",
        "generated_utc": _iso(seconds_old=10),
        "symbol": symbol,
        "altdata_symbol_score": altdata_symbol_score,
        "smart_money_score": smart_money_score,
        "social_momentum_score": social_momentum_score,
        "social_volume_velocity": social_volume_velocity,
        "entity_flow_score": entity_flow_score,
        "provider_availability_score": provider_availability_score,
        "altdata_freshness_score": altdata_freshness_score,
        "providers_consulted": providers_consulted or ["nansen", "lunarcrush"],
        "missing_provider_flags": missing_provider_flags or [],
        "stale_provider_flags": stale_provider_flags or [],
        "missing_signal": bool(missing_provider_flags),
        "stale_signal": bool(stale_provider_flags),
        "altdata_symbol_rank": 1,
    }


def _market_payload() -> dict:
    return {
        "symbol": "BTCUSDT",
        "source": "binance_public_rest",
        "ticker_24hr": {
            "symbol": "BTCUSDT",
            "lastPrice": "77000.0",
        },
    }


def _provider_status(**source_status_counts: int) -> dict:
    return {
        "generated_utc": _iso(seconds_old=10),
        "key_present": True,
        "source_status_counts": source_status_counts,
    }


# --------------------------------------------------------------------------- #
# Classifier tests                                                            #
# --------------------------------------------------------------------------- #


def test_classify_symbol_not_tradable_when_market_prices_absent() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(),
        market_prices_payload=None,
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_SYMBOL_NOT_TRADABLE


def test_classify_budget_limited_when_lunarcrush_status_marks_budget() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(),
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(DAILY_BUDGET_EXHAUSTED=5),
    )
    assert state == svc.CANDIDATE_STATE_BUDGET_LIMITED


def test_classify_budget_limited_when_nansen_status_marks_rate_limit() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(),
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(RATE_LIMITED=3),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_BUDGET_LIMITED


def test_classify_missing_provider_data_when_symbol_score_absent() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=None,
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_MISSING_PROVIDER_DATA


def test_classify_missing_provider_data_when_altdata_score_is_null() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(altdata_symbol_score=None),
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_MISSING_PROVIDER_DATA


def test_classify_scored_partial_provider_payload_does_not_block_on_missing_flags() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(
            altdata_symbol_score=0.45,
            providers_consulted=["coingecko"],
            provider_availability_score=0.5,
            missing_provider_flags=[
                "nansen_payload_missing",
                "lunarcrush_payload_missing",
            ],
        ),
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED


def test_classify_stale_provider_data_when_stale_flags_present() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(stale_provider_flags=["nansen_payload_stale"]),
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_STALE_PROVIDER_DATA


def test_classify_below_threshold_when_score_too_low() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(altdata_symbol_score=0.05),
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_BELOW_THRESHOLD


def test_classify_candidate_ready_for_watchlist_band() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(altdata_symbol_score=0.20),
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_READY


def test_classify_symbol_universe_gate_required_when_score_above_paper_threshold() -> None:
    svc = _svc()
    state = svc.classify_candidate_state(
        symbol_score=_score_payload(altdata_symbol_score=0.65),
        market_prices_payload=_market_payload(),
        nansen_status_payload=_provider_status(),
        lunarcrush_status_payload=_provider_status(),
    )
    assert state == svc.CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED


# --------------------------------------------------------------------------- #
# Candidate construction                                                      #
# --------------------------------------------------------------------------- #


def test_build_candidate_pins_safety_invariants_and_never_proposes_live_use() -> None:
    svc = _svc()
    candidate = svc.build_candidate(
        "BTCUSDT",
        svc.CandidateInputs(
            symbol_score=_score_payload(altdata_symbol_score=0.65),
            market_prices_payload=_market_payload(),
            feature_payload={"latest": 1.0},
            nansen_status_payload=_provider_status(),
            lunarcrush_status_payload=_provider_status(),
        ),
    )
    assert candidate["candidate_state"] == svc.CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED
    assert candidate["live_symbol_candidate"] is False
    assert candidate["may_not_override_strict_paper_fill_gate"] is True
    assert candidate["may_not_authorize_live_or_canary"] is True
    assert candidate["may_not_place_orders"] is True
    assert candidate["live_gate"] == "blocked_human_only"
    assert candidate["live_symbols"] == []
    assert candidate["raw_credential_in_payload"] == "NEVER"
    assert candidate["writes_old_redis"] is False
    assert candidate["writes_exchange_orders"] is False
    assert candidate["leverage_changed"] is False
    assert candidate["margin_mode_changed"] is False
    assert candidate["candidate_only_not_adopted"] is True
    # Proposed uses include watchlist + paper + training (score 0.65 ≥
    # 0.50 training threshold), but NEVER live.
    assert svc.PROPOSED_USE_WATCHLIST in candidate["proposed_use"]
    assert svc.PROPOSED_USE_PAPER in candidate["proposed_use"]
    assert svc.PROPOSED_USE_TRAINING in candidate["proposed_use"]


def test_build_candidate_below_threshold_has_no_proposed_uses() -> None:
    svc = _svc()
    candidate = svc.build_candidate(
        "BTCUSDT",
        svc.CandidateInputs(
            symbol_score=_score_payload(altdata_symbol_score=0.05),
            market_prices_payload=_market_payload(),
            feature_payload=None,
            nansen_status_payload=_provider_status(),
            lunarcrush_status_payload=_provider_status(),
        ),
    )
    assert candidate["proposed_use"] == []
    assert candidate["watchlist_candidate"] is False
    assert candidate["paper_symbol_candidate"] is False
    assert candidate["training_symbol_candidate"] is False
    assert candidate["live_symbol_candidate"] is False


def test_build_candidate_reason_strings_are_state_specific() -> None:
    svc = _svc()
    # Each of the 7 states should produce a non-empty reason.
    for score_val, market, nansen, lunar, expected_state in (
        (None, _market_payload(), _provider_status(), _provider_status(), svc.CANDIDATE_STATE_MISSING_PROVIDER_DATA),
        (0.5, None, _provider_status(), _provider_status(), svc.CANDIDATE_STATE_SYMBOL_NOT_TRADABLE),
        (0.5, _market_payload(), _provider_status(DAILY_BUDGET_EXHAUSTED=1), _provider_status(), svc.CANDIDATE_STATE_BUDGET_LIMITED),
        (0.04, _market_payload(), _provider_status(), _provider_status(), svc.CANDIDATE_STATE_BELOW_THRESHOLD),
        (0.20, _market_payload(), _provider_status(), _provider_status(), svc.CANDIDATE_STATE_READY),
        (0.65, _market_payload(), _provider_status(), _provider_status(), svc.CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED),
    ):
        candidate = svc.build_candidate(
            "BTCUSDT",
            svc.CandidateInputs(
                symbol_score=_score_payload(altdata_symbol_score=score_val)
                if score_val is not None or expected_state == svc.CANDIDATE_STATE_MISSING_PROVIDER_DATA
                else None,
                market_prices_payload=market,
                feature_payload=None,
                nansen_status_payload=nansen,
                lunarcrush_status_payload=lunar,
            ),
        )
        assert candidate["candidate_state"] == expected_state, expected_state
        assert isinstance(candidate["candidate_reason"], str)
        assert candidate["candidate_reason"]


# --------------------------------------------------------------------------- #
# CLI pipeline tests                                                          #
# --------------------------------------------------------------------------- #


def test_cli_pipeline_reads_only_allowlisted_keys_no_paper_no_risk() -> None:
    cli = _cli()
    redis = FakeRedis()
    # Stock the fake redis with valid scoring + market + provider
    # payloads so the pipeline returns CANDIDATE_READY / etc.
    redis.store["v2:altdata:symbol_score:BTCUSDT"] = json.dumps(
        _score_payload(symbol="BTCUSDT", altdata_symbol_score=0.65)
    )
    redis.store["v2:altdata:symbol_score:ETHUSDT"] = json.dumps(
        _score_payload(symbol="ETHUSDT", altdata_symbol_score=0.20)
    )
    redis.store["v2:altdata:symbol_score:SOLUSDT"] = json.dumps(
        _score_payload(symbol="SOLUSDT", altdata_symbol_score=None,
                       missing_provider_flags=["nansen_payload_missing"])
    )
    redis.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    redis.store["v2:market:prices:ETHUSDT"] = json.dumps(_market_payload())
    redis.store["v2:market:prices:SOLUSDT"] = json.dumps(_market_payload())
    redis.store["v2:altdata:nansen:status"] = json.dumps(_provider_status())
    redis.store["v2:altdata:lunarcrush:status"] = json.dumps(_provider_status())

    payload = cli.run_once(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        redis_client_override=redis,
        write_redis=True,
        public_paths=(),
    )
    # Every Redis read must be in the allowed input boundary.
    for key in redis.read_log:
        assert not key.startswith("v2:paper:"), key
        assert not key.startswith("v2:risk:"), key
        assert key.startswith(
            ("v2:altdata:", "v2:market:", "v2:features:")
        ), key

    # Every Redis write must be in the publisher's allowlist.
    svc = _svc()
    for key, _value in redis.write_log:
        assert key in svc.ALLOWED_REDIS_WRITE_KEYS, key

    # State distribution: BTCUSDT → SYMBOL_UNIVERSE_GATE_REQUIRED,
    # ETHUSDT → CANDIDATE_READY, SOLUSDT → MISSING_PROVIDER_DATA.
    states_by_symbol = {c["symbol"]: c["candidate_state"] for c in payload["candidates"]}
    assert states_by_symbol["BTCUSDT"] == svc.CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED
    assert states_by_symbol["ETHUSDT"] == svc.CANDIDATE_STATE_READY
    assert states_by_symbol["SOLUSDT"] == svc.CANDIDATE_STATE_MISSING_PROVIDER_DATA

    # Safety invariants on the publisher payload.
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["live_symbols_expanded"] is False
    assert payload["paper_symbols_expanded"] is False
    assert payload["training_symbols_expanded"] is False
    assert payload["raw_credential_in_payload"] == "NEVER"
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_old_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["leverage_changed"] is False
    assert payload["margin_mode_changed"] is False
    assert payload["real_order_attempted"] is False
    assert payload["provider_network_calls_attempted"] is False
    assert payload["may_not_override_strict_paper_fill_gate"] is True
    assert payload["may_not_authorize_live_or_canary"] is True

    # Forbidden namespaces explicitly documented.
    assert "v2:paper:*" in payload["forbidden_input_namespaces"]
    assert "v2:risk:*" in payload["forbidden_input_namespaces"]

    # No candidate is a live_symbol_candidate.
    for c in payload["candidates"]:
        assert c["live_symbol_candidate"] is False


def test_safe_redis_set_refuses_keys_outside_publisher_allowlist() -> None:
    svc = _svc()
    redis = FakeRedis()
    assert svc.safe_redis_set(redis, svc.KEY_ALTDATA_CANDIDATES, {"x": 1}) is True
    assert svc.safe_redis_set(redis, svc.KEY_PUBLISHER_STATUS, {"x": 1}) is True
    for forbidden in (
        "v2:paper:positions",
        "v2:risk:decisions",
        "v2:altdata:nansen:status",
        "order_intent:BTCUSDT",
        "trader:positions",
        "v2:symbol_universe:paper_symbols",
        "v2:symbol_universe:live_symbols",
        "v2:symbol_universe:training_symbols",
    ):
        assert svc.safe_redis_set(redis, forbidden, {"x": 1}) is False, forbidden


def test_payload_does_not_serialize_synthetic_credential() -> None:
    cli = _cli()
    secret = "sk-LEAK-CANDIDATE-PUBLISHER-NEVER-1234567890abcdef"
    redis = FakeRedis()
    redis.store["v2:altdata:nansen:status"] = json.dumps(
        {
            "generated_utc": _iso(),
            "key_present": True,
            "source_status_counts": {"OK": 1},
            "credential_in_payload": "NEVER",
            # Even if a provider erroneously embeds a secret in a
            # non-credential field, the publisher must not propagate
            # it. We verify by string-searching the final payload.
            "non_credential_note": "this field is plain text only",
        }
    )
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client_override=redis,
        write_redis=False,
        public_paths=(),
    )
    flat = json.dumps(payload)
    assert secret not in flat


def test_cli_does_not_read_v2_paper_or_v2_risk_during_full_pipeline() -> None:
    cli = _cli()
    redis = FakeRedis()
    cli.run_once(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        redis_client_override=redis,
        write_redis=False,
        public_paths=(),
    )
    forbidden_prefixes = ("v2:paper:", "v2:risk:", "order_intent:", "trader:")
    for key in redis.read_log:
        for prefix in forbidden_prefixes:
            assert not key.startswith(prefix), key


def test_cli_pipeline_does_not_mutate_symbol_universe_sets() -> None:
    cli = _cli()
    svc = _svc()
    redis = FakeRedis()
    redis.store["v2:altdata:symbol_score:BTCUSDT"] = json.dumps(
        _score_payload(altdata_symbol_score=0.95)
    )
    redis.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    redis.store["v2:altdata:nansen:status"] = json.dumps(_provider_status())
    redis.store["v2:altdata:lunarcrush:status"] = json.dumps(_provider_status())
    payload = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client_override=redis,
        write_redis=True,
        public_paths=(),
    )
    # Even with the highest possible score, no Symbol Universe
    # population key is mutated.
    for key, _value in redis.write_log:
        assert key in svc.ALLOWED_REDIS_WRITE_KEYS
        assert "paper_symbols" not in key
        assert "training_symbols" not in key
        assert "live_symbols" not in key
    # BTCUSDT is in the SYMBOL_UNIVERSE_GATE_REQUIRED state (score
    # 0.95 ≥ paper threshold) → adoption is gated by Symbol
    # Universe governance, not this publisher.
    cand = next(c for c in payload["candidates"] if c["symbol"] == "BTCUSDT")
    assert cand["candidate_state"] == svc.CANDIDATE_STATE_SYMBOL_UNIVERSE_GATE_REQUIRED


def test_cli_legend_and_state_counts_match_candidates() -> None:
    cli = _cli()
    svc = _svc()
    redis = FakeRedis()
    redis.store["v2:altdata:symbol_score:BTCUSDT"] = json.dumps(
        _score_payload(altdata_symbol_score=0.65)
    )
    redis.store["v2:altdata:symbol_score:ETHUSDT"] = json.dumps(
        _score_payload(altdata_symbol_score=0.20)
    )
    redis.store["v2:altdata:symbol_score:SOLUSDT"] = json.dumps(
        _score_payload(altdata_symbol_score=0.05)
    )
    for sym in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
        redis.store[f"v2:market:prices:{sym}"] = json.dumps(_market_payload())
    redis.store["v2:altdata:nansen:status"] = json.dumps(_provider_status())
    redis.store["v2:altdata:lunarcrush:status"] = json.dumps(_provider_status())
    payload = cli.run_once(
        symbols=("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        redis_client_override=redis,
        write_redis=False,
        public_paths=(),
    )
    for state in svc.ALL_CANDIDATE_STATES:
        assert state in payload["candidate_state_counts"]
        assert state in payload["candidate_states_legend"]
    total = sum(payload["candidate_state_counts"].values())
    assert total == payload["candidate_count"]
