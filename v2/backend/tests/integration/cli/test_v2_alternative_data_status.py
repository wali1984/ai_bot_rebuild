"""Tests for the V2 alternative-data status scaffold.

No provider network calls. No raw key publication. No old Redis writes.
No exchange mutation. No live/shutdown approval.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def ping(self) -> bool:
        return True

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        return True

    def get(self, key: str):
        return self.store.get(key)


def _cli():
    return importlib.import_module("v2.backend.app.cli.v2_alternative_data_status")


def _registry():
    return importlib.import_module(
        "v2.backend.app.services.alternative_data.provider_registry"
    )


def _cache():
    return importlib.import_module("v2.backend.app.services.alternative_data.cache")


def test_provider_registry_contains_exact_allowed_providers(tmp_path: Path) -> None:
    registry = _registry()
    vault = tmp_path / "alternative_data.env"
    vault.write_text(
        "NANSEN_API_KEY=raw_nansen_value\n"
        "LUNARCRUSH_API_KEY=raw_lunar_value\n"
        "COINGECKO_API_KEY=raw_coingecko_value\n"
        "COINGLASS_API_KEY=raw_coinglass_value\n"
        "ASKSURF_API_KEY=raw_surf_value\n"
        "ARKHAM_API_KEY=\n",
        encoding="utf-8",
    )
    payload = registry.provider_registry_payload(vault_path=vault, env={})
    assert payload["provider_ids"] == list(registry.ALLOWED_PROVIDER_IDS)
    assert "nansen" in payload["provider_ids"]
    assert "lunarcrush" in payload["provider_ids"]
    assert "coingecko" in payload["provider_ids"]
    assert "coinglass" in payload["provider_ids"]
    assert "surf" in payload["provider_ids"]
    assert "public_intel_free_tier" in payload["provider_ids"]
    assert "arkham_future" in payload["provider_ids"]
    assert "binance_existing" in payload["provider_ids"]
    assert "coinank_existing" in payload["provider_ids"]
    assert "liquidation_wss_existing" in payload["provider_ids"]
    serialized = json.dumps(payload)
    assert "raw_nansen_value" not in serialized
    assert "raw_lunar_value" not in serialized
    assert "raw_coingecko_value" not in serialized
    assert "raw_coinglass_value" not in serialized
    assert "raw_surf_value" not in serialized
    assert payload["raw_values_exposed"] is False


def test_public_intel_provider_family_stays_out_of_status_scaffold_sources() -> None:
    # Build the token in pieces so this test file does not itself create a
    # lane occurrence for the provider string. DeFiLlama-derived fields are now
    # intentionally allowed in the public-intel scoring contract, but the old
    # status scaffold still must not imply a direct provider client there.
    forbidden = ("Defi" + "Llama").lower()
    roots = [
        Path("v2/backend/app/services/alternative_data/provider_registry.py"),
        Path("v2/backend/app/services/alternative_data/rate_limits.py"),
        Path("v2/backend/app/services/alternative_data/cache.py"),
        Path("v2/backend/app/cli/v2_alternative_data_status.py"),
    ]
    hits: list[str] = []
    for root in roots:
        paths = [root] if root.is_file() else list(root.rglob("*.py"))
        for path in paths:
            text = path.read_text(encoding="utf-8").lower()
            normalized = text.replace("_", "").replace("-", "").replace(" ", "")
            if forbidden.lower() in normalized:
                hits.append(str(path))
    assert hits == []


def test_rate_limits_default_free_and_paid_disabled() -> None:
    rate_limits = importlib.import_module(
        "v2.backend.app.services.alternative_data.rate_limits"
    )
    payload = rate_limits.build_rate_limit_contract(
        alt_data_tier="paid",
        alt_data_enable_paid=True,
        paid_endpoints_validated=False,
    )
    assert payload["effective_tier"] == "free"
    assert payload["paid_tier_enabled"] is False
    nansen = next(row for row in payload["provider_limits"] if row["provider_id"] == "nansen")
    assert nansen["rate_limit_per_minute"] == 10
    assert nansen["daily_request_budget"] == 1000
    assert nansen["cache_ttl_seconds"] == 600
    assert nansen["per_symbol_cooldown_seconds"] == 300


def test_safe_redis_set_allows_only_three_altdata_contracts() -> None:
    cache = _cache()
    fake = FakeRedis()
    assert cache.safe_redis_set(fake, "v2:altdata:provider_status", {"ok": True}) is True
    assert cache.safe_redis_set(fake, "v2:altdata:symbol_score:BTCUSDT", {"ok": True}) is True
    assert cache.safe_redis_set(fake, "v2:symbol_universe:altdata_candidates", {"ok": True}) is True
    assert cache.safe_redis_set(fake, "prediction:BTCUSDT", {"bad": True}) is False
    assert cache.safe_redis_set(fake, "v2:altdata:nansen:status", {"bad": True}) is False
    assert sorted(fake.store) == [
        "v2:altdata:provider_status",
        "v2:altdata:symbol_score:BTCUSDT",
        "v2:symbol_universe:altdata_candidates",
    ]


def test_status_payload_is_dry_run_and_safety_bounded(tmp_path: Path) -> None:
    cli = _cli()
    vault = tmp_path / "alternative_data.env"
    vault.write_text(
        "NANSEN_API_KEY=raw_nansen_value\n"
        "LUNARCRUSH_API_KEY=raw_lunar_value\n"
        "ARKHAM_API_KEY=\n",
        encoding="utf-8",
    )
    payload = cli.build_status_payload(
        symbols=("BTCUSDT", "ETHUSDT"),
        vault_path=vault,
        env={},
    )
    body = json.dumps(payload)
    assert "raw_nansen_value" not in body
    assert "raw_lunar_value" not in body
    assert payload["go_no_go"] == "V2_ALT_DATA_PROVIDER_REGISTRY_RATE_LIMIT_AND_DASHBOARD_SCAFFOLD_READY"
    assert payload["placeholder_score_redis_writes_disabled"] is True
    assert payload["score_key_owner"] == "v2_alt_data_symbol_universe_scoring"
    assert payload["candidate_key_owner"] == "v2_alt_data_symbol_candidate_publisher"
    assert payload["provider_network_calls_attempted"] is False
    assert payload["dry_run_only"] is True
    assert payload["paid_tier_enabled"] is False
    assert payload["checkpoint_compatibility_claimed"] is False
    assert payload["policy_architecture_parity_claimed"] is False
    assert payload["may_not_override_strict_paper_fill_gate"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["writes_old_redis"] is False
    assert payload["exchange_mutation"] is False


def test_run_once_writes_worklog_public_and_allowed_redis_only(tmp_path: Path) -> None:
    cli = _cli()
    vault = tmp_path / "alternative_data.env"
    vault.write_text(
        "NANSEN_API_KEY=raw_nansen_value\n"
        "LUNARCRUSH_API_KEY=raw_lunar_value\n",
        encoding="utf-8",
    )
    fake = FakeRedis()
    fake.store["v2:altdata:symbol_score:BTCUSDT"] = json.dumps(
        {"altdata_symbol_score": 0.77, "providers_consulted": ["public_intel"]}
    )
    worklog = tmp_path / "worklog/status.json"
    public_a = tmp_path / "public_a/status.json"
    public_b = tmp_path / "public_b/status.json"
    payload = cli.run_once(
        symbols=("BTCUSDT", "SOLUSDT"),
        redis_client_override=fake,
        write_redis=True,
        worklog_path=worklog,
        public_paths=(public_a, public_b),
        vault_path=vault,
        env={},
    )
    assert payload["go_no_go"] == "V2_ALT_DATA_PROVIDER_REGISTRY_RATE_LIMIT_AND_DASHBOARD_SCAFFOLD_READY"
    assert json.loads(worklog.read_text()) == json.loads(public_a.read_text())
    assert json.loads(public_a.read_text()) == json.loads(public_b.read_text())
    assert sorted(fake.store) == [
        "v2:altdata:provider_status",
        "v2:altdata:symbol_score:BTCUSDT",
    ]
    assert json.loads(fake.store["v2:altdata:symbol_score:BTCUSDT"]) == {
        "altdata_symbol_score": 0.77,
        "providers_consulted": ["public_intel"],
    }
    assert payload["redis_write_results"]["v2:altdata:symbol_score:{symbol}"] == "SKIPPED_PLACEHOLDER_WRITE_REAL_SCORER_OWNER"
    assert payload["redis_write_results"]["v2:symbol_universe:altdata_candidates"] == "SKIPPED_PLACEHOLDER_WRITE_REAL_CANDIDATE_PUBLISHER_OWNER"
    for raw in fake.store.values():
        assert "raw_nansen_value" not in raw
        assert "raw_lunar_value" not in raw


def test_dashboard_contract_has_top_10_with_binance_panels() -> None:
    registry = _registry()
    panels = list(registry.dashboard_contracts())
    assert len(panels) == 10
    ids = {panel["id"] for panel in panels}
    assert {
        "binance_12h_volume_leaders",
        "binance_12h_most_traded",
        "binance_12h_volatility_leaders",
    }.issubset(ids)
    overlay = next(panel for panel in panels if panel["id"] == "v2_trainer_risk_decision_overlay")
    assert overlay["altdata_may_not_override_strict_paper_fill_gate"] is True
    assert overlay["altdata_may_not_authorize_live_or_canary"] is True
    assert overlay["altdata_may_not_place_orders"] is True


def test_no_torch_or_network_clients_imported() -> None:
    for name in ("torch", "requests", "httpx", "aiohttp", "websockets"):
        sys.modules.pop(name, None)
    importlib.import_module("v2.backend.app.services.alternative_data.provider_registry")
    importlib.import_module("v2.backend.app.services.alternative_data.rate_limits")
    importlib.import_module("v2.backend.app.services.alternative_data.cache")
    importlib.import_module("v2.backend.app.services.alternative_data.symbol_scoring_contract")
    importlib.import_module("v2.backend.app.cli.v2_alternative_data_status")
    for name in ("torch", "requests", "httpx", "aiohttp", "websockets"):
        assert name not in sys.modules
