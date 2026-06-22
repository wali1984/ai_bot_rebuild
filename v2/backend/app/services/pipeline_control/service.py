"""V2 full-pipeline control planning and safe command queueing.

This module is intentionally a control-plane adapter:

* reads only V2-owned Redis keys and public V2 chart payloads
* writes only ``v2:pipeline:*`` control/audit keys
* never starts a process, imports legacy trainer code, or calls an exchange
* reports current V2 live-gate state but never mutates execution
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.services.live_gate.runtime_execution_state import LIVE_GATE_ENABLED, read_runtime_execution_state
from app.services.v2_symbol_runtime_universe import is_valid_runtime_symbol, resolve_symbols_with_provenance

SCHEMA_VERSION = "v2_pipeline_control_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"

CONTROL_STREAM_KEY = "v2:pipeline:control:requests"
CONTROL_AUDIT_STREAM_KEY = "v2:pipeline:control:audit"
CONTROL_LAST_REQUEST_KEY = "v2:pipeline:control:last_request"

RUN_TYPE_TRAINER = "trainer_cycle"
RUN_TYPE_REPLAY = "replay"
RUN_TYPE_BACKTEST = "backtest"
RUN_TYPE_FULL_PIPELINE = "full_pipeline"
ALLOWED_RUN_TYPES = (
    RUN_TYPE_TRAINER,
    RUN_TYPE_REPLAY,
    RUN_TYPE_BACKTEST,
    RUN_TYPE_FULL_PIPELINE,
)

DEFAULT_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h")
ALLOWED_TIMEFRAMES = frozenset(DEFAULT_TIMEFRAMES)
MAX_SYMBOLS_PER_REQUEST = 256
MAX_TIMEFRAMES_PER_REQUEST = 8

MARKET_CHART_PUBLIC_PATH = Path("v2/frontend/public/operator_runtime/v2_professional_market_chart/latest")


@dataclass(frozen=True)
class PipelineControlRequest:
    run_type: str
    symbols: tuple[str, ...]
    timeframes: tuple[str, ...]
    dry_run: bool = True
    max_rows: int = 8192
    requested_by: str = "website"
    reason: str = "operator_requested_from_website"


@dataclass(frozen=True)
class SourceProbe:
    key: str
    present: bool
    source_type: str


@dataclass(frozen=True)
class CompatibilityRow:
    symbol: str
    timeframe: str
    trainer_compatible: bool
    backtest_compatible: bool
    replay_compatible: bool
    chart_visible: bool
    blockers: tuple[str, ...]
    required_sources_present: int
    required_sources_total: int
    optional_sources_present: int
    optional_sources_total: int
    chart_payload_path: str
    chart_status: str
    probes: tuple[SourceProbe, ...] = field(default_factory=tuple)


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _repo_root() -> Path:
    return Path(os.environ.get("V2_REPO_ROOT", "/home/wali/Desktop/AI BOT REBUILD"))


def _json_default(value: Any) -> Any:
    if hasattr(value, "__dict__"):
        return asdict(value)
    return str(value)


def _stable_request_id(request: PipelineControlRequest, generated_utc: str) -> str:
    digest = hashlib.sha256(
        json.dumps(
            {
                "run_type": request.run_type,
                "symbols": request.symbols,
                "timeframes": request.timeframes,
                "dry_run": request.dry_run,
                "max_rows": request.max_rows,
                "requested_by": request.requested_by,
                "reason": request.reason,
                "generated_utc": generated_utc,
            },
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()[:24]
    return f"v2pc_{digest}"


def _decode_raw(raw: Any) -> Any:
    if raw is None:
        return None
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return {"_raw_present": True, "raw_preview": raw[:256]}
    return raw


def _redis_get(redis_client: Any, key: str) -> Any:
    if redis_client is None:
        return None
    try:
        return _decode_raw(redis_client.get(key))
    except Exception:
        return None


def _redis_present(redis_client: Any, key: str) -> bool:
    if redis_client is None:
        return False
    payload = _redis_get(redis_client, key)
    if payload is not None:
        return True
    try:
        return bool(redis_client.exists(key))
    except Exception:
        return False


def _normalize_symbols(symbols: Iterable[str] | None) -> tuple[list[str], dict[str, Any]]:
    explicit = None
    if symbols is not None:
        cleaned = [str(s).strip().upper() for s in symbols if str(s).strip()]
        explicit = None if not cleaned or cleaned == ["ALL"] else cleaned
    provenance = resolve_symbols_with_provenance(explicit=explicit)
    raw_resolved = [str(s).strip().upper() for s in provenance["symbols"] if str(s).strip()]
    invalid_symbols = [symbol for symbol in raw_resolved if not is_valid_runtime_symbol(symbol)]
    resolved = [symbol for symbol in raw_resolved if is_valid_runtime_symbol(symbol)]
    seen: set[str] = set()
    unique = []
    for symbol in resolved:
        if symbol in seen:
            continue
        seen.add(symbol)
        unique.append(symbol)
    if len(unique) > MAX_SYMBOLS_PER_REQUEST:
        unique = unique[:MAX_SYMBOLS_PER_REQUEST]
        provenance = {
            **provenance,
            "truncated_to_max_symbols": MAX_SYMBOLS_PER_REQUEST,
        }
    if invalid_symbols:
        provenance = {
            **provenance,
            "invalid_symbols_filtered": invalid_symbols,
            "invalid_symbols_filtered_count": len(invalid_symbols),
        }
    return unique, provenance


def _live_context(redis_client: Any) -> dict[str, Any]:
    if redis_client is None:
        return {
            "live_gate": LIVE_GATE_BLOCKED,
            "live_symbols": [],
            "execution_live_symbols": [],
            "trader_execution_enabled": False,
            "runtime_source": "REDIS_UNAVAILABLE_FAIL_CLOSED",
            "runtime_validation": {
                "valid": False,
                "blockers": ["REDIS_UNAVAILABLE"],
            },
        }
    runtime = read_runtime_execution_state(redis_client=redis_client)
    payload = runtime.get("payload") if isinstance(runtime.get("payload"), Mapping) else {}
    validation = runtime.get("validation") if isinstance(runtime.get("validation"), Mapping) else {}
    if validation.get("valid") and payload.get("live_gate") == LIVE_GATE_ENABLED:
        return {
            "live_gate": LIVE_GATE_ENABLED,
            "live_symbols": [str(symbol) for symbol in payload.get("live_symbols") or []],
            "execution_live_symbols": [
                str(symbol) for symbol in payload.get("execution_live_symbols") or []
            ],
            "trader_execution_enabled": bool(payload.get("trader_execution_enabled")),
            "runtime_source": runtime.get("source"),
            "runtime_validation": validation,
        }
    return {
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "execution_live_symbols": [],
        "trader_execution_enabled": False,
        "runtime_source": runtime.get("source"),
        "runtime_validation": validation,
    }


def _normalize_timeframes(timeframes: Iterable[str] | None) -> tuple[str, ...]:
    raw = [str(tf).strip() for tf in (timeframes or DEFAULT_TIMEFRAMES) if str(tf).strip()]
    if not raw:
        raw = list(DEFAULT_TIMEFRAMES)
    out: list[str] = []
    for tf in raw:
        if tf not in ALLOWED_TIMEFRAMES:
            continue
        if tf not in out:
            out.append(tf)
    if not out:
        out = list(DEFAULT_TIMEFRAMES)
    return tuple(out[:MAX_TIMEFRAMES_PER_REQUEST])


def normalize_control_request(
    *,
    run_type: str,
    symbols: Iterable[str] | None,
    timeframes: Iterable[str] | None,
    dry_run: bool,
    max_rows: int,
    requested_by: str,
    reason: str,
) -> PipelineControlRequest:
    if run_type not in ALLOWED_RUN_TYPES:
        raise ValueError(f"unsupported_run_type:{run_type}")
    resolved_symbols, _provenance = _normalize_symbols(symbols)
    normalized_timeframes = _normalize_timeframes(timeframes)
    if not resolved_symbols:
        raise ValueError("symbols_empty_after_resolution")
    if max_rows < 1:
        raise ValueError("max_rows_must_be_positive")
    return PipelineControlRequest(
        run_type=run_type,
        symbols=tuple(resolved_symbols),
        timeframes=normalized_timeframes,
        dry_run=bool(dry_run),
        max_rows=min(int(max_rows), 250_000),
        requested_by=str(requested_by or "website")[:64],
        reason=str(reason or "operator_requested_from_website")[:256],
    )


def _chart_manifest() -> Mapping[str, Any]:
    root = _repo_root()
    candidate_paths = (
        MARKET_CHART_PUBLIC_PATH / "operator_dashboard_payload.json",
        Path("v2/frontend/public/operator_runtime/v2_market_chart/latest/operator_dashboard_payload.json"),
    )
    for rel_path in candidate_paths:
        path = root / rel_path
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(payload, Mapping):
            return payload
    return {}


def _chart_status(manifest: Mapping[str, Any], symbol: str, timeframe: str) -> str:
    payloads = manifest.get("payloads")
    if not isinstance(payloads, Mapping):
        return "CHART_MANIFEST_MISSING"
    row = payloads.get(f"{symbol}:{timeframe}") or payloads.get(symbol)
    if not isinstance(row, Mapping):
        return "CHART_PAYLOAD_MISSING"
    return str(row.get("status") or "CHART_STATUS_UNKNOWN")


def _probe(redis_client: Any, key: str, source_type: str) -> SourceProbe:
    return SourceProbe(key=key, present=_redis_present(redis_client, key), source_type=source_type)


def _compatibility_row(
    redis_client: Any,
    *,
    symbol: str,
    timeframe: str,
    chart_manifest: Mapping[str, Any],
) -> CompatibilityRow:
    required = (
        _probe(redis_client, f"v2:market:prices:{symbol}", "price"),
        _probe(redis_client, f"v2:market:ohlcv:binance:{symbol}:{timeframe}", "ohlcv"),
        _probe(redis_client, f"v2:features:latest:{symbol}:{timeframe}", "features_latest"),
        _probe(redis_client, f"v2:features:ta:{symbol}:{timeframe}", "technical_analysis"),
    )
    optional = (
        _probe(redis_client, f"v2:market:orderbook:{symbol}", "orderbook"),
        _probe(redis_client, f"v2:market:funding:{symbol}", "funding"),
        _probe(redis_client, f"v2:market:open_interest:{symbol}", "open_interest"),
        _probe(redis_client, f"v2:market:liquidation_levels:{symbol}", "liquidation_levels"),
        _probe(redis_client, f"v2:altdata:symbol_score:{symbol}", "altdata_symbol_score"),
        _probe(redis_client, f"v2:prediction:{symbol}:{timeframe}", "prediction"),
        _probe(redis_client, f"v2:signals:paper:{symbol}:{timeframe}", "paper_signal_timeframe"),
        _probe(redis_client, f"v2:signals:paper:{symbol}", "paper_signal_symbol"),
    )
    present_required = sum(1 for row in required if row.present)
    present_optional = sum(1 for row in optional if row.present)
    missing_required = tuple(row.source_type for row in required if not row.present)

    prediction_present = any(
        row.present for row in optional if row.source_type == "prediction"
    )
    signal_present = any(
        row.present
        for row in optional
        if row.source_type in {"paper_signal_timeframe", "paper_signal_symbol"}
    )
    chart_status = _chart_status(chart_manifest, symbol, timeframe)
    chart_visible = chart_status == "CURRENT"

    trainer_compatible = present_required == len(required)
    backtest_compatible = trainer_compatible and prediction_present
    replay_compatible = trainer_compatible and (prediction_present or signal_present)

    blockers: list[str] = []
    for missing in missing_required:
        blockers.append(f"missing_{missing}")
    if not prediction_present:
        blockers.append("missing_prediction_for_backtest")
    if not (prediction_present or signal_present):
        blockers.append("missing_prediction_or_signal_for_replay")
    if not chart_visible:
        blockers.append(f"chart_not_current:{chart_status}")

    return CompatibilityRow(
        symbol=symbol,
        timeframe=timeframe,
        trainer_compatible=trainer_compatible,
        backtest_compatible=backtest_compatible,
        replay_compatible=replay_compatible,
        chart_visible=chart_visible,
        blockers=tuple(blockers),
        required_sources_present=present_required,
        required_sources_total=len(required),
        optional_sources_present=present_optional,
        optional_sources_total=len(optional),
        chart_payload_path=f"/operator_runtime/v2_professional_market_chart/latest/{symbol}_{timeframe}_chart.json",
        chart_status=chart_status,
        probes=required + optional,
    )


def _last_request(redis_client: Any) -> dict[str, Any] | None:
    payload = _redis_get(redis_client, CONTROL_LAST_REQUEST_KEY)
    return payload if isinstance(payload, dict) else None


def build_pipeline_status(
    redis_client: Any,
    *,
    symbols: Iterable[str] | None = None,
    timeframes: Iterable[str] | None = None,
) -> dict[str, Any]:
    resolved_symbols, provenance = _normalize_symbols(symbols)
    live = _live_context(redis_client)
    normalized_timeframes = _normalize_timeframes(timeframes)
    manifest = _chart_manifest()
    rows = [
        _compatibility_row(
            redis_client,
            symbol=symbol,
            timeframe=timeframe,
            chart_manifest=manifest,
        )
        for symbol in resolved_symbols
        for timeframe in normalized_timeframes
    ]
    total = max(1, len(rows))
    trainer_ok = sum(1 for row in rows if row.trainer_compatible)
    backtest_ok = sum(1 for row in rows if row.backtest_compatible)
    replay_ok = sum(1 for row in rows if row.replay_compatible)
    chart_ok_symbols = {
        row.symbol for row in rows if row.chart_visible
    }
    blockers: dict[str, int] = {}
    for row in rows:
        for blocker in row.blockers:
            blockers[blocker] = blockers.get(blocker, 0) + 1

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_utc": _utc_iso(),
        "live_gate": live["live_gate"],
        "live_symbols": live["live_symbols"],
        "execution_live_symbols": live["execution_live_symbols"],
        "trader_execution_enabled": live["trader_execution_enabled"],
        "live_gate_runtime_source": live["runtime_source"],
        "exchange_action_taken": False,
        "control_stream_key": CONTROL_STREAM_KEY,
        "control_last_request_key": CONTROL_LAST_REQUEST_KEY,
        "allowed_run_types": list(ALLOWED_RUN_TYPES),
        "symbols": resolved_symbols,
        "timeframes": list(normalized_timeframes),
        "symbol_provenance": provenance,
        "compatibility": {
            "row_count": len(rows),
            "trainer_compatible_count": trainer_ok,
            "backtest_compatible_count": backtest_ok,
            "replay_compatible_count": replay_ok,
            "chart_visible_symbol_count": len(chart_ok_symbols),
            "trainer_compatible_percent": round(100.0 * trainer_ok / total, 3),
            "backtest_compatible_percent": round(100.0 * backtest_ok / total, 3),
            "replay_compatible_percent": round(100.0 * replay_ok / total, 3),
            "blocker_counts": blockers,
        },
        "rows": [asdict(row) for row in rows],
        "last_request": _last_request(redis_client),
        "website_visualization": {
            "market_chart_manifest_path": "/operator_runtime/v2_professional_market_chart/latest/operator_dashboard_payload.json",
            "trainer_page": "/trainer-admin",
            "prediction_page": "/trainer-prediction-monitor",
            "replay_page": "/replay",
            "backtesting_page": "/strategy-backtesting",
        },
    }


def _safe_xadd(redis_client: Any, stream: str, fields: dict[str, str]) -> str | None:
    if redis_client is None:
        return None
    if not stream.startswith("v2:"):
        raise ValueError(f"non_v2_control_stream_rejected:{stream}")
    try:
        return str(
            redis_client.xadd(
                stream,
                fields,
                maxlen=10_000,
                approximate=True,
            )
        )
    except TypeError:
        try:
            return str(redis_client.xadd(stream, fields))
        except Exception:
            return None
    except Exception:
        return None


def _safe_set(redis_client: Any, key: str, payload: Mapping[str, Any]) -> bool:
    if redis_client is None:
        return False
    if not key.startswith("v2:"):
        raise ValueError(f"non_v2_control_key_rejected:{key}")
    try:
        return bool(redis_client.set(key, json.dumps(payload, sort_keys=True, default=_json_default)))
    except Exception:
        return False


def record_pipeline_control_request(
    redis_client: Any,
    *,
    request: PipelineControlRequest,
) -> dict[str, Any]:
    generated_utc = _utc_iso()
    request_id = _stable_request_id(request, generated_utc)
    live = _live_context(redis_client)
    status = build_pipeline_status(
        redis_client,
        symbols=request.symbols,
        timeframes=request.timeframes,
    )
    compatibility = status["compatibility"]
    accepted = True
    queue_state = "DRY_RUN_NOT_QUEUED" if request.dry_run else "QUEUED"
    if redis_client is None and not request.dry_run:
        accepted = False
        queue_state = "REDIS_UNAVAILABLE_NOT_QUEUED"

    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "control_request_id": request_id,
        "generated_utc": generated_utc,
        "run_type": request.run_type,
        "symbols": list(request.symbols),
        "timeframes": list(request.timeframes),
        "dry_run": request.dry_run,
        "max_rows": request.max_rows,
        "requested_by": request.requested_by,
        "reason": request.reason,
        "accepted": accepted,
        "queue_state": queue_state,
        "live_gate": live["live_gate"],
        "live_symbols": live["live_symbols"],
        "execution_live_symbols": live["execution_live_symbols"],
        "trader_execution_enabled": live["trader_execution_enabled"],
        "live_gate_runtime_source": live["runtime_source"],
        "exchange_action_taken": False,
        "trainer_api_executed_job_inline": False,
        "control_stream_key": CONTROL_STREAM_KEY,
        "compatibility": compatibility,
    }

    stream_id = None
    audit_stream_id = None
    last_request_written = False
    if accepted and not request.dry_run:
        fields = {
            "control_request_id": request_id,
            "payload": json.dumps(payload, sort_keys=True, default=_json_default),
            "run_type": request.run_type,
            "requested_by": request.requested_by,
            "generated_utc": generated_utc,
            "live_gate": live["live_gate"],
        }
        stream_id = _safe_xadd(redis_client, CONTROL_STREAM_KEY, fields)
        audit_stream_id = _safe_xadd(
            redis_client,
            CONTROL_AUDIT_STREAM_KEY,
            {
                **fields,
                "audit_event": "pipeline_control_request_recorded",
                "payload_hash": hashlib.sha256(fields["payload"].encode("utf-8")).hexdigest(),
            },
        )
        last_request_written = _safe_set(redis_client, CONTROL_LAST_REQUEST_KEY, payload)
        if stream_id is None:
            payload["accepted"] = False
            payload["queue_state"] = "QUEUE_WRITE_FAILED"

    payload.update(
        {
            "stream_id": stream_id,
            "audit_stream_id": audit_stream_id,
            "last_request_written": last_request_written,
            "server_epoch_ms": int(time.time() * 1000),
        }
    )
    return payload
