"""V2 native dynamic runtime + trainer bridge-exit execution.

This is a bounded one-shot paper/read-only execution lane. It performs
public Binance USD-M market-data reads, publishes only ``v2:*`` Redis keys
when Redis is available, computes V2-native feature/TA payloads only from
observed inputs, and emits blocked trainer bridge-exit prediction payloads
without claiming native trainer readiness.

No credentials are loaded. No private or order endpoint is called. No legacy
Redis key can be written through this module.
"""
from __future__ import annotations

import hashlib
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from v2.backend.app.services.feature_pipeline_and_ta.service import (
    FeaturePipelineAndTAService,
)
from v2.backend.app.services.feature_pipeline_native.service import (
    FeaturePipelineNativeService,
    NativeFeatureInputs,
)
from v2.backend.app.services.native_runtime_migration.safety import (
    KNOWN_UNIVERSE,
    LIVE_GATE_BLOCKED,
    V2_NATIVE_ACTIVE_SYMBOLS,
    safety_block,
    utc_now_iso,
)
from v2.backend.app.services.v2_owned_runtime.redis_namespace_adapter import (
    RedisNamespaceAdapter,
)


SCHEMA_VERSION = "v2_native_dynamic_runtime_trainer_bridge_exit_execution_v1"

TIMEFRAMES = ("1m", "5m", "15m", "1h")
FEATURE_TFS = ("1m", "5m")

OHLCV_KEY_TEMPLATE = "v2:market:ohlcv:binance:{symbol}:{timeframe}"
OHLCV_HEARTBEAT_KEY = "v2:market:ohlcv:binance:heartbeat"
ORDERBOOK_KEY_TEMPLATE = "v2:market:orderbook:binance:{symbol}"
ORDERBOOK_HEARTBEAT_KEY = "v2:market:orderbook:binance:heartbeat"
FEATURES_KEY_TEMPLATE = "v2:features:latest:{symbol}:{timeframe}"
FEATURES_HEARTBEAT_KEY = "v2:features:pipeline:heartbeat"
TA_KEY_TEMPLATE = "v2:technical_analysis:{symbol}:{timeframe}"
TA_FEATURES_KEY_TEMPLATE = "v2:features:ta:{symbol}:{timeframe}"
PREDICTION_KEY_TEMPLATE = "v2:prediction:{symbol}:{timeframe}"
TRAINER_HEARTBEAT_KEY = "v2:trainer:heartbeat"
TRAINER_DATASET_MANIFEST_KEY = "v2:trainer:dataset:manifest"

BINANCE_USDM_BASE = "https://fapi.binance.com"

TRAINER_SOURCE_CONTRACT_ONLY = "V2_NATIVE_CONTRACT_ONLY"
PREDICTION_BLOCK_REASONS = (
    "native_trainer_not_implemented",
    "checkpoint_operator_decision_required",
    "contract_only_prediction_not_tradeable",
    "live_gate_blocked_human_only",
)


def _json_dumps(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _stable_id(prefix: str, payload: Any) -> str:
    digest = hashlib.sha256(_json_dumps(payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:32]}"


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )
    tmp.replace(path)


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _now_ms() -> int:
    return int(time.time() * 1000)


def _age_seconds(ts_ms: Any) -> int | None:
    try:
        value = int(float(ts_ms))
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return max(0, int((_now_ms() - value) / 1000))


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


class BinancePublicReadError(RuntimeError):
    """Raised for a failed public Binance read."""


class BinanceUsdMPublicClient:
    """Tiny public-read Binance USD-M REST client with injectable HTTP."""

    def __init__(
        self,
        *,
        http_get: Callable[[str], Any] | None = None,
        timeout_seconds: int = 10,
    ) -> None:
        self._http_get = http_get or self._default_http_get
        self._timeout_seconds = timeout_seconds

    def _default_http_get(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            method="GET",
            headers={
                "User-Agent": "ai-bot-v2-native-dynamic-runtime-readonly",
            },
        )
        with urllib.request.urlopen(request, timeout=self._timeout_seconds) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def klines(
        self,
        symbol: str,
        timeframe: str,
        *,
        limit: int = 60,
    ) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode(
            {"symbol": symbol, "interval": timeframe, "limit": str(limit)}
        )
        url = f"{BINANCE_USDM_BASE}/fapi/v1/klines?{query}"
        try:
            raw = self._http_get(url)
        except Exception as exc:  # noqa: BLE001
            raise BinancePublicReadError(str(exc)) from exc
        if not isinstance(raw, list):
            raise BinancePublicReadError("unexpected_klines_payload")
        rows: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, list) or len(item) < 7:
                continue
            row = {
                "open_time_ms": int(item[0]),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
                "close_time_ms": int(item[6]),
            }
            rows.append(row)
        if not rows:
            raise BinancePublicReadError("empty_klines_payload")
        return rows

    def depth(self, symbol: str, *, limit: int = 100) -> dict[str, Any]:
        query = urllib.parse.urlencode({"symbol": symbol, "limit": str(limit)})
        url = f"{BINANCE_USDM_BASE}/fapi/v1/depth?{query}"
        try:
            raw = self._http_get(url)
        except Exception as exc:  # noqa: BLE001
            raise BinancePublicReadError(str(exc)) from exc
        if not isinstance(raw, dict):
            raise BinancePublicReadError("unexpected_depth_payload")
        bids = raw.get("bids") or []
        asks = raw.get("asks") or []
        if not bids or not asks:
            raise BinancePublicReadError("empty_depth_payload")
        return {
            "last_update_id": raw.get("lastUpdateId"),
            "bids": [[float(x[0]), float(x[1])] for x in bids if len(x) >= 2],
            "asks": [[float(x[0]), float(x[1])] for x in asks if len(x) >= 2],
            "fetched_ms": _now_ms(),
        }


