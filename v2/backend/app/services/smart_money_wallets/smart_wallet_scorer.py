"""Behavioral smart-wallet candidate scoring.

Moralis does not supply Nansen-style labels. Scores produced here are candidate
labels only unless enough history is present. They must not approve trades by
themselves.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from app.services.smart_money_wallets.address_classifier import SMART_BLOCKING_CATEGORIES


SMART_WALLET_CANDIDATES_KEY = "v2:moralis:smart_wallet_candidates"
SMART_WALLET_SCORE_KEY = "v2:moralis:smart_wallet_score:{chain}:{address}"
MIN_VERIFIED_HISTORY_EVENTS = 50
MIN_CANDIDATE_HISTORY_EVENTS = 5


def score_wallet_candidate(
    *,
    chain: str,
    address: str,
    features: Mapping[str, Any],
    classification: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    category = str((classification or {}).get("category") or "unknown")
    if category in SMART_BLOCKING_CATEGORIES:
        label = "EXCHANGE_LIKE" if category.startswith("exchange_") else "CONTRACT_LIKE"
        score = 0.0
    else:
        score = _score(features)
        label = _label(score=score, features=features)
    payload = {
        "schema_version": "moralis_smart_wallet_score_v1",
        "chain": str(chain).lower(),
        "address": str(address).lower(),
        "label": label,
        "candidate_score": round(score, 6),
        "features": {
            "realized_profit_proxy": _float(features.get("realized_profit_proxy")),
            "win_rate_proxy": _float(features.get("win_rate_proxy")),
            "entry_timing_score": _float(features.get("entry_timing_score")),
            "exit_timing_score": _float(features.get("exit_timing_score")),
            "wallet_networth_usd": _float(features.get("wallet_networth_usd")),
            "token_diversity": _float(features.get("token_diversity")),
            "recent_activity": _float(features.get("recent_activity")),
            "whale_size_score": _float(features.get("whale_size_score")),
            "exchange_flow_score": _float(features.get("exchange_flow_score")),
            "contract_penalty": _float(features.get("contract_penalty")),
            "exchange_wallet_penalty": _float(features.get("exchange_wallet_penalty")),
            "history_event_count": int(_float(features.get("history_event_count"))),
        },
        "classification": dict(classification or {}),
        "unknown_wallet_called_smart_money": False,
        "standalone_trade_approval_allowed": False,
        "can_boost_confidence_modestly": label in {"CANDIDATE_SMART_WALLET", "VERIFIED_SMART_WALLET"},
        "can_block_reduce_size_or_require_hedge": True,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
    return payload


def publish_smart_wallet_candidates(
    redis_client: Any,
    *,
    scored_rows: list[Mapping[str, Any]],
    ttl_seconds: int = 6 * 3600,
) -> dict[str, Any]:
    rows = [dict(row) for row in scored_rows]
    keys_written = []
    for row in rows:
        chain = str(row.get("chain") or "").lower()
        address = str(row.get("address") or "").lower()
        if not chain or not address:
            continue
        key = SMART_WALLET_SCORE_KEY.format(chain=chain, address=address)
        redis_client.set(key, json.dumps(row, sort_keys=True, default=str), ex=ttl_seconds)
        keys_written.append(key)
    candidates = [
        row for row in rows
        if row.get("label") in {"CANDIDATE_SMART_WALLET", "VERIFIED_SMART_WALLET"}
    ]
    status = {
        "schema_version": "moralis_smart_wallet_candidates_v1",
        "status": "SMART_WALLET_CANDIDATES_READY" if candidates else "NO_SMART_WALLET_CANDIDATES",
        "generated_utc": _now(),
        "candidate_count": len(candidates),
        "verified_count": sum(1 for row in candidates if row.get("label") == "VERIFIED_SMART_WALLET"),
        "unknown_wallet_called_smart_money": False,
        "verified_without_history": False,
        "standalone_trade_approval_allowed": False,
        "rows": candidates,
        "raw_key_exposed": False,
        "core_system_blocked": False,
    }
    redis_client.set(SMART_WALLET_CANDIDATES_KEY, json.dumps(status, sort_keys=True, default=str), ex=ttl_seconds)
    status["keys_written"] = [*keys_written, SMART_WALLET_CANDIDATES_KEY]
    return status


def _score(features: Mapping[str, Any]) -> float:
    positives = (
        0.20 * _clamp01(features.get("realized_profit_proxy"))
        + 0.15 * _clamp01(features.get("win_rate_proxy"))
        + 0.12 * _clamp01(features.get("entry_timing_score"))
        + 0.12 * _clamp01(features.get("exit_timing_score"))
        + 0.10 * _clamp01(features.get("token_diversity"))
        + 0.10 * _clamp01(features.get("recent_activity"))
        + 0.12 * _clamp01(features.get("whale_size_score"))
        + 0.09 * _clamp01(features.get("exchange_flow_score"))
    )
    penalties = (
        0.35 * _clamp01(features.get("contract_penalty"))
        + 0.45 * _clamp01(features.get("exchange_wallet_penalty"))
    )
    return max(0.0, min(1.0, positives - penalties))


def _label(*, score: float, features: Mapping[str, Any]) -> str:
    history = int(_float(features.get("history_event_count")))
    if history >= MIN_VERIFIED_HISTORY_EVENTS and score >= 0.78:
        return "VERIFIED_SMART_WALLET"
    if history >= MIN_CANDIDATE_HISTORY_EVENTS and score >= 0.55:
        return "CANDIDATE_SMART_WALLET"
    if _clamp01(features.get("whale_size_score")) >= 0.70:
        return "WHALE_ONLY"
    return "UNKNOWN"


def _clamp01(value: Any) -> float:
    return max(0.0, min(1.0, _float(value)))


def _float(value: Any) -> float:
    try:
        if value in (None, ""):
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
