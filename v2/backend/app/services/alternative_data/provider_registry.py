"""Provider registry for the V2 alternative-data scaffold.

The registry is intentionally static and redacted. It documents allowed
providers, tier defaults, credential env-var names, and dashboard
contracts without reading raw key values or performing provider
network calls.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA_VERSION = "v2_alternative_data_provider_registry_scaffold_v1"
DEFAULT_VAULT_PATH = Path(".local_secrets/alternative_data.env")
ALLOWED_PROVIDER_IDS = (
    "nansen",
    "lunarcrush",
    "coingecko",
    "coinglass",
    "surf",
    "public_intel_free_tier",
    "aicoin_free_tier",
    "whale_walls_existing",
    "alphavantage",
    "tokenmetrics",
    "arkham_future",
    "binance_existing",
    "coinank_existing",
    "liquidation_wss_existing",
)


@dataclass(frozen=True)
class ProviderDefinition:
    id: str
    layer: str
    default_state: str
    credential_env_var: str | None
    free_rate_limit_per_minute: int | None
    free_daily_budget: int | None
    free_cache_ttl_seconds: int | None
    free_per_symbol_cooldown_seconds: int | None
    paid_rate_limit_per_minute: int | None = None
    paid_daily_budget: int | None = None
    paid_cache_ttl_seconds: int | None = None
    paid_per_symbol_cooldown_seconds: int | None = None
    future_placeholder_only: bool = False
    existing_v2_native: bool = False

    def redacted_dict(self, *, key_present: bool = False) -> dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer,
            "default_state": self.default_state,
            "credential_env_var_name_documented_only": self.credential_env_var,
            "credential_present": bool(key_present),
            "credential_value": "NEVER",
            "credential_raw_value_exposed": False,
            "free_tier": {
                "rate_limit_per_minute": self.free_rate_limit_per_minute,
                "daily_request_budget": self.free_daily_budget,
                "cache_ttl_seconds": self.free_cache_ttl_seconds,
                "per_symbol_cooldown_seconds": self.free_per_symbol_cooldown_seconds,
            },
            "paid_tier": {
                "rate_limit_per_minute": self.paid_rate_limit_per_minute,
                "daily_request_budget": self.paid_daily_budget,
                "cache_ttl_seconds": self.paid_cache_ttl_seconds,
                "per_symbol_cooldown_seconds": self.paid_per_symbol_cooldown_seconds,
                "enabled_by_default": False,
                "requires_codex_review": True,
            },
            "future_placeholder_only": self.future_placeholder_only,
            "existing_v2_native": self.existing_v2_native,
        }


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def provider_definitions() -> tuple[ProviderDefinition, ...]:
    return (
        ProviderDefinition(
            id="nansen",
            layer="on_chain",
            default_state="DISABLED_PENDING_OPERATOR_DECISION",
            credential_env_var="NANSEN_API_KEY",
            free_rate_limit_per_minute=10,
            free_daily_budget=1000,
            free_cache_ttl_seconds=600,
            free_per_symbol_cooldown_seconds=300,
            paid_rate_limit_per_minute=60,
            paid_daily_budget=50000,
            paid_cache_ttl_seconds=60,
            paid_per_symbol_cooldown_seconds=30,
        ),
        ProviderDefinition(
            id="lunarcrush",
            layer="off_chain",
            default_state="DISABLED_PENDING_OPERATOR_DECISION",
            credential_env_var="LUNARCRUSH_API_KEY",
            free_rate_limit_per_minute=10,
            free_daily_budget=1000,
            free_cache_ttl_seconds=600,
            free_per_symbol_cooldown_seconds=300,
            paid_rate_limit_per_minute=60,
            paid_daily_budget=50000,
            paid_cache_ttl_seconds=60,
            paid_per_symbol_cooldown_seconds=30,
        ),
        ProviderDefinition(
            id="coingecko",
            layer="market_discovery",
            default_state="ENABLED_FREE_TIER_DISCOVERY",
            credential_env_var="COINGECKO_API_KEY",
            free_rate_limit_per_minute=5,
            free_daily_budget=500,
            free_cache_ttl_seconds=21_600,
            free_per_symbol_cooldown_seconds=21_600,
            paid_rate_limit_per_minute=60,
            paid_daily_budget=50_000,
            paid_cache_ttl_seconds=600,
            paid_per_symbol_cooldown_seconds=600,
        ),
        ProviderDefinition(
            id="coinglass",
            layer="derivatives_discovery",
            default_state="ENABLED_FREE_TIER_STATUS_PROBE",
            credential_env_var="COINGLASS_API_KEY",
            free_rate_limit_per_minute=2,
            free_daily_budget=50,
            free_cache_ttl_seconds=21_600,
            free_per_symbol_cooldown_seconds=21_600,
            paid_rate_limit_per_minute=60,
            paid_daily_budget=50_000,
            paid_cache_ttl_seconds=600,
            paid_per_symbol_cooldown_seconds=600,
        ),
        ProviderDefinition(
            id="surf",
            layer="market_news_social_onchain_discovery",
            default_state="ENABLED_FREE_TIER_LIMITED_PROBE",
            credential_env_var="ASKSURF_API_KEY",
            free_rate_limit_per_minute=1,
            free_daily_budget=30,
            free_cache_ttl_seconds=21_600,
            free_per_symbol_cooldown_seconds=21_600,
            paid_rate_limit_per_minute=60,
            paid_daily_budget=50_000,
            paid_cache_ttl_seconds=600,
            paid_per_symbol_cooldown_seconds=600,
        ),
        ProviderDefinition(
            id="public_intel_free_tier",
            layer="defi_news_sentiment_onchain_context",
            default_state="ENABLED_FREE_TIER_PUBLIC_NO_KEY",
            credential_env_var=None,
            free_rate_limit_per_minute=6,
            free_daily_budget=120,
            free_cache_ttl_seconds=3_600,
            free_per_symbol_cooldown_seconds=3_600,
            paid_rate_limit_per_minute=None,
            paid_daily_budget=None,
            paid_cache_ttl_seconds=None,
            paid_per_symbol_cooldown_seconds=None,
        ),
        ProviderDefinition(
            id="aicoin_free_tier",
            layer="market_coin_orderflow_airdrop_drop_radar",
            default_state="ENABLED_FREE_TIER_GUARDED_ENDPOINT_MAPPING_REQUIRED",
            credential_env_var="AICOIN_ACCESS_KEY_ID",
            free_rate_limit_per_minute=15,
            free_daily_budget=666,
            free_cache_ttl_seconds=3_600,
            free_per_symbol_cooldown_seconds=3_600,
            paid_rate_limit_per_minute=30,
            paid_daily_budget=666,
            paid_cache_ttl_seconds=900,
            paid_per_symbol_cooldown_seconds=900,
        ),
        ProviderDefinition(
            id="whale_walls_existing",
            layer="orderbook_wall_detection",
            default_state="ALREADY_INTEGRATED_NATIVE_V2_DERIVED_FROM_ORDERBOOK",
            credential_env_var=None,
            free_rate_limit_per_minute=None,
            free_daily_budget=None,
            free_cache_ttl_seconds=60,
            free_per_symbol_cooldown_seconds=60,
            existing_v2_native=True,
        ),
        ProviderDefinition(
            id="alphavantage",
            layer="news_sentiment",
            default_state="DISABLED_PENDING_OPERATOR_DECISION",
            credential_env_var="ALPHAVANTAGE_API_KEY",
            free_rate_limit_per_minute=5,
            free_daily_budget=500,
            free_cache_ttl_seconds=900,
            free_per_symbol_cooldown_seconds=600,
            paid_rate_limit_per_minute=75,
            paid_daily_budget=50000,
            paid_cache_ttl_seconds=120,
            paid_per_symbol_cooldown_seconds=60,
        ),
        ProviderDefinition(
            id="tokenmetrics",
            layer="ratings_and_sentiment",
            default_state="DISABLED_PENDING_OPERATOR_DECISION",
            credential_env_var="TOKENMETRICS_API_KEY",
            free_rate_limit_per_minute=5,
            free_daily_budget=500,
            free_cache_ttl_seconds=900,
            free_per_symbol_cooldown_seconds=600,
            paid_rate_limit_per_minute=60,
            paid_daily_budget=50000,
            paid_cache_ttl_seconds=120,
            paid_per_symbol_cooldown_seconds=60,
        ),
        ProviderDefinition(
            id="arkham_future",
            layer="on_chain",
            default_state="PLACEHOLDER_FUTURE_ONLY_NO_INTEGRATION_TODAY",
            credential_env_var="ARKHAM_API_KEY",
            free_rate_limit_per_minute=None,
            free_daily_budget=None,
            free_cache_ttl_seconds=None,
            free_per_symbol_cooldown_seconds=None,
            future_placeholder_only=True,
        ),
        ProviderDefinition(
            id="binance_existing",
            layer="predictive",
            default_state="ALREADY_INTEGRATED_NATIVE_V2",
            credential_env_var=None,
            free_rate_limit_per_minute=None,
            free_daily_budget=None,
            free_cache_ttl_seconds=None,
            free_per_symbol_cooldown_seconds=None,
            existing_v2_native=True,
        ),
        ProviderDefinition(
            id="coinank_existing",
            layer="predictive",
            default_state="ALREADY_INTEGRATED_NATIVE_V2",
            credential_env_var=None,
            free_rate_limit_per_minute=None,
            free_daily_budget=None,
            free_cache_ttl_seconds=None,
            free_per_symbol_cooldown_seconds=None,
            existing_v2_native=True,
        ),
        ProviderDefinition(
            id="liquidation_wss_existing",
            layer="predictive",
            default_state="ALREADY_INTEGRATED_PAPER_SHADOW_DAEMON_ACTIVE",
            credential_env_var=None,
            free_rate_limit_per_minute=None,
            free_daily_budget=None,
            free_cache_ttl_seconds=None,
            free_per_symbol_cooldown_seconds=None,
            existing_v2_native=True,
        ),
    )


def _env_assignment_names(path: Path) -> dict[str, bool]:
    names: dict[str, bool] = {}
    if not path.exists() or not path.is_file():
        return names
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return names
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.removeprefix("export ").strip()
        names[name] = bool(value.strip().strip("'\""))
    return names


def redacted_key_presence(
    *,
    vault_path: Path = DEFAULT_VAULT_PATH,
    env: dict[str, str] | None = None,
    watched: Iterable[str] = (
        "NANSEN_API_KEY",
        "LUNARCRUSH_API_KEY",
        "COINGECKO_API_KEY",
        "COINGLASS_API_KEY",
        "ASKSURF_API_KEY",
        "SURF_API_KEY",
        "AICOIN_ACCESS_KEY_ID",
        "AICOIN_ACCESS_SECRET",
        "AICOIN_API_KEY",
        "AICOIN_API_SECRET",
        "AICOIN_API_BASE_URL",
        "ALPHAVANTAGE_API_KEY",
        "TOKENMETRICS_API_KEY",
        "ARKHAM_API_KEY",
    ),
) -> dict[str, bool]:
    process_env = {} if env is None else env
    vault_presence = _env_assignment_names(vault_path)
    result: dict[str, bool] = {}
    for name in watched:
        result[name] = bool(process_env.get(name)) or bool(vault_presence.get(name))
    return result


def provider_registry_payload(
    *,
    vault_path: Path = DEFAULT_VAULT_PATH,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    key_presence = redacted_key_presence(vault_path=vault_path, env=env)
    providers = []
    for provider in provider_definitions():
        providers.append(
            provider.redacted_dict(
                key_present=key_presence.get(provider.credential_env_var or "", False)
            )
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": utc_iso(),
        "implementation_status": "MIXED_SCAFFOLD_AND_ACTIVE_V2_PROVIDER_CLIENTS",
        "provider_ids": [p["id"] for p in providers],
        "providers": providers,
        "allowed_provider_ids": list(ALLOWED_PROVIDER_IDS),
        "raw_values_exposed": False,
        "provider_network_calls_attempted": False,
        "dry_run_only": True,
        "global_defaults": {
            "ALT_DATA_TIER": "free",
            "ALT_DATA_ENABLE_PAID": False,
            "paid_tier_enabled": False,
            "paid_endpoints_require_codex_review": True,
            "no_provider_failure_may_break_v2_runtime": True,
            "stale_but_safe_fallback": True,
        },
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "writes_old_redis": False,
        "exchange_mutation": False,
    }


def dashboard_contracts() -> tuple[dict[str, Any], ...]:
    base = {"credential_in_payload": "NEVER", "missing_or_stale_flag_required": True}
    return (
        {**base, "id": "binance_12h_volume_leaders", "title": "Binance 12h Volume Leaders", "rank": 1},
        {**base, "id": "binance_12h_most_traded", "title": "Binance 12h Most Traded", "rank": 2},
        {**base, "id": "binance_12h_volatility_leaders", "title": "Binance 12h Volatility Leaders", "rank": 3},
        {**base, "id": "futures_liquidation_tape", "title": "Futures Liquidation Tape", "rank": 4},
        {**base, "id": "funding_open_interest_intelligence", "title": "Funding / Open Interest Intelligence", "rank": 5},
        {**base, "id": "nansen_smart_money_flow", "title": "Nansen Smart Money Flow", "rank": 6},
        {**base, "id": "lunarcrush_social_momentum", "title": "LunarCrush Social Momentum", "rank": 7},
        {**base, "id": "arkham_entity_watchlist_future", "title": "Arkham Entity Watchlist Future", "rank": 8, "future_only_no_integration_today": True},
        {**base, "id": "v2_symbol_universe_altdata_ranking", "title": "V2 Symbol Universe Alt-Data Ranking", "rank": 9},
        {
            **base,
            "id": "v2_trainer_risk_decision_overlay",
            "title": "V2 Trainer / Risk Decision Overlay",
            "rank": 10,
            "altdata_may_not_override_strict_paper_fill_gate": True,
            "altdata_may_not_authorize_live_or_canary": True,
            "altdata_may_not_place_orders": True,
        },
    )