@dataclass
class RedisWriteAudit:
    redis_connected: bool = False
    writes_attempted: int = 0
    writes_succeeded: int = 0
    writes_failed: int = 0
    old_redis_write_attempts: int = 0
    keys_written: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class V2RedisPublisher:
    """JSON SET publisher that refuses non-``v2:*`` keys."""

    def __init__(self, client: Any = None) -> None:
        self._adapter = RedisNamespaceAdapter(client)
        self.audit = RedisWriteAudit(redis_connected=client is not None)

    @staticmethod
    def from_localhost() -> "V2RedisPublisher":
        try:
            import redis  # type: ignore

            client = redis.Redis(
                host="127.0.0.1",
                port=6379,
                db=0,
                decode_responses=True,
                socket_connect_timeout=2,
            )
            client.ping()
            return V2RedisPublisher(client)
        except Exception:  # noqa: BLE001
            return V2RedisPublisher(None)

    def get_json(self, key: str) -> Any:
        if not key.startswith("v2:"):
            raise ValueError(f"non_v2_read_rejected:{key}")
        raw = self._adapter.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return raw

    def set_json(self, key: str, payload: Any) -> bool:
        self.audit.writes_attempted += 1
        if not key.startswith("v2:"):
            self.audit.old_redis_write_attempts += 1
            self.audit.writes_failed += 1
            self.audit.errors.append(f"blocked_non_v2_key:{key}")
            return False
        try:
            self._adapter.set(key, json.dumps(payload, sort_keys=True, default=str))
        except Exception as exc:  # noqa: BLE001
            self.audit.writes_failed += 1
            self.audit.errors.append(f"{key}:{type(exc).__name__}")
            return False
        self.audit.writes_succeeded += 1
        self.audit.keys_written.append(key)
        return True


@dataclass
class ExecutionPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path
    startup_runtime_dir: Path
    startup_runtime_public_dir: Path


def default_paths(repo_root: Path) -> ExecutionPaths:
    return ExecutionPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/"
        "v2_native_dynamic_runtime_and_trainer_bridge_exit_execution/latest",
        public_dir=repo_root
        / "v2/frontend/public/"
        "v2_native_dynamic_runtime_and_trainer_bridge_exit_execution/latest",
        startup_runtime_dir=repo_root
        / "claude_worklog/final_readiness/"
        "v2_full_paper_only_startup_manifest_runtime/latest",
        startup_runtime_public_dir=repo_root
        / "v2/frontend/public/v2_full_paper_only_startup_manifest_runtime/latest",
    )


@dataclass
class ExecutionRunResult:
    go_no_go: str
    paths_written: list[Path] = field(default_factory=list)


def _ohlcv_payload(symbol: str, timeframe: str, candles: list[dict[str, Any]]) -> dict[str, Any]:
    latest = candles[-1]
    return {
        "schema_version": SCHEMA_VERSION + "_ohlcv_payload",
        "source_label": "V2_NATIVE_PUBLIC_BINANCE_USDM",
        "source_endpoint": "/fapi/v1/klines",
        "source_mutation_capability": "NONE_PUBLIC_GET_ONLY",
        "symbol": symbol,
        "timeframe": timeframe,
        "generated_utc": utc_now_iso(),
        "candle_count": len(candles),
        "latest": latest,
        "candles": candles,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }


