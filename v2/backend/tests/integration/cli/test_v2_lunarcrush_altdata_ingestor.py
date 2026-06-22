"""Tests for the V2 LunarCrush alternative-data paper/shadow client + CLI."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


SENTINEL_KEY = "TEST_ONLY_NOT_REAL_LUNARCRUSH_TOKEN_PLACEHOLDER_BBBB"


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


def _client_mod():
    return importlib.import_module(
        "v2.backend.app.services.alternative_data.lunarcrush_client"
    )


def _cli_mod():
    return importlib.import_module(
        "v2.backend.app.cli.v2_lunarcrush_altdata_ingestor"
    )


def test_key_missing_no_network_path_skips_network(tmp_path: Path, monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.delenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, raising=False)
    calls: list[str] = []

    def boom(url, headers, timeout):
        calls.append(url)
        raise AssertionError("HTTP should not be called when key is missing")

    client = mod.LunarCrushClient(http_get=boom, vault_path=tmp_path / "missing.env")
    res = client.fetch_symbol("BTCUSDT")
    assert res.source_status == mod.SOURCE_STATUS_KEY_MISSING
    assert calls == []
    assert res.social_momentum_score is None


def test_cli_key_missing_writes_status_no_network(
    tmp_path: Path, monkeypatch
) -> None:
    cli = _cli_mod()
    mod = _client_mod()
    monkeypatch.delenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, raising=False)
    fake = FakeRedis()
    monkeypatch.setattr(cli, "_connect_redis", lambda: fake)
    worklog = tmp_path / "wl/status.json"
    pub_a = tmp_path / "pa/status.json"
    pub_b = tmp_path / "pb/status.json"
    rc = cli.main(
        [
            "--symbols", "BTCUSDT,ETHUSDT",
            "--out-worklog", str(worklog),
            "--out-public", str(pub_a),
            "--out-public-secondary", str(pub_b),
            "--vault-path", str(tmp_path / "missing.env"),
        ]
    )
    assert rc == 0
    a = json.loads(worklog.read_text())
    assert a["go_no_go"] == "V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_READY"
    assert a["key_present"] is False
    assert a["source_status_counts"].get("KEY_MISSING_NO_NETWORK") == 2
    assert a["writes_legacy_redis"] is False
    assert a["writes_exchange_orders"] is False
    assert a["credential_in_payload"] == "NEVER"
    assert a["paid_endpoints_enabled"] is False
    keys_written = {k for (k, _v, _ex) in fake.write_log}
    assert mod.KEY_STATUS in keys_written
    assert not any(
        k.startswith("v2:altdata:lunarcrush:symbol:") for k in keys_written
    )


def test_client_emits_api_ok_with_bearer_auth(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    captured: list[dict] = []

    def http_get(url, headers, timeout):
        captured.append(dict(headers))
        return 200, {
            "data": [
                {
                    "galaxy_score": 70.0,
                    "social_score": 65.0,
                    "sentiment": 3.5,
                    "social_volume_24h_change_pct": 12.5,
                }
            ]
        }

    client = mod.LunarCrushClient(http_get=http_get)
    first = client.fetch_symbol("BTCUSDT")
    assert first.source_status == mod.SOURCE_STATUS_OK
    assert first.galaxy_or_equivalent_score == 70.0
    assert first.social_momentum_score is not None
    assert first.social_volume_velocity == 12.5
    assert first.sentiment_score is not None
    assert captured[0][mod.LUNARCRUSH_AUTH_HEADER_NAME].startswith(
        mod.LUNARCRUSH_AUTH_HEADER_VALUE_PREFIX
    )
    assert SENTINEL_KEY in captured[0][mod.LUNARCRUSH_AUTH_HEADER_NAME]
    # Cache hit on the second call
    second = client.fetch_symbol("BTCUSDT")
    assert second.source_status == mod.SOURCE_STATUS_CACHE_HIT
    assert len(captured) == 1


def test_client_handles_401_403_429_explicitly(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    for status_code, expected in (
        (401, mod.SOURCE_STATUS_AUTH_401),
        (402, mod.SOURCE_STATUS_PAYMENT_REQUIRED_402),
        (403, mod.SOURCE_STATUS_FORBIDDEN_403),
        (429, mod.SOURCE_STATUS_RATE_LIMITED_429),
    ):
        def http_get(url, headers, timeout, code=status_code):
            return code, None

        client = mod.LunarCrushClient(
            http_get=http_get, per_symbol_cooldown_seconds=0
        )
        res = client.fetch_symbol("BTCUSDT")
        assert res.source_status == expected, (status_code, res.source_status)
        assert res.social_momentum_score is None


def test_client_cooldown_blocks_second_call(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    calls = []

    def http_get(url, headers, timeout):
        calls.append(url)
        return 500, None

    now = [1_000_000]

    def now_ms():
        return now[0]

    client = mod.LunarCrushClient(
        http_get=http_get,
        now_ms_func=now_ms,
        per_symbol_cooldown_seconds=300,
    )
    first = client.fetch_symbol("BTCUSDT")
    second = client.fetch_symbol("BTCUSDT")
    assert first.source_status == mod.SOURCE_STATUS_NETWORK_ERROR
    assert second.source_status == mod.SOURCE_STATUS_COOLDOWN
    assert len(calls) == 1


def test_client_daily_budget_exhausts(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    calls = []

    def http_get(url, headers, timeout):
        calls.append(url)
        return 200, {"data": [{"galaxy_score": 50.0}]}

    rate = mod.RateLimitState(
        daily_budget_internal=2,
        daily_budget_remaining=2,
    )
    client = mod.LunarCrushClient(
        http_get=http_get,
        rate_limit=rate,
        per_symbol_cooldown_seconds=0,
        cache_ttl_seconds=0,
    )
    r1 = client.fetch_symbol("BTCUSDT")
    r2 = client.fetch_symbol("ETHUSDT")
    r3 = client.fetch_symbol("SOLUSDT")
    assert r1.source_status == mod.SOURCE_STATUS_OK
    assert r2.source_status == mod.SOURCE_STATUS_OK
    assert r3.source_status == mod.SOURCE_STATUS_BUDGET_EXHAUSTED
    assert len(calls) == 2


def test_internal_budget_below_provider_budget() -> None:
    mod = _client_mod()
    assert (
        mod.DEFAULT_FREE_DAILY_BUDGET_INTERNAL
        < mod.DEFAULT_FREE_DAILY_BUDGET_PROVIDER
    )


def test_free_tier_budget_constants_match_docs_validation() -> None:
    """Codex docs-validation approved these stricter free-tier values.

    DEFAULT_FREE_RATE_LIMIT_PER_MINUTE       = 6
    DEFAULT_FREE_DAILY_BUDGET_INTERNAL       = 500
    DEFAULT_FREE_CACHE_TTL_SECONDS           = 900
    DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS = 900

    These values must not be relaxed without a new Codex docs review.
    """
    mod = _client_mod()
    assert mod.DEFAULT_FREE_RATE_LIMIT_PER_MINUTE == 6
    assert mod.DEFAULT_FREE_DAILY_BUDGET_INTERNAL == 500
    assert mod.DEFAULT_FREE_CACHE_TTL_SECONDS == 900
    assert mod.DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS == 900
    # Sanity: internal budget remains strictly below provider ceiling.
    assert (
        mod.DEFAULT_FREE_DAILY_BUDGET_INTERNAL
        < mod.DEFAULT_FREE_DAILY_BUDGET_PROVIDER
    )
    # Sanity: cache TTL must be at least as long as the per-symbol
    # cooldown so cooldowns do not push consumers off cache too early.
    assert (
        mod.DEFAULT_FREE_CACHE_TTL_SECONDS
        >= mod.DEFAULT_FREE_PER_SYMBOL_COOLDOWN_SECONDS
    )


def test_lunarcrush_free_tier_strictly_below_nansen_rate_limit() -> None:
    """Cross-provider check: LunarCrush free-tier rate limit is now
    explicitly stricter than the Nansen free-tier rate limit so the
    LunarCrush lane cannot accidentally consume more than the
    docs-validation-approved share of the alternative-data request
    capacity.
    """
    lc = _client_mod()
    nansen = importlib.import_module(
        "v2.backend.app.services.alternative_data.nansen_client"
    )
    assert (
        lc.DEFAULT_FREE_RATE_LIMIT_PER_MINUTE
        <= nansen.DEFAULT_FREE_RATE_LIMIT_PER_MINUTE
    )
    assert (
        lc.DEFAULT_FREE_DAILY_BUDGET_INTERNAL
        <= nansen.DEFAULT_FREE_DAILY_BUDGET_INTERNAL
    )


def test_no_raw_key_in_status_payload_or_per_symbol_payload(monkeypatch) -> None:
    mod = _client_mod()
    cli = _cli_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)

    def http_get(url, headers, timeout):
        return 200, {"data": [{"galaxy_score": 40.0}]}

    fake = FakeRedis()
    out = cli.run_once(
        symbols=("BTCUSDT",),
        redis_client=fake,
        http_get=http_get,
        daily_budget_internal=10,
    )
    body_blobs = json.dumps(out["status_payload"]) + json.dumps(out["results"])
    for entry in fake.write_log:
        body_blobs += json.dumps({"k": entry[0], "v": entry[1]})
    assert SENTINEL_KEY not in body_blobs


def test_no_raw_key_in_cli_stdout(monkeypatch, capsys) -> None:
    cli = _cli_mod()
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    monkeypatch.setattr(cli, "_connect_redis", lambda: None)
    import v2.backend.app.services.alternative_data.lunarcrush_client as lc

    def fake_http_get(url, headers, timeout):
        return 200, {"data": [{"galaxy_score": 80.0}]}

    monkeypatch.setattr(lc, "_default_http_get", fake_http_get)
    rc = cli.main(
        [
            "--symbols", "BTCUSDT",
            "--out-worklog", str(Path("/tmp/_v2_lc_wl.json")),
            "--out-public", str(Path("/tmp/_v2_lc_pa.json")),
            "--out-public-secondary", str(Path("/tmp/_v2_lc_pb.json")),
        ]
    )
    assert rc == 0
    out, err = capsys.readouterr()
    assert SENTINEL_KEY not in out
    assert SENTINEL_KEY not in err


def test_client_only_writes_to_v2_altdata_lunarcrush_keys() -> None:
    mod = _client_mod()
    fake = FakeRedis()
    assert mod._safe_redis_set(fake, mod.KEY_STATUS, "x", ex=600) is True
    assert mod._safe_redis_set(
        fake,
        mod.KEY_PER_SYMBOL_TEMPLATE.format(symbol="BTCUSDT"),
        "x",
        ex=600,
    ) is True
    assert mod._safe_redis_set(fake, "prediction:BTCUSDT", "x", ex=600) is False
    assert mod._safe_redis_set(fake, "v2:altdata:nansen:status", "x", ex=600) is False
    for k in fake.store.keys():
        assert k.startswith("v2:altdata:lunarcrush:")


def test_parse_social_response_handles_empty_payload() -> None:
    mod = _client_mod()
    for body in (None, {}, [], "garbage", 42):
        out = mod.parse_social_response(body)
        assert out == {
            "social_momentum_score": None,
            "social_volume_velocity": None,
            "sentiment_score": None,
            "galaxy_or_equivalent_score": None,
        }


def test_parse_social_response_extracts_fields_from_first_record() -> None:
    mod = _client_mod()
    out = mod.parse_social_response(
        {
            "data": [
                {
                    "galaxy_score": 88.0,
                    "social_score": 75.0,
                    "sentiment": 4.0,
                    "social_volume_24h_change_pct": -25.0,
                },
                {"galaxy_score": 0.0},
            ]
        }
    )
    assert out["galaxy_or_equivalent_score"] == 88.0
    assert out["social_momentum_score"] == 0.75
    assert out["sentiment_score"] is not None
    assert out["social_volume_velocity"] == -25.0


def test_parse_social_response_normalizes_sentiment_scales() -> None:
    mod = _client_mod()
    # Scale 0..5
    out = mod.parse_social_response({"sentiment": 5.0})
    assert out["sentiment_score"] == 1.0
    # Scale -1..1 passed through
    out = mod.parse_social_response({"sentiment_score": -0.3})
    assert out["sentiment_score"] == -0.3
    # Scale 0..100
    out = mod.parse_social_response({"sentiment_score": 75.0})
    assert out["sentiment_score"] == 0.5


def test_provider_failure_does_not_crash_cli(monkeypatch, tmp_path: Path) -> None:
    cli = _cli_mod()
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    monkeypatch.setattr(cli, "_connect_redis", lambda: None)

    def fake_http_get(url, headers, timeout):
        raise ConnectionError("provider unreachable")

    import v2.backend.app.services.alternative_data.lunarcrush_client as lc

    monkeypatch.setattr(lc, "_default_http_get", fake_http_get)
    rc = cli.main(
        [
            "--symbols", "BTCUSDT",
            "--out-worklog", str(tmp_path / "wl.json"),
            "--out-public", str(tmp_path / "pa.json"),
            "--out-public-secondary", str(tmp_path / "pb.json"),
        ]
    )
    assert rc == 0
    payload = json.loads((tmp_path / "wl.json").read_text())
    assert payload["go_no_go"] == "V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_READY"
    counts = payload["source_status_counts"]
    assert counts.get("API_NETWORK_ERROR", 0) >= 1


def test_no_exchange_mutation_surface_in_module_source() -> None:
    # Source-scan for exchange-mutation entry points. Uses regex word
    # boundaries so legitimate safety-flag identifiers do not
    # accidentally trigger the forbidden-substring check.
    import inspect
    import re

    mod = _client_mod()
    cli = _cli_mod()
    forbidden = (
        "create" + "_order",
        "place" + "_order",
        "cancel" + "_order",
        "modify" + "_order",
        "set" + "_leverage",
        "set" + "_margin" + "_mode",
        "futures" + "_create" + "_order",
    )
    for source_mod in (mod, cli):
        src = inspect.getsource(source_mod)
        for token in forbidden:
            pattern = r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])"
            assert not re.search(pattern, src), (
                f"forbidden token in module: {token}"
            )


def test_no_torch_imported_in_lunarcrush_modules() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.alternative_data.lunarcrush_client"
    )
    importlib.import_module("v2.backend.app.cli.v2_lunarcrush_altdata_ingestor")
    assert "torch" not in sys.modules


def test_no_pickle_imported_in_lunarcrush_modules() -> None:
    import inspect

    for name in (
        "v2.backend.app.services.alternative_data.lunarcrush_client",
        "v2.backend.app.cli.v2_lunarcrush_altdata_ingestor",
    ):
        mod = importlib.import_module(name)
        src = inspect.getsource(mod)
        assert "pickle.load" not in src
        assert "pickle.loads" not in src
        assert "cPickle" not in src


def test_status_payload_includes_required_provider_fields(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.delenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, raising=False)
    fake = FakeRedis()
    rate = mod.RateLimitState()
    payload = mod.write_status_payload(
        fake,
        go_no_go="V2_LUNARCRUSH_FREE_TIER_CLIENT_PAPER_SHADOW_READY",
        rate_limit_state=rate,
        symbol_count=0,
        successful_symbol_count=0,
        source_status_counts={},
        key_present=False,
    )
    for field in (
        "schema_version",
        "generated_utc",
        "provider",
        "go_no_go",
        "tier",
        "paid_endpoints_enabled",
        "key_present",
        "credential_in_payload",
        "auth_header_name_documented_only",
        "auth_header_scheme_documented_only",
        "api_docs_url_documented",
        "rate_limit_state",
        "writes_legacy_redis",
        "writes_exchange_orders",
        "no_synthetic_signals",
        "gate",
        "symbols_real",
    ):
        assert field in payload, f"missing field {field}"
    assert payload["provider"] == "lunarcrush"
    assert payload["credential_in_payload"] == "NEVER"
    assert payload["tier"] == "free"
    assert payload["paid_endpoints_enabled"] is False
    assert payload["auth_header_scheme_documented_only"] == "Bearer"


def test_per_symbol_payload_includes_required_contract_fields(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)

    def http_get(url, headers, timeout):
        return 200, {"data": [{"galaxy_score": 65.0}]}

    client = mod.LunarCrushClient(http_get=http_get)
    res = client.fetch_symbol("BTCUSDT")
    payload = res.as_payload()
    for field in (
        "symbol",
        "provider",
        "social_momentum_score",
        "social_volume_velocity",
        "sentiment_score",
        "galaxy_or_equivalent_score",
        "provider_freshness_seconds",
        "missing_feature_flags",
        "stale_feature_flags",
        "rate_limit_state",
        "source_status",
    ):
        assert field in payload, f"missing required contract field: {field}"
    assert payload["provider"] == "lunarcrush"
    assert payload["credential_in_payload"] == "NEVER"


# --------------------------------------------------------------------------- #
# Endpoint allowlist regression tests                                         #
# (mirrors the V2 Nansen endpoint-allowlist remediation)                      #
# --------------------------------------------------------------------------- #


def test_constructor_refuses_social_endpoint_override() -> None:
    import pytest

    mod = _client_mod()
    with pytest.raises(TypeError):
        mod.LunarCrushClient(social_endpoint="/api/v4/paid/not-reviewed")


def test_constructor_refuses_api_base_url_override() -> None:
    import pytest

    mod = _client_mod()
    with pytest.raises(TypeError):
        mod.LunarCrushClient(api_base_url="https://attacker.example/")


def test_endpoint_allowlist_blocks_unknown_endpoint_id_before_http(
    monkeypatch,
) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    calls: list[str] = []

    def http_get(url, headers, timeout):
        calls.append(url)
        raise AssertionError(
            "HTTP must not be reached when endpoint_id is not allowlisted"
        )

    client = mod.LunarCrushClient(
        http_get=http_get, endpoint_id="paid_not_reviewed_endpoint"
    )
    res = client.fetch_symbol("BTCUSDT")
    assert res.source_status == mod.SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED
    assert res.source_status == "LUNARCRUSH_ENDPOINT_NOT_ALLOWLISTED"
    assert calls == []
    payload = res.as_payload()
    assert payload["credential_in_payload"] == "NEVER"
    assert payload["paid_endpoints_enabled"] is False
    assert payload["endpoint_allowlist_enforced"] is True
    assert payload["constructor_accepts_api_base_url_override"] is False
    assert payload["constructor_accepts_social_endpoint_override"] is False


def test_paid_endpoint_unreachable_when_paid_disabled(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    monkeypatch.delenv(mod.PAID_ENABLED_ENV_VAR, raising=False)
    mod.PAID_ENDPOINT_PATHS["paid_premium_social"] = "/api/v4/paid/premium-social"
    try:
        calls: list[str] = []

        def http_get(url, headers, timeout):
            calls.append(url)
            raise AssertionError(
                "HTTP must not be reached for paid endpoints when disabled"
            )

        client = mod.LunarCrushClient(
            http_get=http_get, endpoint_id="paid_premium_social"
        )
        res = client.fetch_symbol("BTCUSDT")
        assert res.source_status == mod.SOURCE_STATUS_PAID_ENDPOINT_DISABLED
        assert res.source_status == "LUNARCRUSH_PAID_ENDPOINT_DISABLED"
        assert calls == []
    finally:
        del mod.PAID_ENDPOINT_PATHS["paid_premium_social"]


def test_paid_endpoint_disabled_when_env_var_not_true(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    monkeypatch.setenv(mod.PAID_ENABLED_ENV_VAR, "false")
    mod.PAID_ENDPOINT_PATHS["paid_premium_social"] = "/api/v4/paid/premium-social"
    try:

        def http_get(url, headers, timeout):
            raise AssertionError("HTTP must not be reached")

        client = mod.LunarCrushClient(
            http_get=http_get, endpoint_id="paid_premium_social"
        )
        res = client.fetch_symbol("BTCUSDT")
        assert res.source_status == mod.SOURCE_STATUS_PAID_ENDPOINT_DISABLED
    finally:
        del mod.PAID_ENDPOINT_PATHS["paid_premium_social"]


def test_free_endpoint_id_reaches_documented_base_url_only(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    seen: list[str] = []

    def http_get(url, headers, timeout):
        seen.append(url)
        return 200, {"data": [{"social_score": 75.0, "sentiment": 0.3}]}

    client = mod.LunarCrushClient(
        http_get=http_get, endpoint_id=mod.DEFAULT_ENDPOINT_ID
    )
    res = client.fetch_symbol("BTCUSDT")
    assert res.source_status == mod.SOURCE_STATUS_OK
    assert seen, "expected exactly one URL captured"
    assert seen[0].startswith(mod.LUNARCRUSH_API_BASE_URL_DOCUMENTED), seen[0]
    assert "/public/coins/list/v2" in seen[0]
    assert "limit=1000" in seen[0]
    assert "?symbol=" not in seen[0]
    assert "attacker" not in seen[0].lower()


def test_raw_key_never_appears_in_payload(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    client = mod.LunarCrushClient(endpoint_id="paid_not_reviewed_endpoint")
    res = client.fetch_symbol("BTCUSDT")
    flat = json.dumps(res.as_payload(), sort_keys=True)
    assert SENTINEL_KEY not in flat
    assert "NEVER" in flat


def test_no_legacy_redis_or_exchange_writes_on_refusal_paths(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, SENTINEL_KEY)
    client = mod.LunarCrushClient(endpoint_id="paid_not_reviewed_endpoint")
    res = client.fetch_symbol("BTCUSDT")
    payload = res.as_payload()
    assert res.source_status == mod.SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_module_allowlist_contains_only_reviewed_free_public_coins_today() -> None:
    mod = _client_mod()
    assert mod.DEFAULT_ENDPOINT_ID == "public_coins_list_v2_free"
    assert set(mod.FREE_ENDPOINT_PATHS.keys()) == {
        "public_coins_list_v2_free",
        "public_coins_list_v1_free",
    }
    assert mod.FREE_ENDPOINT_PATHS["public_coins_list_v2_free"] == "/public/coins/list/v2"
    assert mod.FREE_ENDPOINT_PATHS["public_coins_list_v1_free"] == "/public/coins/list/v1"
    assert mod.PAID_ENDPOINT_PATHS == {}
    assert mod.is_free_endpoint("public_coins_list_v2_free") is True
    assert mod.is_allowlisted_endpoint("public_coins_list_v2_free") is True
    assert mod.is_allowlisted_endpoint("paid_not_reviewed_endpoint") is False
    assert mod.is_paid_endpoint("public_coins_list_v2_free") is False


def test_status_payload_surfaces_endpoint_allowlist_contract(
    tmp_path, monkeypatch
) -> None:
    cli = _cli_mod()
    mod = _client_mod()
    monkeypatch.delenv(mod.LUNARCRUSH_API_KEY_ENV_VAR, raising=False)
    monkeypatch.delenv(mod.PAID_ENABLED_ENV_VAR, raising=False)
    fake = FakeRedis()
    monkeypatch.setattr(cli, "_connect_redis", lambda: fake)
    worklog = tmp_path / "wl/status.json"
    pub_a = tmp_path / "pa/status.json"
    pub_b = tmp_path / "pb/status.json"
    rc = cli.main(
        [
            "--symbols", "BTCUSDT",
            "--out-worklog", str(worklog),
            "--out-public", str(pub_a),
            "--out-public-secondary", str(pub_b),
            "--vault-path", str(tmp_path / "missing.env"),
        ]
    )
    assert rc == 0
    a = json.loads(worklog.read_text())
    assert a["endpoint_allowlist_enforced"] is True
    assert a["constructor_accepts_api_base_url_override"] is False
    assert a["constructor_accepts_social_endpoint_override"] is False
    assert a["paid_endpoints_enabled"] is False
    assert a["paid_endpoint_ids_registered"] == []
    assert "public_coins_list_v2_free" in a["free_endpoint_ids_allowed"]
    assert "public_coins_list_v1_free" in a["free_endpoint_ids_allowed"]
    assert a["paid_endpoints_env_var"] == "ALT_DATA_ENABLE_PAID"
    assert a["paid_endpoints_env_value"] is False
    assert a["network_call_attempted"] is False
