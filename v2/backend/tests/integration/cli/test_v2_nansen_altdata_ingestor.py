"""Tests for the V2 Nansen alternative-data paper/shadow client + CLI.

Paper-only. No real network IO. No real API key. No torch import. No
legacy filesystem mutation. No silent zero-fill.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


SENTINEL_KEY = "TEST_ONLY_NOT_REAL_NANSEN_TOKEN_PLACEHOLDER_AAAA"


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
        "v2.backend.app.services.alternative_data.nansen_client"
    )


def _cli_mod():
    return importlib.import_module(
        "v2.backend.app.cli.v2_nansen_altdata_ingestor"
    )


def test_key_missing_no_network_path_skips_network(tmp_path: Path, monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.delenv(mod.NANSEN_API_KEY_ENV_VAR, raising=False)
    calls: list[str] = []

    def boom(url, headers, timeout):
        calls.append(url)
        raise AssertionError("HTTP should not be called when key is missing")

    client = mod.NansenClient(http_get=boom, vault_path=tmp_path / "missing.env")
    res = client.fetch_symbol("BTCUSDT")
    assert res.source_status == mod.SOURCE_STATUS_KEY_MISSING
    assert calls == []
    assert res.smart_money_score is None


def test_cli_key_missing_writes_status_no_network(
    tmp_path: Path, monkeypatch
) -> None:
    cli = _cli_mod()
    mod = _client_mod()
    monkeypatch.delenv(mod.NANSEN_API_KEY_ENV_VAR, raising=False)

    def boom(url, headers, timeout):
        raise AssertionError("HTTP must not be called when key is missing")

    # Force the CLI to use FakeRedis so we can inspect writes.
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
    assert a["go_no_go"] == "V2_NANSEN_FREE_TIER_CLIENT_PAPER_SHADOW_READY"
    assert a["key_present"] is False
    assert a["network_call_attempted"] is False
    assert a["provider_network_calls_attempted"] is False
    assert a["source_status_counts"].get("KEY_MISSING_NO_NETWORK") == 2
    assert a["writes_legacy_redis"] is False
    assert a["writes_exchange_orders"] is False
    assert a["credential_in_payload"] == "NEVER"
    assert a["paid_endpoints_enabled"] is False
    assert a["live_gate"] == "blocked_human_only"
    assert a["live_symbols"] == []
    assert a["may_not_override_strict_paper_fill_gate"] is True
    # Status was written to Redis; only v2:altdata:nansen:status, never
    # any per-symbol key when the key is absent.
    keys_written = {k for (k, _v, _ex) in fake.write_log}
    assert mod.KEY_STATUS in keys_written
    assert not any(
        k.startswith("v2:altdata:nansen:symbol:") for k in keys_written
    )


def test_client_emits_api_ok_and_caches_response(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    captured_headers: list[dict] = []

    def http_get(url, headers, timeout):
        captured_headers.append(dict(headers))
        return 200, {"data": [{"net_flow_usd": 500_000.0}]}

    now = [1_000_000]

    def now_ms():
        return now[0]

    client = mod.NansenClient(http_get=http_get, now_ms_func=now_ms)
    first = client.fetch_symbol("BTCUSDT")
    assert first.source_status == mod.SOURCE_STATUS_OK
    assert first.smart_money_score is not None
    assert -1.0 <= first.smart_money_score <= 1.0
    assert first.smart_money_flow_direction == "long"
    # Second fetch in the same TTL window must come from cache.
    second = client.fetch_symbol("BTCUSDT")
    assert second.source_status == mod.SOURCE_STATUS_CACHE_HIT
    assert len(captured_headers) == 1
    assert captured_headers[0][mod.NANSEN_AUTH_HEADER_NAME] == SENTINEL_KEY


def test_client_loads_key_from_local_vault_without_payload_leak(tmp_path: Path, monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.delenv(mod.NANSEN_API_KEY_ENV_VAR, raising=False)
    vault = tmp_path / "alternative_data.env"
    vault.write_text(f"NANSEN_API_KEY={SENTINEL_KEY}\n", encoding="utf-8")
    captured_headers: list[dict] = []

    def http_get(url, headers, timeout):
        captured_headers.append(dict(headers))
        return 200, {"data": [{"net_flow_usd": 250_000.0}]}

    client = mod.NansenClient(http_get=http_get, vault_path=vault)
    result = client.fetch_symbol("BTCUSDT")
    payload = result.as_payload()
    assert result.source_status == mod.SOURCE_STATUS_OK
    assert captured_headers[0][mod.NANSEN_AUTH_HEADER_NAME] == SENTINEL_KEY
    assert SENTINEL_KEY not in json.dumps(payload)
    assert payload["credential_in_payload"] == "NEVER"
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_client_handles_401_403_429_explicitly(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)

    for status_code, expected in (
        (401, mod.SOURCE_STATUS_AUTH_401),
        (402, mod.SOURCE_STATUS_PAYMENT_REQUIRED_402),
        (403, mod.SOURCE_STATUS_FORBIDDEN_403),
        (429, mod.SOURCE_STATUS_RATE_LIMITED_429),
    ):
        def http_get(url, headers, timeout, code=status_code):
            return code, None

        client = mod.NansenClient(
            http_get=http_get, per_symbol_cooldown_seconds=0
        )
        res = client.fetch_symbol("BTCUSDT")
        assert res.source_status == expected, (status_code, res.source_status)
        assert res.smart_money_score is None


def test_client_cooldown_blocks_second_call(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    calls = []

    def http_get(url, headers, timeout):
        calls.append(url)
        return 500, None  # any non-cacheable code

    now = [1_000_000]

    def now_ms():
        return now[0]

    client = mod.NansenClient(
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
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    calls = []

    def http_get(url, headers, timeout):
        calls.append(url)
        return 200, {"data": [{"net_flow_usd": 0.0}]}

    rate = mod.RateLimitState(
        daily_budget_internal=2,
        daily_budget_remaining=2,
    )
    client = mod.NansenClient(
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


def test_client_internal_budget_stays_below_provider_budget() -> None:
    mod = _client_mod()
    assert (
        mod.DEFAULT_FREE_DAILY_BUDGET_INTERNAL
        < mod.DEFAULT_FREE_DAILY_BUDGET_PROVIDER
    )


def test_no_raw_key_in_status_payload_or_per_symbol_payload(monkeypatch) -> None:
    mod = _client_mod()
    cli = _cli_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)

    def http_get(url, headers, timeout):
        return 200, {"data": [{"net_flow_usd": 100.0}]}

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
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    # Force the CLI to skip Redis (cleaner stdout assertion).
    monkeypatch.setattr(cli, "_connect_redis", lambda: None)
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    # Stub the http path so the CLI returns API_OK without real net IO.
    import v2.backend.app.services.alternative_data.nansen_client as nc

    def fake_http_get(url, headers, timeout):
        return 200, {"data": [{"net_flow_usd": 10.0}]}

    monkeypatch.setattr(nc, "_default_http_get", fake_http_get)
    rc = cli.main(
        [
            "--symbols", "BTCUSDT",
            "--out-worklog", str(Path("/tmp/_v2_nansen_wl.json")),
            "--out-public", str(Path("/tmp/_v2_nansen_pa.json")),
            "--out-public-secondary", str(Path("/tmp/_v2_nansen_pb.json")),
        ]
    )
    assert rc == 0
    out, err = capsys.readouterr()
    assert SENTINEL_KEY not in out
    assert SENTINEL_KEY not in err


def test_client_only_writes_to_v2_altdata_nansen_keys() -> None:
    mod = _client_mod()
    fake = FakeRedis()
    # status write should accept
    assert mod._safe_redis_set(fake, mod.KEY_STATUS, "x", ex=600) is True
    # per-symbol write should accept
    assert mod._safe_redis_set(
        fake,
        mod.KEY_PER_SYMBOL_TEMPLATE.format(symbol="BTCUSDT"),
        "x",
        ex=600,
    ) is True
    # legacy / unscoped keys must be refused
    assert mod._safe_redis_set(fake, "prediction:BTCUSDT", "x", ex=600) is False
    assert mod._safe_redis_set(fake, "signals:paper", "x", ex=600) is False
    assert mod._safe_redis_set(fake, "v2:altdata:lunarcrush:status", "x", ex=600) is False
    for k in fake.store.keys():
        assert k.startswith("v2:altdata:nansen:")


def test_parse_smart_money_response_handles_empty_payload() -> None:
    mod = _client_mod()
    assert mod.parse_smart_money_response(None) == {
        "smart_money_score": None,
        "smart_money_flow_direction": None,
        "entity_flow_score": None,
    }
    assert mod.parse_smart_money_response({}) == {
        "smart_money_score": None,
        "smart_money_flow_direction": None,
        "entity_flow_score": None,
    }
    assert mod.parse_smart_money_response("garbage") == {
        "smart_money_score": None,
        "smart_money_flow_direction": None,
        "entity_flow_score": None,
    }


def test_parse_smart_money_response_aggregates_net_flow_list() -> None:
    mod = _client_mod()
    out = mod.parse_smart_money_response(
        {"data": [{"net_flow_usd": 250_000.0}, {"net_flow_usd": -50_000.0}]}
    )
    assert out["smart_money_score"] == 0.2
    assert out["smart_money_flow_direction"] == "long"


def test_parse_smart_money_response_picks_up_explicit_score_fields() -> None:
    mod = _client_mod()
    out = mod.parse_smart_money_response(
        {"smart_money_score": -0.42, "flow_direction": "short", "entity_flow_score": 0.7}
    )
    assert out["smart_money_score"] == -0.42
    assert out["smart_money_flow_direction"] == "short"
    assert out["entity_flow_score"] == 0.7


def test_provider_failure_does_not_crash_cli(monkeypatch, tmp_path: Path) -> None:
    cli = _cli_mod()
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    monkeypatch.setattr(cli, "_connect_redis", lambda: None)

    def fake_http_get(url, headers, timeout):
        raise ConnectionError("provider unreachable")

    import v2.backend.app.services.alternative_data.nansen_client as nc

    monkeypatch.setattr(nc, "_default_http_get", fake_http_get)
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
    assert payload["go_no_go"] == "V2_NANSEN_FREE_TIER_CLIENT_PAPER_SHADOW_READY"
    counts = payload["source_status_counts"]
    assert counts.get("API_NETWORK_ERROR", 0) >= 1


def test_no_exchange_mutation_surface_in_module_source() -> None:
    import inspect

    mod = _client_mod()
    cli = _cli_mod()
    forbidden = (
        "create" + "_order(",
        "place" + "_order(",
        "cancel" + "_order(",
        "modify" + "_order(",
        "set" + "_leverage(",
        "set" + "_margin" + "_mode(",
        "futures" + "_create" + "_order(",
    )
    for source_mod in (mod, cli):
        src = inspect.getsource(source_mod)
        for token in forbidden:
            assert token not in src, f"forbidden token in module: {token}"


def test_no_torch_imported_in_nansen_modules() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.alternative_data.nansen_client"
    )
    importlib.import_module("v2.backend.app.cli.v2_nansen_altdata_ingestor")
    assert "torch" not in sys.modules


def test_no_pickle_imported_in_nansen_modules() -> None:
    # The client and ingestor must not deserialize pickle blobs.
    import inspect

    for name in (
        "v2.backend.app.services.alternative_data.nansen_client",
        "v2.backend.app.cli.v2_nansen_altdata_ingestor",
    ):
        mod = importlib.import_module(name)
        src = inspect.getsource(mod)
        assert "pickle.load" not in src
        assert "pickle.loads" not in src
        assert "cPickle" not in src


def test_status_payload_includes_required_provider_fields(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.delenv(mod.NANSEN_API_KEY_ENV_VAR, raising=False)
    fake = FakeRedis()
    rate = mod.RateLimitState()
    payload = mod.write_status_payload(
        fake,
        go_no_go="V2_NANSEN_FREE_TIER_CLIENT_PAPER_SHADOW_READY",
        rate_limit_state=rate,
        symbol_count=0,
        successful_symbol_count=0,
        source_status_counts={},
        key_present=False,
        network_call_attempted=False,
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
        "api_docs_url_documented",
        "rate_limit_state",
        "writes_legacy_redis",
        "writes_exchange_orders",
        "no_synthetic_signals",
        "gate",
        "symbols_real",
        "live_gate",
        "live_symbols",
        "approves_live",
        "may_not_override_strict_paper_fill_gate",
        "may_not_authorize_live_or_canary",
        "may_not_place_orders",
        "network_call_attempted",
        "provider_network_calls_attempted",
    ):
        assert field in payload, f"missing field {field}"
    assert payload["provider"] == "nansen"
    assert payload["credential_in_payload"] == "NEVER"
    assert payload["tier"] == "free"
    assert payload["paid_endpoints_enabled"] is False
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["may_not_override_strict_paper_fill_gate"] is True
    assert payload["network_call_attempted"] is False


def test_per_symbol_payload_includes_required_contract_fields(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)

    def http_get(url, headers, timeout):
        return 200, {"data": [{"net_flow_usd": 1000.0}]}

    client = mod.NansenClient(http_get=http_get)
    res = client.fetch_symbol("BTCUSDT")
    payload = res.as_payload()
    for field in (
        "symbol",
        "provider",
        "smart_money_score",
        "smart_money_flow_direction",
        "entity_flow_score",
        "provider_freshness_seconds",
        "missing_feature_flags",
        "stale_feature_flags",
        "rate_limit_state",
        "source_status",
        "live_gate",
        "live_symbols",
        "approves_live",
        "may_not_override_strict_paper_fill_gate",
        "may_not_authorize_live_or_canary",
        "may_not_place_orders",
    ):
        assert field in payload, f"missing required contract field: {field}"
    assert payload["provider"] == "nansen"
    assert payload["credential_in_payload"] == "NEVER"
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["may_not_override_strict_paper_fill_gate"] is True


# --------------------------------------------------------------------------- #
# Endpoint allowlist regression tests                                         #
# (would have caught V2_NANSEN_FREE_TIER_CLIENT_CODEX_FAIL)                   #
# --------------------------------------------------------------------------- #


def test_constructor_refuses_smart_money_endpoint_override() -> None:
    """Codex's fail proof: ``NansenClient(smart_money_endpoint=...)`` must
    not be a thing. Constructor must raise ``TypeError``."""
    import pytest

    mod = _client_mod()
    with pytest.raises(TypeError):
        mod.NansenClient(smart_money_endpoint="/api/v1/paid/not-reviewed")


def test_constructor_refuses_api_base_url_override() -> None:
    import pytest

    mod = _client_mod()
    with pytest.raises(TypeError):
        mod.NansenClient(api_base_url="https://attacker.example/")


def test_endpoint_allowlist_blocks_unknown_endpoint_id_before_http(
    tmp_path, monkeypatch
) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    calls: list[str] = []

    def http_get(url, headers, timeout):
        calls.append(url)
        raise AssertionError(
            "HTTP must not be reached when endpoint_id is not allowlisted"
        )

    client = mod.NansenClient(
        http_get=http_get, endpoint_id="paid_not_reviewed_endpoint"
    )
    res = client.fetch_symbol("BTCUSDT")
    assert res.source_status == mod.SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED
    assert res.source_status == "NANSEN_ENDPOINT_NOT_ALLOWLISTED"
    assert calls == []
    payload = res.as_payload()
    # Refusal payload must still pin the safety invariants and never
    # claim a network call happened.
    assert payload["credential_in_payload"] == "NEVER"
    assert payload["paid_endpoints_enabled"] is False
    assert payload["endpoint_allowlist_enforced"] is True
    assert payload["constructor_accepts_api_base_url_override"] is False
    assert payload["constructor_accepts_smart_money_endpoint_override"] is False


def test_paid_endpoint_unreachable_when_paid_disabled(monkeypatch) -> None:
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    # ALT_DATA_ENABLE_PAID is unset / "" -> paid disabled.
    monkeypatch.delenv(mod.PAID_ENABLED_ENV_VAR, raising=False)
    # Inject a registered-but-paid endpoint ID. The test temporarily
    # adds it to the paid set, then verifies the client refuses to
    # reach it.
    mod.PAID_ENDPOINT_PATHS["paid_premium_alpha"] = "/api/v1/paid/premium-alpha"
    try:
        calls: list[str] = []

        def http_get(url, headers, timeout):
            calls.append(url)
            raise AssertionError(
                "HTTP must not be reached for paid endpoints when disabled"
            )

        client = mod.NansenClient(
            http_get=http_get, endpoint_id="paid_premium_alpha"
        )
        res = client.fetch_symbol("BTCUSDT")
        assert res.source_status == mod.SOURCE_STATUS_PAID_ENDPOINT_DISABLED
        assert res.source_status == "NANSEN_PAID_ENDPOINT_DISABLED"
        assert calls == []
    finally:
        del mod.PAID_ENDPOINT_PATHS["paid_premium_alpha"]


def test_paid_endpoint_disabled_when_env_var_not_true(monkeypatch) -> None:
    """``ALT_DATA_ENABLE_PAID=false`` (or any non-"true" string) keeps
    paid disabled even when the ID is registered."""
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    monkeypatch.setenv(mod.PAID_ENABLED_ENV_VAR, "false")
    mod.PAID_ENDPOINT_PATHS["paid_premium_alpha"] = "/api/v1/paid/premium-alpha"
    try:

        def http_get(url, headers, timeout):
            raise AssertionError("HTTP must not be reached")

        client = mod.NansenClient(
            http_get=http_get, endpoint_id="paid_premium_alpha"
        )
        res = client.fetch_symbol("BTCUSDT")
        assert res.source_status == mod.SOURCE_STATUS_PAID_ENDPOINT_DISABLED
    finally:
        del mod.PAID_ENDPOINT_PATHS["paid_premium_alpha"]


def test_free_endpoint_id_reaches_documented_base_url_only(monkeypatch) -> None:
    """When the allowlisted free endpoint ID is used and a key is
    present, the URL passed to http_get must start with the
    documented base URL — never a caller-supplied host."""
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    seen: list[str] = []
    bodies: list[dict] = []

    def http_get(url, headers, body, timeout):
        seen.append(url)
        bodies.append(dict(body))
        return 200, {"data": [{"net_flow_usd": 1.0}]}

    client = mod.NansenClient(
        http_get=http_get, endpoint_id=mod.DEFAULT_ENDPOINT_ID
    )
    res = client.fetch_symbol("BTCUSDT")
    assert res.source_status == mod.SOURCE_STATUS_OK
    assert seen, "expected exactly one URL captured"
    assert seen[0].startswith(mod.NANSEN_API_BASE_URL_DOCUMENTED), seen[0]
    assert "/api/v1/smart-money/holdings" in seen[0]
    assert "?symbol=" not in seen[0]
    assert "attacker" not in seen[0].lower()
    assert bodies[0]["premium_labels"] is False
    assert bodies[0]["pagination"]["per_page"] == 100
    assert bodies[0]["filters"]["include_smart_money_labels"] == ["Fund", "Smart Trader"]
    assert bodies[0]["order_by"] == [{"field": "value_usd", "direction": "DESC"}]


def test_raw_key_never_appears_in_payload(monkeypatch) -> None:
    """Even on the refusal paths, the raw API key value must never
    appear in any serialized payload field."""
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    client = mod.NansenClient(endpoint_id="paid_not_reviewed_endpoint")
    res = client.fetch_symbol("BTCUSDT")
    flat = json.dumps(res.as_payload(), sort_keys=True)
    assert SENTINEL_KEY not in flat
    assert "NEVER" in flat  # credential_in_payload


def test_no_legacy_redis_or_exchange_writes_on_refusal_paths(monkeypatch) -> None:
    """Refusal-path payloads must continue to assert no legacy Redis /
    exchange writes."""
    mod = _client_mod()
    monkeypatch.setenv(mod.NANSEN_API_KEY_ENV_VAR, SENTINEL_KEY)
    client = mod.NansenClient(endpoint_id="paid_not_reviewed_endpoint")
    res = client.fetch_symbol("BTCUSDT")
    payload = res.as_payload()
    assert res.source_status == mod.SOURCE_STATUS_ENDPOINT_NOT_ALLOWLISTED
    assert payload["writes_legacy_redis"] is False
    assert payload["writes_exchange_orders"] is False
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []


def test_module_allowlist_contains_only_reviewed_free_smart_money_endpoints_today() -> None:
    """Pins the current free-tier endpoint contract. If a new free
    endpoint is added, this test must be updated AND the new endpoint
    must be Codex-reviewed before being added."""
    mod = _client_mod()
    assert mod.DEFAULT_ENDPOINT_ID == "smart_money_holdings_free"
    assert set(mod.FREE_ENDPOINT_PATHS.keys()) == {
        "smart_money_netflow_free",
        "smart_money_holdings_free",
    }
    assert (
        mod.FREE_ENDPOINT_PATHS["smart_money_netflow_free"]
        == "/api/v1/smart-money/netflow"
    )
    assert (
        mod.FREE_ENDPOINT_PATHS["smart_money_holdings_free"]
        == "/api/v1/smart-money/holdings"
    )
    assert mod.PAID_ENDPOINT_PATHS == {}
    assert mod.is_free_endpoint("smart_money_holdings_free") is True
    assert mod.is_allowlisted_endpoint("smart_money_holdings_free") is True
    assert mod.is_allowlisted_endpoint("paid_not_reviewed_endpoint") is False
    assert mod.is_paid_endpoint("smart_money_netflow_free") is False


def test_status_payload_surfaces_endpoint_allowlist_contract(
    tmp_path, monkeypatch
) -> None:
    """The aggregate status payload written to Redis + worklog must
    surface the allowlist contract so operators / Codex can confirm
    the contract from the dashboard alone."""
    cli = _cli_mod()
    mod = _client_mod()
    monkeypatch.delenv(mod.NANSEN_API_KEY_ENV_VAR, raising=False)
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
    assert a["constructor_accepts_smart_money_endpoint_override"] is False
    assert a["paid_endpoints_enabled"] is False
    assert a["paid_endpoint_ids_registered"] == []
    assert "smart_money_netflow_free" in a["free_endpoint_ids_allowed"]
    assert "smart_money_holdings_free" in a["free_endpoint_ids_allowed"]
    assert a["paid_endpoints_env_var"] == "ALT_DATA_ENABLE_PAID"
    assert a["paid_endpoints_env_value"] is False