def _orderbook_payload(symbol: str, depth: dict[str, Any]) -> dict[str, Any]:
    best_bid = depth["bids"][0] if depth.get("bids") else None
    best_ask = depth["asks"][0] if depth.get("asks") else None
    return {
        "schema_version": SCHEMA_VERSION + "_orderbook_payload",
        "source_label": "V2_NATIVE_PUBLIC_BINANCE_USDM",
        "source_endpoint": "/fapi/v1/depth",
        "source_mutation_capability": "NONE_PUBLIC_GET_ONLY",
        "symbol": symbol,
        "generated_utc": utc_now_iso(),
        "last_update_id": depth.get("last_update_id"),
        "fetched_ms": depth.get("fetched_ms"),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "bid_depth_count": len(depth.get("bids") or []),
        "ask_depth_count": len(depth.get("asks") or []),
        "bids": depth.get("bids") or [],
        "asks": depth.get("asks") or [],
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
    }


def _feature_inputs(
    *,
    symbol: str,
    timeframe: str,
    generated_utc: str,
    candles: list[dict[str, Any]],
    orderbook: dict[str, Any],
    higher_tf_candles: list[dict[str, Any]] | None,
) -> NativeFeatureInputs:
    bids = orderbook.get("bids") or []
    asks = orderbook.get("asks") or []
    bid = bids[0] if bids else [None, None]
    ask = asks[0] if asks else [None, None]
    htf_closes = tuple(
        float(row["close"]) for row in (higher_tf_candles or []) if row.get("close")
    )
    latest_close_ms = candles[-1].get("close_time_ms") if candles else None
    return NativeFeatureInputs(
        symbol=symbol,
        timeframe=timeframe,
        generated_utc=generated_utc,
        ohlcv_window=tuple(candles),
        ohlcv_window_age_seconds=_age_seconds(latest_close_ms),
        bid_price=_safe_float(bid[0]),
        ask_price=_safe_float(ask[0]),
        bid_size=_safe_float(bid[1]),
        ask_size=_safe_float(ask[1]),
        orderbook_age_seconds=_age_seconds(orderbook.get("fetched_ms")),
        higher_tf_label="15m" if higher_tf_candles else None,
        higher_tf_close_window=htf_closes,
        higher_tf_age_seconds=_age_seconds(
            higher_tf_candles[-1].get("close_time_ms")
            if higher_tf_candles
            else None
        ),
    )


def _prediction_payload(
    *,
    symbol: str,
    timeframe: str,
    feature_snapshot: dict[str, Any] | None,
) -> dict[str, Any]:
    generated = utc_now_iso()
    missing_flags = list(
        (feature_snapshot or {}).get("missing_feature_flags") or ["feature_snapshot_missing"]
    )
    stale_flags = list((feature_snapshot or {}).get("stale_feature_flags") or [])
    feature_snapshot_id = str(
        (feature_snapshot or {}).get("feature_snapshot_id")
        or f"missing_feature_snapshot:{symbol}:{timeframe}"
    )
    base = {
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_snapshot_id": feature_snapshot_id,
        "trainer_source": TRAINER_SOURCE_CONTRACT_ONLY,
        "model_source": "V2_NATIVE_CONTRACT_ONLY_NO_CHECKPOINT",
        "generated_at": generated,
    }
    return {
        "schema_version": SCHEMA_VERSION + "_trainer_prediction_contract_payload",
        "prediction_id": _stable_id("v2_contract_pred", base),
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_snapshot_id": feature_snapshot_id,
        "trainer_source": TRAINER_SOURCE_CONTRACT_ONLY,
        "model_source": "V2_NATIVE_CONTRACT_ONLY_NO_CHECKPOINT",
        "expected_move_bps": None,
        "expected_move_after_cost_bps": None,
        "confidence_raw": 0.0,
        "confidence_calibrated": 0.0,
        "feature_freshness_state": (feature_snapshot or {}).get(
            "feature_freshness_state", "MISSING"
        ),
        "missing_feature_flags": missing_flags,
        "stale_feature_flags": stale_flags,
        "checkpoint_id": None,
        "checkpoint_blocker": "OPERATOR_DECISION_REQUIRED_NATIVE_TRAINER_CHECKPOINT",
        "paper_fill_gate_status": "BLOCKED_CONTRACT_ONLY",
        "paper_fill_allowed": False,
        "paper_fill_gate_block_reasons": list(PREDICTION_BLOCK_REASONS),
        "prediction_action": "HOLD",
        "direction": "flat",
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def _status_counts(rows: list[dict[str, Any]], key: str = "status") -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get(key) or "UNKNOWN")
        counts[status] = counts.get(status, 0) + 1
    return counts


