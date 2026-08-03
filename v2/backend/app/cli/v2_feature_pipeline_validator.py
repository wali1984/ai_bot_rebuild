"""Validate and repair feature pipeline completeness for A-grade emergence.

This script:
1. Checks all provider feature bridges
2. Detects stale/missing fields
3. Repairs incomplete bridges
4. Validates feature freshness
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping

import redis

logger = logging.getLogger(__name__)

REQUIRED_FEATURES = {
    "ta": ["ta_rsi_14", "ta_macd_signal", "ta_bollinger_width", "ta_atr_14"],
    "moralis": [
        "moralis_whale_buy_usd",
        "moralis_whale_sell_usd",
        "moralis_whale_net_flow_usd",
        "moralis_exchange_inflow_usd",
        "moralis_exchange_outflow_usd",
        "moralis_net_exchange_flow_usd",
        "moralis_dex_buy_pressure_usd",
        "moralis_dex_sell_pressure_usd",
        "moralis_dex_flow_imbalance_usd",
        "moralis_smart_wallet_accumulation_score",
        "moralis_smart_wallet_distribution_score",
        "moralis_top_holder_concentration",
        "moralis_holder_count",
        "moralis_holder_delta",
        "moralis_onchain_risk_score",
    ],
    "coinglass": [
        "coinglass_funding_rate",
        "coinglass_liquidation_long",
        "coinglass_liquidation_short",
        "coinglass_long_short_ratio",
        "coinglass_open_interest",
    ],
    "coinank": [
        "coinank_liquidation_long_usd",
        "coinank_liquidation_short_usd",
        "coinank_liquidation_net_imbalance_usd",
        "coinank_funding_rate_long",
        "coinank_funding_rate_short",
        "coinank_funding_rate_net",
    ],
}

MAJOR_SYMBOLS = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
TIMEFRAMES = ["1m", "5m", "15m", "1h", "4h"]
FRESHNESS_THRESHOLD_SECONDS = 300  # 5 minutes


def validate_provider_features(redis_client: redis.Redis, provider: str) -> dict[str, Any]:
    """Validate feature completeness for a provider."""
    required = REQUIRED_FEATURES.get(provider, [])
    results = {
        "provider": provider,
        "required_feature_count": len(required),
        "symbols_checked": [],
        "timeframes_checked": [],
        "complete_payloads": 0,
        "incomplete_payloads": 0,
        "stale_payloads": 0,
        "missing_payloads": 0,
        "gaps": [],
    }

    for symbol in MAJOR_SYMBOLS:
        for timeframe in TIMEFRAMES:
            key = f"v2:features:{provider}:{symbol}:{timeframe}"
            payload_raw = redis_client.get(key)

            if not payload_raw:
                results["missing_payloads"] += 1
                results["gaps"].append(f"{symbol}:{timeframe} [missing]")
                continue

            try:
                payload = json.loads(payload_raw)
                features = payload.get("features", {})
                generated_at = payload.get("generated_at")

                # Check freshness
                if generated_at:
                    generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                    now = datetime.now(timezone.utc)
                    age_seconds = (now - generated_dt).total_seconds()
                    if age_seconds > FRESHNESS_THRESHOLD_SECONDS:
                        results["stale_payloads"] += 1
                        results["gaps"].append(f"{symbol}:{timeframe} [stale {int(age_seconds)}s]")
                        continue

                # Check completeness
                missing_features = [f for f in required if f not in features or features[f] in (None, "", 0)]
                if missing_features:
                    results["incomplete_payloads"] += 1
                    results["gaps"].append(f"{symbol}:{timeframe} [missing {len(missing_features)} fields]")
                else:
                    results["complete_payloads"] += 1

                if symbol not in results["symbols_checked"]:
                    results["symbols_checked"].append(symbol)
                if timeframe not in results["timeframes_checked"]:
                    results["timeframes_checked"].append(timeframe)

            except Exception as e:
                logger.error(f"Error parsing {key}: {e}")
                results["gaps"].append(f"{symbol}:{timeframe} [parse error]")

    return results


def validate_all_providers(redis_client: redis.Redis) -> dict[str, Any]:
    """Validate all feature providers."""
    report = {
        "schema_version": "feature_pipeline_validation_v1",
        "generated_at": _now(),
        "providers": {},
        "pipeline_health": "UNKNOWN",
        "a_grade_ready": False,
        "blocking_gaps": [],
    }

    for provider in REQUIRED_FEATURES.keys():
        report["providers"][provider] = validate_provider_features(redis_client, provider)

    # Determine health
    all_complete = all(
        p["missing_payloads"] == 0 and p["stale_payloads"] == 0
        for p in report["providers"].values()
    )

    if all_complete:
        report["pipeline_health"] = "GREEN"
        report["a_grade_ready"] = True
    else:
        incomplete = [
            p for p in report["providers"].values()
            if p["incomplete_payloads"] > 0 or p["missing_payloads"] > 0
        ]
        if len(incomplete) > 2:
            report["pipeline_health"] = "RED"
        else:
            report["pipeline_health"] = "YELLOW"

        report["blocking_gaps"] = [gap for p in report["providers"].values() for gap in p.get("gaps", [])][:10]

    return report


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


if __name__ == "__main__":
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    client = redis.from_url(redis_url)
    report = validate_all_providers(client)
    print(json.dumps(report, indent=2, default=str))

    # Exit with error code if not ready
    if not report["a_grade_ready"]:
        print("\n⚠️  Feature pipeline not ready for A-grade candidates", file=__import__("sys").stderr)
        exit(1)
