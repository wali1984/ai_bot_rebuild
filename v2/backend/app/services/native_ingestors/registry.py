"""V2 native ingestors registry + classification (P0.5).

Classifies each legacy ingestor into:
    NATIVE_V2
    DIRECT_LEGACY_OWNED_READONLY_PUBLIC_DATA
    READONLY_BRIDGED
    MISSING_IN_V2
    BLOCKED_BY_SECRET_OR_API
    BLOCKED_BY_RATE_LIMIT
    OPERATOR_DECISION_REQUIRED

This module performs no network IO and no Redis writes. It reads the
local secret vault footprint via env-name probing (without revealing
values) and records the resulting classification for each ingestor.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

CLASS_NATIVE_V2 = "NATIVE_V2"
CLASS_NATIVE_V2_READONLY_PUBLIC_DATA = "NATIVE_V2_READONLY_PUBLIC_DATA"
CLASS_DIRECT_LEGACY_OWNED_READONLY_PUBLIC_DATA = "DIRECT_LEGACY_OWNED_READONLY_PUBLIC_DATA"
CLASS_READONLY_BRIDGED = "READONLY_BRIDGED"
CLASS_MISSING_IN_V2 = "MISSING_IN_V2"
CLASS_BLOCKED_BY_SECRET_OR_API = "BLOCKED_BY_SECRET_OR_API"
CLASS_BLOCKED_BY_RATE_LIMIT = "BLOCKED_BY_RATE_LIMIT"
CLASS_OPERATOR_DECISION_REQUIRED = "OPERATOR_DECISION_REQUIRED"
CLASS_OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN = (
    "OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN"
)

ALL_CLASSIFICATIONS = (
    CLASS_NATIVE_V2,
    CLASS_NATIVE_V2_READONLY_PUBLIC_DATA,
    CLASS_DIRECT_LEGACY_OWNED_READONLY_PUBLIC_DATA,
    CLASS_READONLY_BRIDGED,
    CLASS_MISSING_IN_V2,
    CLASS_BLOCKED_BY_SECRET_OR_API,
    CLASS_BLOCKED_BY_RATE_LIMIT,
    CLASS_OPERATOR_DECISION_REQUIRED,
    CLASS_OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN,
)


@dataclass(frozen=True)
class IngestorClassification:
    classification: str
    rationale: str
    requires_secret_env: tuple[str, ...] = field(default_factory=tuple)
    public_market_data_only: bool = True
    v2_namespace_payload_path: Optional[str] = None
    rate_limit_concern_notes: str = ""


@dataclass(frozen=True)
class IngestorRecord:
    name: str
    legacy_path: str
    legacy_sha256: str
    legacy_size_bytes: int
    classification: IngestorClassification


INGESTOR_REGISTRY: tuple[tuple[str, str, str, int], ...] = (
    (
        "live_binance",
        "v2/legacy_owned_runtime/ingest/live_binance.py",
        "6c1eb771a3842e2d94b797eedd55aa624075c51c6d50aec701397f81dbace798",
        0,
    ),
    (
        "live_binance_liquidations",
        "v2/legacy_owned_runtime/ingest/live_binance_liquidations.py",
        "19711590a3d194fd05ae3be85ef7bd6dec397f6394d02f7e91008c44c310131b",
        0,
    ),
    (
        "live_coinank",
        "v2/legacy_owned_runtime/ingest/live_coinank.py",
        "cd13dab55c0906c379e4116102c05f960908dd28d6b6e883ca76347cd1f144c8",
        0,
    ),
    (
        "live_coinank_global_aggregator",
        "v2/legacy_owned_runtime/ingest/live_coinank_global_aggregator.py",
        "1f85c4532e4829aa99ddadbd6a5cd2325ef9e5c4012208eb05876c1b0187eeae",
        0,
    ),
    (
        "live_kucoin",
        "v2/legacy_owned_runtime/ingest/live_kucoin.py",
        "73b852db1bf69062d4028091cf17c126f5cb666e94bf784cdb2bb9b47328a976",
        0,
    ),
    (
        "live_coinapi_v1",
        "v2/legacy_owned_runtime/ingest/live_coinapi_v1.py",
        "c8ca17d21b972510b92c4e84c477cd3440b3cfd1e2ec8e7411624a7454cee280",
        0,
    ),
    (
        "live_coinapi_wsds",
        "v2/legacy_owned_runtime/ingest/live_coinapi_wsds.py",
        "a6973d887d1c52a4bb48f3b6f222b04e97d92e500ab889e94d6026cf504471b6",
        0,
    ),
    (
        "live_technical_analysis",
        "v2/legacy_owned_runtime/ingest/live_technical_analysis.py",
        "5cdd4ea1d43271d0199e1ca92ecad3a8b76308838898a611df6ef4602f7388ac",
        0,
    ),
    (
        "realtime_price_provider",
        "v2/legacy_owned_runtime/ingest/realtime_price_provider.py",
        "dfdc2568368c134b9afcc4fa0faff312cc93a6ecc501ecaac747e7c20d7344ba",
        0,
    ),
    (
        "liquidation_bridge",
        "v2/legacy_owned_runtime/ingest/liquidation_bridge.py",
        "5d70e395938228b61162b531310cd751403ddfeebb8920429e73cdcdbe35d48a",
        0,
    ),
    (
        "liquidation_levels_engine",
        "v2/legacy_owned_runtime/ingest/liquidation_levels_engine.py",
        "fed3c90b5193c27d24dc183089730bda49ff69a1758b597e23a154397f839df7",
        0,
    ),
    (
        "ccxt_historical",
        "v2/legacy_owned_runtime/ingest/ccxt_historical.py",
        "7d021ca95e57f10b5ac458753d921f77c2349569125e2e968772143c4baec1e3",
        0,
    ),
)


def _has_env(name: str) -> bool:
    """Vault-aware key-name presence check.

    Returns True if ``name`` is in os.environ OR in the redacted local
    secret vault (NAMES only; no values are read or returned).
    """
    try:
        from .secret_decision import key_name_available
    except Exception:
        return bool(os.environ.get(name))
    return key_name_available(name)


def _classify(name: str) -> IngestorClassification:
    if name == "live_binance":
        return IngestorClassification(
            classification=CLASS_NATIVE_V2_READONLY_PUBLIC_DATA,
            rationale=(
                "Binance public market data (OHLCV, depth, mark price, "
                "funding) consumed by V2 native v2_market_ingestor "
                "through public REST/WSS endpoints. No API key required. "
                "Closed for paper-only shutdown as native public-data."
            ),
            requires_secret_env=(),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/v2_market_ingestor/",
            rate_limit_concern_notes="binance_public_weight_1200_per_minute_safe_for_v2_paper_loop",
        )
    if name == "live_binance_liquidations":
        return IngestorClassification(
            classification=CLASS_NATIVE_V2_READONLY_PUBLIC_DATA,
            rationale=(
                "Binance liquidations consumed by V2 native WSS runtime from "
                "routed public WSS market !forceOrder stream; no secret required. "
                "Closed for paper-only shutdown as native public-data."
            ),
            requires_secret_env=(),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/v2_market_ingestor/",
            rate_limit_concern_notes="wss_no_documented_rate_limit_for_forceOrder_stream",
        )
    if name == "live_coinank":
        has_key = _has_env("COINANK_API_KEY")
        return IngestorClassification(
            classification=CLASS_NATIVE_V2_READONLY_PUBLIC_DATA
            if has_key
            else CLASS_BLOCKED_BY_SECRET_OR_API,
            rationale=(
                "CoinAnk REST requires an API key. With COINANK_API_KEY "
                "present, the V2 paper stack classifies CoinAnk as native "
                "read-only public-data consumption through V2-owned runtime "
                "surfaces. Without the key, classification is "
                "BLOCKED_BY_SECRET_OR_API."
            ),
            requires_secret_env=("COINANK_API_KEY",),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/coinank_market_intelligence/",
            rate_limit_concern_notes="coinank_per_minute_quotas_apply_use_v2_throttle",
        )
    if name == "live_coinank_global_aggregator":
        has_key = _has_env("COINANK_API_KEY")
        return IngestorClassification(
            classification=CLASS_NATIVE_V2_READONLY_PUBLIC_DATA
            if has_key
            else CLASS_BLOCKED_BY_SECRET_OR_API,
            rationale=(
                "CoinAnk/global market-intelligence aggregation remains "
                "read-only market data. With COINANK_API_KEY present it is "
                "classified as native V2 read-only public data; otherwise it "
                "is BLOCKED_BY_SECRET_OR_API."
            ),
            requires_secret_env=("COINANK_API_KEY",),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/coinank_market_intelligence/",
            rate_limit_concern_notes="aggregator_amplifies_coinank_rate_pressure",
        )
    if name == "live_kucoin":
        return IngestorClassification(
            classification=CLASS_NATIVE_V2,
            rationale=(
                "KuCoin public-data ingestor implemented natively in V2 "
                "via v2_kucoin_ingestor_worker (public REST + WSS, no "
                "API key required). Spot ticker, klines, orderbook20, "
                "and futures funding/OI/mark configuration emitted with "
                "deterministic V2 symbol mapping and reconnect backoff."
            ),
            requires_secret_env=(),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/v2_kucoin_ingestor/",
            rate_limit_concern_notes="kucoin_public_endpoints_low_pressure",
        )
    if name == "live_coinapi_v1":
        has_key = _has_env("COINAPI_KEY") or _has_env("COINAPI_API_KEY")
        return IngestorClassification(
            classification=CLASS_NATIVE_V2_READONLY_PUBLIC_DATA
            if has_key
            else CLASS_BLOCKED_BY_SECRET_OR_API,
            rationale=(
                "CoinAPI v1 requires X-CoinAPI-Key (COINAPI_API_KEY or "
                "COINAPI_KEY). With the key present, V2 may consume "
                "free-tier read-only market data. Without the key it is "
                "BLOCKED_BY_SECRET_OR_API."
            ),
            requires_secret_env=("COINAPI_API_KEY",),
            public_market_data_only=True,
            v2_namespace_payload_path=None,
            rate_limit_concern_notes="coinapi_free_tier_strict_daily_quota",
        )
    if name == "live_coinapi_wsds":
        has_key = _has_env("COINAPI_KEY") or _has_env("COINAPI_API_KEY")
        return IngestorClassification(
            classification=CLASS_OPERATOR_DECISION_REQUIRED_FOR_PAPER_ONLY_SHUTDOWN
            if has_key
            else CLASS_BLOCKED_BY_SECRET_OR_API,
            rationale=(
                "CoinAPI WSDS is a paid/keyed read-only streaming source. "
                "The V2 worker is native and V2-only, but it must stay "
                "operator-decision-gated even when the key name is present. "
                "Enable only through V2_COINAPI_WSDS_OPT_IN=true; otherwise "
                "CoinAPI REST/OHLCV remains the fallback."
            ),
            requires_secret_env=("COINAPI_API_KEY",),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/v2_coinapi_wsds/",
            rate_limit_concern_notes="coinapi_wsds_paid_streaming_operator_opt_in_required",
        )
    if name == "live_technical_analysis":
        return IngestorClassification(
            classification=CLASS_NATIVE_V2,
            rationale=(
                "Technical analysis pipeline is fully native in V2 via "
                "v2_feature_pipeline_and_ta_worker + "
                "v2_feature_pipeline_native_trainer_snapshot. No legacy "
                "dependency."
            ),
            requires_secret_env=(),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/v2_feature_pipeline_and_ta_worker/",
            rate_limit_concern_notes="local_computation_no_rate_limit",
        )
    if name == "realtime_price_provider":
        return IngestorClassification(
            classification=CLASS_NATIVE_V2,
            rationale=(
                "Realtime price layer is served by v2_market_ingestor in "
                "V2 with native OHLCV cache."
            ),
            requires_secret_env=(),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/v2_market_ingestor/",
            rate_limit_concern_notes="binance_public_endpoints_safe",
        )
    if name == "liquidation_bridge":
        return IngestorClassification(
            classification=CLASS_MISSING_IN_V2,
            rationale=(
                "The current V2 runtime does not run a liquidation ingestor bridge. "
                "Liquidation WSS and levels are handled by direct V2 runtime services. "
                "This preserved legacy bridge role remains disabled unless the "
                "operator explicitly asks to run that legacy script as-is."
            ),
            requires_secret_env=(),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/coinank_market_intelligence/",
            rate_limit_concern_notes="bridge_pulls_existing_streams_no_extra_rate_pressure",
        )
    if name == "liquidation_levels_engine":
        return IngestorClassification(
            classification=CLASS_NATIVE_V2,
            rationale=(
                "Liquidation levels are computed natively in V2 against "
                "the V2 OHLCV cache. No legacy import."
            ),
            requires_secret_env=(),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/v2_market_ingestor/",
            rate_limit_concern_notes="local_computation_only",
        )
    if name == "ccxt_historical":
        return IngestorClassification(
            classification=CLASS_NATIVE_V2_READONLY_PUBLIC_DATA,
            rationale=(
                "Legacy CCXT historical/backfill was a secondary historical "
                "source. V2 training/live-like paper inputs are now covered "
                "by native Binance USDM multi-timeframe OHLCV, CoinAPI OHLCV "
                "fallback keys, and the local replay store. No CCXT legacy "
                "process or adapter is required for the active V2 ingestor "
                "plane."
            ),
            requires_secret_env=(),
            public_market_data_only=True,
            v2_namespace_payload_path="v2/frontend/public/operator_runtime/v2_market_ingestor/",
            rate_limit_concern_notes="ccxt_not_started_active_v2_uses_exchange_specific_public_ingestors",
        )
    return IngestorClassification(
        classification=CLASS_OPERATOR_DECISION_REQUIRED,
        rationale="No classifier branch matched the ingestor name.",
        requires_secret_env=(),
        public_market_data_only=True,
        v2_namespace_payload_path=None,
        rate_limit_concern_notes="",
    )


def classify_all_ingestors() -> tuple[IngestorRecord, ...]:
    out: list[IngestorRecord] = []
    for name, path, sha, size_hint in INGESTOR_REGISTRY:
        try:
            from pathlib import Path
            real_size = Path(path).stat().st_size
        except OSError:
            real_size = int(size_hint)
        out.append(
            IngestorRecord(
                name=name,
                legacy_path=path,
                legacy_sha256=sha,
                legacy_size_bytes=int(real_size),
                classification=_classify(name),
            )
        )
    return tuple(out)


def ingestors_invariants_snapshot() -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    return {
        "imports_torch": False,
        "imports_numpy": False,
        "imports_redis": False,
        "imports_exchange_sdk": False,
        "performs_network_io": False,
        "writes_legacy_redis": False,
        "places_exchange_orders": False,
        "public_market_data_only": True,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "allowed_classifications": list(ALL_CLASSIFICATIONS),
        "generated_utc": now,
    }