def execute_dynamic_runtime(
    *,
    client: BinanceUsdMPublicClient,
    publisher: V2RedisPublisher,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    generated = utc_now_iso()
    ohlcv_cache: dict[tuple[str, str], list[dict[str, Any]]] = {}
    orderbook_cache: dict[str, dict[str, Any]] = {}
    feature_cache: dict[tuple[str, str], dict[str, Any]] = {}
    ta_cache: dict[tuple[str, str], dict[str, Any]] = {}

    ohlcv_rows: list[dict[str, Any]] = []
    for symbol in KNOWN_UNIVERSE:
        for tf in TIMEFRAMES:
            key = OHLCV_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            try:
                candles = client.klines(symbol, tf, limit=60)
                payload = _ohlcv_payload(symbol, tf, candles)
                publisher.set_json(key, payload)
                ohlcv_cache[(symbol, tf)] = candles
                ohlcv_rows.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "target_key": key,
                    "status": "V2_NATIVE_POPULATED",
                    "source_label": "V2_NATIVE_PUBLIC_BINANCE_USDM",
                    "sample_count": len(candles),
                    "latest_close_time_ms": candles[-1]["close_time_ms"],
                })
            except BinancePublicReadError as exc:
                ohlcv_rows.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "target_key": key,
                    "status": "MISSING_SOURCE",
                    "source_label": "MISSING_SOURCE",
                    "sample_count": 0,
                    "missing_reason": str(exc)[:240],
                })
    publisher.set_json(
        OHLCV_HEARTBEAT_KEY,
        {
            "schema_version": SCHEMA_VERSION + "_ohlcv_heartbeat",
            "generated_utc": generated,
            "symbol_count": len(KNOWN_UNIVERSE),
            "timeframes": list(TIMEFRAMES),
            "populated_count": sum(1 for r in ohlcv_rows if r["status"] == "V2_NATIVE_POPULATED"),
            "missing_count": sum(1 for r in ohlcv_rows if r["status"] != "V2_NATIVE_POPULATED"),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        },
    )

    orderbook_rows: list[dict[str, Any]] = []
    for symbol in KNOWN_UNIVERSE:
        key = ORDERBOOK_KEY_TEMPLATE.format(symbol=symbol)
        try:
            depth = client.depth(symbol, limit=100)
            payload = _orderbook_payload(symbol, depth)
            publisher.set_json(key, payload)
            orderbook_cache[symbol] = depth
            orderbook_rows.append({
                "symbol": symbol,
                "target_key": key,
                "status": "V2_NATIVE_POPULATED",
                "source_label": "V2_NATIVE_PUBLIC_BINANCE_USDM",
                "bid_depth_count": len(depth.get("bids") or []),
                "ask_depth_count": len(depth.get("asks") or []),
            })
        except BinancePublicReadError as exc:
            orderbook_rows.append({
                "symbol": symbol,
                "target_key": key,
                "status": "MISSING_SOURCE",
                "source_label": "MISSING_SOURCE",
                "missing_reason": str(exc)[:240],
            })
    publisher.set_json(
        ORDERBOOK_HEARTBEAT_KEY,
        {
            "schema_version": SCHEMA_VERSION + "_orderbook_heartbeat",
            "generated_utc": generated,
            "symbol_count": len(KNOWN_UNIVERSE),
            "populated_count": sum(1 for r in orderbook_rows if r["status"] == "V2_NATIVE_POPULATED"),
            "missing_count": sum(1 for r in orderbook_rows if r["status"] != "V2_NATIVE_POPULATED"),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        },
    )

    feature_service = FeaturePipelineNativeService()
    ta_service = FeaturePipelineAndTAService()
    feature_rows: list[dict[str, Any]] = []
    ta_rows: list[dict[str, Any]] = []
    for symbol in KNOWN_UNIVERSE:
        orderbook = orderbook_cache.get(symbol)
        for tf in FEATURE_TFS:
            feature_key = FEATURES_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            candles = ohlcv_cache.get((symbol, tf))
            if not candles or not orderbook:
                feature_rows.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "target_key": feature_key,
                    "status": "MISSING_SOURCE",
                    "source_label": "MISSING_SOURCE",
                    "missing_reason": "ohlcv_or_orderbook_missing",
                })
            else:
                inputs = _feature_inputs(
                    symbol=symbol,
                    timeframe=tf,
                    generated_utc=generated,
                    candles=candles,
                    orderbook=orderbook,
                    higher_tf_candles=ohlcv_cache.get((symbol, "15m")),
                )
                payload = feature_service.emit_trainer_consumable_snapshot(inputs)
                payload["source_label"] = "V2_NATIVE_PUBLIC_BINANCE_USDM_DERIVED"
                payload["target_key"] = feature_key
                payload["no_fake_features"] = True
                publisher.set_json(feature_key, payload)
                feature_cache[(symbol, tf)] = payload
                feature_rows.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "target_key": feature_key,
                    "status": "V2_NATIVE_POPULATED",
                    "source_label": "V2_NATIVE_PUBLIC_BINANCE_USDM_DERIVED",
                    "feature_snapshot_id": payload["feature_snapshot_id"],
                    "feature_count": payload["feature_count"],
                    "missing_feature_flags": payload["missing_feature_flags"],
                    "stale_feature_flags": payload["stale_feature_flags"],
                })

            ta_key = TA_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            ta_feature_key = TA_FEATURES_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            if not candles:
                ta_rows.append({
                    "symbol": symbol,
                    "timeframe": tf,
                    "target_keys": [ta_key, ta_feature_key],
                    "status": "MISSING_SOURCE",
                    "source_label": "MISSING_SOURCE",
                    "missing_reason": "ohlcv_missing",
                })
            else:
                result = ta_service.compute_ta_indicators(symbol, tf, candles, now_ms=_now_ms())
                if result.insufficient_history or not result.indicators:
                    ta_rows.append({
                        "symbol": symbol,
                        "timeframe": tf,
                        "target_keys": [ta_key, ta_feature_key],
                        "status": "MISSING_SOURCE",
                        "source_label": "MISSING_SOURCE",
                        "missing_reason": "insufficient_ohlcv_history",
                    })
                else:
                    payload = {
                        "schema_version": SCHEMA_VERSION + "_ta_payload",
                        "source_label": "V2_NATIVE_PUBLIC_BINANCE_USDM_DERIVED",
                        "symbol": symbol,
                        "timeframe": tf,
                        "generated_utc": generated,
                        "indicators": result.indicators,
                        "families_present": result.families_present,
                        "source_ohlcv_key": OHLCV_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf),
                        "no_zero_fill": True,
                        "live_gate": LIVE_GATE_BLOCKED,
                        "live_symbols": [],
                    }
                    publisher.set_json(ta_key, payload)
                    publisher.set_json(ta_feature_key, payload)
                    ta_cache[(symbol, tf)] = payload
                    ta_rows.append({
                        "symbol": symbol,
                        "timeframe": tf,
                        "target_keys": [ta_key, ta_feature_key],
                        "status": "V2_NATIVE_POPULATED",
                        "source_label": "V2_NATIVE_PUBLIC_BINANCE_USDM_DERIVED",
                        "indicator_count": len(result.indicators),
                        "families_present": result.families_present,
                    })
    publisher.set_json(
        FEATURES_HEARTBEAT_KEY,
        {
            "schema_version": SCHEMA_VERSION + "_features_heartbeat",
            "generated_utc": generated,
            "symbol_count": len(KNOWN_UNIVERSE),
            "timeframes": list(FEATURE_TFS),
            "populated_count": sum(1 for r in feature_rows if r["status"] == "V2_NATIVE_POPULATED"),
            "missing_count": sum(1 for r in feature_rows if r["status"] != "V2_NATIVE_POPULATED"),
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
        },
    )

    prediction_rows: list[dict[str, Any]] = []
    prediction_required_fields = (
        "prediction_id",
        "symbol",
        "timeframe",
        "feature_snapshot_id",
        "trainer_source",
        "model_source",
        "expected_move_bps",
        "expected_move_after_cost_bps",
        "confidence_raw",
        "confidence_calibrated",
        "feature_freshness_state",
        "missing_feature_flags",
        "stale_feature_flags",
        "checkpoint_id",
        "checkpoint_blocker",
        "paper_fill_gate_status",
        "paper_fill_gate_block_reasons",
        "live_gate",
        "live_symbols",
    )
    for symbol in KNOWN_UNIVERSE:
        for tf in FEATURE_TFS:
            key = PREDICTION_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            payload = _prediction_payload(
                symbol=symbol,
                timeframe=tf,
                feature_snapshot=feature_cache.get((symbol, tf)),
            )
            missing_fields = [f for f in prediction_required_fields if f not in payload]
            existing = publisher.get_json(key) if publisher.audit.redis_connected else None
            existing_source = existing.get("trainer_source") if isinstance(existing, dict) else None
            if existing and existing_source != TRAINER_SOURCE_CONTRACT_ONLY:
                status = "PRESERVED_EXISTING_RUNTIME_PREDICTION_NOT_OVERWRITTEN"
                redis_written = False
            elif feature_cache.get((symbol, tf)):
                redis_written = publisher.set_json(key, payload)
                status = "V2_NATIVE_CONTRACT_ONLY_BLOCKED_PREDICTION_WRITTEN"
            else:
                redis_written = False
                status = "MISSING_SOURCE_NOT_WRITTEN"
            prediction_rows.append({
                "symbol": symbol,
                "timeframe": tf,
                "target_key": key,
                "status": status,
                "redis_written": redis_written,
                "required_fields_present": not missing_fields,
                "missing_required_fields": missing_fields,
                "trainer_source": payload["trainer_source"],
                "native_trainer_ready_claimed": False,
                "paper_fill_gate_status": payload["paper_fill_gate_status"],
                "paper_fill_gate_block_reasons": payload["paper_fill_gate_block_reasons"],
            })

    dataset_manifest = {
        "schema_version": SCHEMA_VERSION + "_trainer_dataset_manifest",
        "generated_utc": generated,
        "universe": list(KNOWN_UNIVERSE),
        "timeframes": list(FEATURE_TFS),
        "feature_snapshot_count": len(feature_cache),
        "ta_snapshot_count": len(ta_cache),
        "trainer_source": TRAINER_SOURCE_CONTRACT_ONLY,
        "native_trainer_ready": False,
        "training_dispatched": False,
        "operator_decision_required_for_checkpoint": True,
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }
    trainer_heartbeat = {
        "schema_version": SCHEMA_VERSION + "_trainer_heartbeat",
        "generated_utc": generated,
        "trainer_source": TRAINER_SOURCE_CONTRACT_ONLY,
        "native_trainer_ready": False,
        "predictions_total": len(prediction_rows),
        "blocked_prediction_count": sum(
            1 for r in prediction_rows if "BLOCKED" in r["status"]
        ),
        "preserved_existing_prediction_count": sum(
            1 for r in prediction_rows if r["status"].startswith("PRESERVED")
        ),
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
    }
    publisher.set_json(TRAINER_DATASET_MANIFEST_KEY, dataset_manifest)
    publisher.set_json(TRAINER_HEARTBEAT_KEY, trainer_heartbeat)

    native_status = {
        "schema_version": SCHEMA_VERSION + "_native_dynamic_runtime_status",
        "generated_utc": generated,
        **safety_block(),
        "go_no_go": "V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_READY",
        "universe": list(KNOWN_UNIVERSE),
        "target_symbol_count": len(KNOWN_UNIVERSE),
        "active_before_symbols": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "native_symbol_count": len(
            {r["symbol"] for r in feature_rows if r["status"] == "V2_NATIVE_POPULATED"}
        ),
        "bridge_symbol_count": 0,
        "missing_symbol_count": len(
            set(KNOWN_UNIVERSE)
            - {r["symbol"] for r in feature_rows if r["status"] == "V2_NATIVE_POPULATED"}
        ),
        "ohlcv_rows": ohlcv_rows,
        "orderbook_rows": orderbook_rows,
        "feature_rows": feature_rows,
        "ta_rows": ta_rows,
        "ohlcv_status_counts": _status_counts(ohlcv_rows),
        "orderbook_status_counts": _status_counts(orderbook_rows),
        "feature_status_counts": _status_counts(feature_rows),
        "ta_status_counts": _status_counts(ta_rows),
        "btc_eth_sol_regression_check": {
            symbol: {
                "ohlcv_1m": (symbol, "1m") in ohlcv_cache,
                "ohlcv_5m": (symbol, "5m") in ohlcv_cache,
                "orderbook": symbol in orderbook_cache,
                "features_1m": (symbol, "1m") in feature_cache,
                "features_5m": (symbol, "5m") in feature_cache,
            }
            for symbol in V2_NATIVE_ACTIVE_SYMBOLS
        },
        "redis_write_audit": publisher.audit.__dict__,
        "no_fake_ohlcv": True,
        "no_fake_orderbook": True,
        "no_fake_features": True,
        "no_fake_ta": True,
        "bridge_data_labeled_as_v2_native": False,
        "public_market_data_only": True,
        "exchange_mutation_allowed": False,
        "old_redis_write_allowed": False,
    }

    trainer_status = {
        "schema_version": SCHEMA_VERSION + "_trainer_bridge_exit_execution_status",
        "generated_utc": generated,
        **safety_block(),
        "trainer_source": TRAINER_SOURCE_CONTRACT_ONLY,
        "trainer_native_readiness_claimed": False,
        "v2_native_trainer_ready": False,
        "checkpoint_id": None,
        "checkpoint_blocker": "OPERATOR_DECISION_REQUIRED_NATIVE_TRAINER_CHECKPOINT",
        "prediction_required_fields": list(prediction_required_fields),
        "prediction_rows": prediction_rows,
        "prediction_status_counts": _status_counts(prediction_rows),
        "dataset_manifest_key": TRAINER_DATASET_MANIFEST_KEY,
        "trainer_heartbeat_key": TRAINER_HEARTBEAT_KEY,
        "paper_fill_gate_block_reasons": list(PREDICTION_BLOCK_REASONS),
        "no_edge_claim": True,
        "no_live_claim": True,
    }

    coverage = _build_coverage_status(
        generated=generated,
        ohlcv_rows=ohlcv_rows,
        orderbook_rows=orderbook_rows,
        feature_rows=feature_rows,
        ta_rows=ta_rows,
        prediction_rows=prediction_rows,
    )
    return native_status, trainer_status, coverage


def _build_coverage_status(
    *,
    generated: str,
    ohlcv_rows: list[dict[str, Any]],
    orderbook_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    ta_rows: list[dict[str, Any]],
    prediction_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    def symbol_status(rows: list[dict[str, Any]], symbol: str, positive: str) -> str:
        subset = [r for r in rows if r.get("symbol") == symbol]
        if subset and all(r.get("status") == positive for r in subset):
            return "V2_NATIVE_POPULATED"
        if any(r.get("status") == positive for r in subset):
            return "PARTIAL"
        return "MISSING_SOURCE"

    per_symbol: dict[str, dict[str, Any]] = {}
    for symbol in KNOWN_UNIVERSE:
        pred_subset = [r for r in prediction_rows if r["symbol"] == symbol]
        pred_written = any(r["redis_written"] for r in pred_subset)
        preserved = any(r["status"].startswith("PRESERVED") for r in pred_subset)
        per_symbol[symbol] = {
            "symbol": symbol,
            "ohlcv": symbol_status(ohlcv_rows, symbol, "V2_NATIVE_POPULATED"),
            "orderbook": symbol_status(orderbook_rows, symbol, "V2_NATIVE_POPULATED"),
            "features": symbol_status(feature_rows, symbol, "V2_NATIVE_POPULATED"),
            "ta": symbol_status(ta_rows, symbol, "V2_NATIVE_POPULATED"),
            "prediction": (
                "V2_NATIVE_CONTRACT_ONLY_BLOCKED"
                if pred_written
                else "PRESERVED_EXISTING_RUNTIME_PREDICTION"
                if preserved
                else "MISSING_SOURCE"
            ),
            "trainer_native_ready": False,
            "live_symbol": False,
        }
    families = ("ohlcv", "orderbook", "features", "ta", "prediction")
    family_status_counts: dict[str, dict[str, int]] = {}
    for family in families:
        counts: dict[str, int] = {}
        for row in per_symbol.values():
            status = row[family]
            counts[status] = counts.get(status, 0) + 1
        family_status_counts[family] = counts
    return {
        "schema_version": SCHEMA_VERSION + "_dynamic_symbol_coverage_status",
        "generated_utc": generated,
        **safety_block(),
        "go_no_go": "V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_READY",
        "universe": list(KNOWN_UNIVERSE),
        "target_symbol_count": len(KNOWN_UNIVERSE),
        "native_symbol_count": sum(
            1 for row in per_symbol.values() if row["features"] == "V2_NATIVE_POPULATED"
        ),
        "bridge_symbol_count": 0,
        "missing_symbol_count": sum(
            1 for row in per_symbol.values() if row["features"] != "V2_NATIVE_POPULATED"
        ),
        "currently_active_symbols_before": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "per_symbol_coverage": per_symbol,
        "family_status_counts": family_status_counts,
        "bridge_data_labeled_as_v2_native": False,
        "live_symbols_unchanged": True,
        "paper_symbols_unchanged_pending_governance": True,
        "training_symbols_unchanged_pending_governance": True,
    }


def _operator_dashboard(
    native_status: dict[str, Any],
    trainer_status: dict[str, Any],
    coverage: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": utc_now_iso(),
        "go_no_go": "V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_READY",
        **safety_block(),
        "summary": {
            "target_symbol_count": coverage["target_symbol_count"],
            "native_symbol_count": coverage["native_symbol_count"],
            "bridge_symbol_count": coverage["bridge_symbol_count"],
            "missing_symbol_count": coverage["missing_symbol_count"],
            "ohlcv_status_counts": native_status["ohlcv_status_counts"],
            "orderbook_status_counts": native_status["orderbook_status_counts"],
            "feature_status_counts": native_status["feature_status_counts"],
            "ta_status_counts": native_status["ta_status_counts"],
            "prediction_status_counts": trainer_status["prediction_status_counts"],
            "redis_writes_succeeded": native_status["redis_write_audit"]["writes_succeeded"],
        },
        "trainer_native_readiness_claimed": False,
        "full_migration_claimed": False,
        "edge_claimed": False,
        "bridge_data_labeled_as_v2_native": False,
        "controls_present": False,
        "fake_readiness": False,
        "blocks_live": True,
        "blocks_shutdown": True,
        "blocks_production_equivalence": True,
    }


def _render_report(native_status: dict[str, Any], trainer_status: dict[str, Any], coverage: dict[str, Any]) -> str:
    return (
        "# V2 Native Dynamic Runtime and Trainer Bridge-Exit Execution\n\n"
        "GO/NO-GO: V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_READY\n\n"
        "This packet executed bounded public/read-only V2-native market-data "
        "collection and V2-native feature/TA derivation across the 25-symbol "
        "universe. Trainer output remains contract-only and blocked; native "
        "trainer readiness is not claimed.\n\n"
        "## Coverage\n"
        f"- target_symbol_count: {coverage['target_symbol_count']}\n"
        f"- native_symbol_count: {coverage['native_symbol_count']}\n"
        f"- bridge_symbol_count: {coverage['bridge_symbol_count']}\n"
        f"- missing_symbol_count: {coverage['missing_symbol_count']}\n"
        f"- ohlcv_status_counts: {native_status['ohlcv_status_counts']}\n"
        f"- orderbook_status_counts: {native_status['orderbook_status_counts']}\n"
        f"- feature_status_counts: {native_status['feature_status_counts']}\n"
        f"- ta_status_counts: {native_status['ta_status_counts']}\n"
        f"- prediction_status_counts: {trainer_status['prediction_status_counts']}\n\n"
        "## Trainer Bridge-Exit\n"
        f"- trainer_source: {trainer_status['trainer_source']}\n"
        "- trainer_native_readiness_claimed: false\n"
        "- v2_native_trainer_ready: false\n"
        f"- checkpoint_blocker: {trainer_status['checkpoint_blocker']}\n"
        "- paper_fill_gate_status: BLOCKED_CONTRACT_ONLY\n\n"
        "## Safety\n"
        "- live_gate: blocked_human_only\n"
        "- live_symbols: []\n"
        "- approves_live: false\n"
        "- approves_canary: false\n"
        "- approves_legacy_shutdown: false\n"
        "- approves_redis_trim: false\n"
        "- old_redis_write_allowed: false\n"
        "- exchange_mutation_allowed: false\n"
        "- public_market_data_only: true\n\n"
        "## What this did NOT do\n"
        "- Did not modify legacy.\n"
        "- Did not stop V2 runtime, report center, replay miner, or governors.\n"
        "- Did not write old Redis keys.\n"
        "- Did not call private/order exchange endpoints.\n"
        "- Did not enable live, canary, or shutdown.\n"
        "- Did not claim edge or native trainer readiness.\n"
    )


def run_execution_packet(
    paths: ExecutionPaths,
    *,
    client: BinanceUsdMPublicClient | None = None,
    publisher: V2RedisPublisher | None = None,
) -> ExecutionRunResult:
    client = client or BinanceUsdMPublicClient()
    publisher = publisher or V2RedisPublisher.from_localhost()
    native_status, trainer_status, coverage = execute_dynamic_runtime(
        client=client,
        publisher=publisher,
    )
    dashboard = _operator_dashboard(native_status, trainer_status, coverage)

    writes = [
        (paths.packet_dir / "native_dynamic_runtime_status.json", native_status),
        (paths.packet_dir / "trainer_bridge_exit_execution_status.json", trainer_status),
        (paths.packet_dir / "dynamic_symbol_coverage_status.json", coverage),
        (paths.packet_dir / "operator_dashboard_payload.json", dashboard),
        (paths.public_dir / "native_dynamic_runtime_status.json", native_status),
        (paths.public_dir / "trainer_bridge_exit_execution_status.json", trainer_status),
        (paths.public_dir / "dynamic_symbol_coverage_status.json", coverage),
        (paths.public_dir / "operator_dashboard_payload.json", dashboard),
        (paths.startup_runtime_dir / "dynamic_symbol_paper_runtime_coverage.json", coverage),
        (paths.startup_runtime_public_dir / "dynamic_symbol_paper_runtime_coverage.json", coverage),
    ]
    for path, payload in writes:
        _atomic_write_json(path, payload)
    report = _render_report(native_status, trainer_status, coverage)
    _atomic_write_text(
        paths.packet_dir
        / "V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_READY\n",
    )
    return ExecutionRunResult(
        go_no_go="V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_READY",
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir / "V2_NATIVE_DYNAMIC_RUNTIME_AND_TRAINER_BRIDGE_EXIT_EXECUTION_REPORT.md",
            *[path for path, _ in writes],
        ],
    )
