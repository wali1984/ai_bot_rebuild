from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime, timezone
from typing import Any, Mapping


TIMEFRAME_SECONDS: dict[str, int] = {
    "1m": 60,
    "5m": 300,
    "15m": 900,
    "1h": 3600,
    "4h": 14400,
}

TRUST_SCHEMA_VERSION = "pipeline_trust_v3"
ENFORCEMENT_EPOCH = "pipeline_trust_v3_20260612"
TRUST_PRODUCER = "v2_pipeline_trust_gate"
TRUST_PRODUCER_VERSION = TRUST_SCHEMA_VERSION

ACTIVE_TRUST_FLAGS: tuple[str, ...] = (
    "approved",
    "pre_trade_allowed",
    "routed_to_paper",
    "trainer_consumable",
    "prediction_eligible",
    "risk_eligible",
    "paper_eligible",
    "paper_fill_allowed",
    "routes_to_orchestrator",
    "used_for_training",
    "included_in_training",
)

ACTIVE_TRUST_REQUIRED_FIELDS: tuple[str, ...] = (
    "trust_schema_version",
    "decision_id",
    "prediction_id",
    "mtf_snapshot_id",
    "replay_snapshot_id",
    "feature_cutoff",
    "available_at",
    "all_tf_candle_timestamps",
)

TRUST_SCHEMA_MISSING_REASON = "TRUST_SCHEMA_MISSING"
TRUST_SNAPSHOT_MISSING_REASON = "TRUST_SNAPSHOT_MISSING"

TERMINAL_INACTIVE_PAPER_LIFECYCLE_STATES: tuple[str, ...] = (
    "CLOSED_PREVIOUSLY",
    "EXPIRED_PREVIOUSLY",
    "CANCELED_PREVIOUSLY",
    "CANCELLED_PREVIOUSLY",
    "REJECTED_PREVIOUSLY",
)


def stable_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def parse_timestamp(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            numeric = float(value)
            if not math.isfinite(numeric):
                return None
            if numeric > 10_000_000_000:
                numeric /= 1000.0
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def isoformat_utc(value: Any) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        raise ValueError("timestamp_missing_or_invalid")
    if parsed.microsecond == 0:
        timespec = "seconds"
    elif parsed.microsecond % 1000 == 0:
        timespec = "milliseconds"
    else:
        timespec = "microseconds"
    return parsed.isoformat(timespec=timespec).replace("+00:00", "Z")


def _normalize_string_tuple(values: Any) -> tuple[str, ...]:
    if not values:
        return ()
    if isinstance(values, str):
        return (values,)
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if text:
            normalized.append(text)
    return tuple(dict.fromkeys(normalized))


def _numeric(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(parsed):
        return float(default)
    return parsed


def _int_value(value: Any, default: int = 0) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return int(default)
    return max(0, parsed)


def _bool_value(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "y", "on"}:
            return True
        if text in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def _expected_last_closed_cutoff(decision_time: datetime, timeframe: str) -> datetime:
    seconds = TIMEFRAME_SECONDS.get(timeframe)
    if seconds is None:
        return decision_time.replace(microsecond=0)
    epoch = int(decision_time.timestamp())
    cutoff_epoch = (epoch // seconds) * seconds
    return datetime.fromtimestamp(cutoff_epoch, tz=timezone.utc)


@dataclass(frozen=True)
class MarketStateEnvelope:
    symbol: str
    exchange: str
    decision_time: str
    event_time: str
    available_at: str
    ingested_at: str
    timeframe_cutoffs: dict[str, str]
    feature_cutoff: str
    feature_version: str
    feature_hash: str
    data_quality_score: float
    data_quality_flags: tuple[str, ...] = ()
    is_backfilled: bool = False
    is_final_candle: bool = True
    missing_candle_count: int = 0
    duplicate_event_count: int = 0
    out_of_order_event_count: int = 0
    source_disagreement_score: float = 0.0
    latency_ms: int = 0
    decision_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["data_quality_flags"] = list(self.data_quality_flags)
        return payload


@dataclass(frozen=True)
class TrustGateResult:
    accepted: bool
    severity: str
    reject_reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    data_quality_score: float = 0.0
    future_leak_detected: bool = False
    cutoff_mismatch_detected: bool = False
    replay_required: bool = True
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reject_reasons"] = list(self.reject_reasons)
        payload["warnings"] = list(self.warnings)
        return payload


@dataclass(frozen=True)
class RuntimeTrustContractResult:
    allowed: bool
    active: bool
    severity: str
    reject_reasons: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["reject_reasons"] = list(self.reject_reasons)
        payload["missing_fields"] = list(self.missing_fields)
        payload["warnings"] = list(self.warnings)
        return payload


class TrustGateRejectedError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        decision_id: str,
        trust_gate_result: TrustGateResult,
    ) -> None:
        super().__init__(message)
        self.decision_id = decision_id
        self.trust_gate_result = trust_gate_result


def trust_created_at(value: Any | None = None) -> str:
    parsed = parse_timestamp(value)
    if parsed is None:
        parsed = datetime.now(timezone.utc)
    return parsed.isoformat(timespec="seconds").replace("+00:00", "Z")


def attach_runtime_trust_metadata(
    record: Mapping[str, Any],
    *,
    decision_id: Any | None = None,
    prediction_id: Any | None = None,
    mtf_snapshot_id: Any | None = None,
    replay_snapshot_id: Any | None = None,
    created_at: Any | None = None,
    producer: str = TRUST_PRODUCER,
    producer_version: str = TRUST_PRODUCER_VERSION,
) -> dict[str, Any]:
    payload = dict(record)
    payload.setdefault("trust_schema_version", TRUST_SCHEMA_VERSION)
    payload.setdefault("enforcement_epoch", ENFORCEMENT_EPOCH)
    payload.setdefault("producer", producer)
    payload.setdefault("producer_version", producer_version)
    payload.setdefault("created_at", trust_created_at(created_at or payload.get("created_at") or payload.get("generated_at") or payload.get("generated_est")))
    for key, value in (
        ("decision_id", decision_id),
        ("prediction_id", prediction_id),
        ("mtf_snapshot_id", mtf_snapshot_id),
        ("replay_snapshot_id", replay_snapshot_id),
    ):
        if value is not None and str(value).strip():
            payload[key] = str(value)
    snapshot = payload.get("replay_snapshot")
    if isinstance(snapshot, Mapping):
        nested_replay_id = snapshot.get("replay_snapshot_id")
        if nested_replay_id and not payload.get("replay_snapshot_id"):
            payload["replay_snapshot_id"] = str(nested_replay_id)
        nested_mtf_id = snapshot.get("mtf_snapshot_id")
        if nested_mtf_id and not payload.get("mtf_snapshot_id"):
            payload["mtf_snapshot_id"] = str(nested_mtf_id)
        nested_tf = snapshot.get("all_tf_candle_timestamps")
        if nested_tf and not payload.get("all_tf_candle_timestamps"):
            payload["all_tf_candle_timestamps"] = list(nested_tf)
    return payload


def is_active_runtime_record(record: Mapping[str, Any]) -> bool:
    if record.get("trust_gate_allowed") is False:
        return False
    if is_terminal_inactive_runtime_record(record):
        return False
    for flag in ACTIVE_TRUST_FLAGS:
        if _bool_value(record.get(flag)):
            return True
    if str(record.get("risk_action") or "").lower() in {"allow", "approved"}:
        return True
    if str(record.get("ledger_action") or record.get("paper_fill_result") or "").lower() in {
        "record_allow",
        "allow",
        "filled",
        "submitted",
    }:
        return True
    return False


def is_terminal_inactive_runtime_record(record: Mapping[str, Any]) -> bool:
    lifecycle = str(record.get("paper_lifecycle_status") or "").strip().upper()
    persistence = str(record.get("paper_fill_persistence_status") or "").strip().upper()
    if lifecycle in TERMINAL_INACTIVE_PAPER_LIFECYCLE_STATES:
        return True
    return bool(
        lifecycle == "CLOSED"
        and persistence in {"EXISTING_FILL_CARRIED_FORWARD", "HISTORICAL_FILL_CARRIED_FORWARD"}
    )


def runtime_trust_missing_fields(record: Mapping[str, Any]) -> tuple[str, ...]:
    missing: list[str] = []
    for field_name in ACTIVE_TRUST_REQUIRED_FIELDS:
        if not _runtime_field_present(record, field_name):
            missing.append(field_name)
    return tuple(missing)


def validate_prediction_trust_contract(
    record: Mapping[str, Any],
    redis_client: Any | None = None,
    *,
    require_replay_write: bool = False,
) -> RuntimeTrustContractResult:
    if not isinstance(record, Mapping):
        return RuntimeTrustContractResult(
            allowed=False,
            active=True,
            severity="critical",
            reject_reasons=("TRUST_RECORD_NOT_MAPPING",),
        )
    active = is_active_runtime_record(record)
    missing = runtime_trust_missing_fields(record) if active else ()
    reject_reasons: list[str] = []
    warnings: list[str] = []
    if missing:
        if "trust_schema_version" in missing:
            reject_reasons.append(TRUST_SCHEMA_MISSING_REASON)
        snapshot_fields = {"mtf_snapshot_id", "replay_snapshot_id", "all_tf_candle_timestamps"}
        if snapshot_fields.intersection(missing):
            reject_reasons.append(TRUST_SNAPSHOT_MISSING_REASON)
        for field_name in missing:
            if field_name not in snapshot_fields and field_name != "trust_schema_version":
                reject_reasons.append(f"{field_name.upper()}_MISSING")
    schema_version = record.get("trust_schema_version")
    if active and schema_version != TRUST_SCHEMA_VERSION:
        reject_reasons.append(TRUST_SCHEMA_MISSING_REASON)
    mtf_snapshot_valid = record.get("mtf_snapshot_valid")
    if active and mtf_snapshot_valid is False:
        reject_reasons.append("MTF_SNAPSHOT_INVALID")
    if active and require_replay_write:
        replay_write = record.get("replay_snapshot_write_success")
        replay_key_present = _runtime_field_present(record, "replay_snapshot_id") and _present(record.get("replay_snapshot_key"))
        if replay_write is not True and not replay_key_present:
            reject_reasons.append("REPLAY_SNAPSHOT_WRITE_MISSING")
    decision_dt = parse_timestamp(
        record.get("decision_time")
        or record.get("decision_cutoff")
        or record.get("generated_at")
        or record.get("generated_est")
        or record.get("timestamp")
    )
    available_dt = parse_timestamp(record.get("available_at"))
    feature_cutoff_dt = parse_timestamp(record.get("feature_cutoff"))
    if active and decision_dt and available_dt and available_dt > decision_dt:
        reject_reasons.append("FEATURE_AVAILABLE_AFTER_DECISION_TIME")
    if active and decision_dt and feature_cutoff_dt and feature_cutoff_dt > decision_dt:
        reject_reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if active and redis_client is not None:
        replay_key = str(record.get("replay_snapshot_key") or "").strip()
        if replay_key:
            try:
                exists = redis_client.exists(replay_key)
            except Exception:
                exists = 0
            if not exists:
                reject_reasons.append("REPLAY_SNAPSHOT_NOT_FOUND")
    if not active and any(not _runtime_field_present(record, field_name) for field_name in ACTIVE_TRUST_REQUIRED_FIELDS):
        warnings.append("INACTIVE_STALE_PRE_ENFORCEMENT_RECORD")
    return RuntimeTrustContractResult(
        allowed=active is False or not reject_reasons,
        active=active,
        severity="critical" if reject_reasons else ("warning" if warnings else "info"),
        reject_reasons=tuple(dict.fromkeys(reject_reasons)),
        missing_fields=missing,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def mark_runtime_trust_denied(
    record: Mapping[str, Any],
    result: RuntimeTrustContractResult,
) -> dict[str, Any]:
    payload = dict(record)
    if result.allowed:
        payload["trust_gate_allowed"] = True
        payload["trust_gate_reasons"] = []
        return payload
    for flag in ACTIVE_TRUST_FLAGS:
        if flag in payload:
            payload[flag] = False
    payload.update(
        {
            "approved": False,
            "pre_trade_allowed": False,
            "routed_to_paper": False,
            "trainer_consumable": False,
            "prediction_eligible": False,
            "risk_eligible": False,
            "paper_eligible": False,
            "paper_fill_allowed": False,
            "routes_to_orchestrator": False,
            "trust_gate_allowed": False,
            "trust_gate_reasons": list(result.reject_reasons),
            "trust_gate_missing_fields": list(result.missing_fields),
            "trust_block_reason": _primary_trust_block_reason(result),
        }
    )
    if str(payload.get("risk_action") or "").lower() in {"allow", "approved"}:
        payload["risk_action"] = "deny"
        payload["risk_reason_code"] = "deny_default"
    if str(payload.get("ledger_action") or "").lower() == "record_allow":
        payload["ledger_action"] = "record_deny"
        payload["ledger_reason_code"] = "mirror_deny_default"
    if str(payload.get("paper_fill_result") or "").lower() in {"allow", "record_allow", "filled", "submitted"}:
        payload["paper_fill_result"] = "blocked"
    return payload


def _runtime_field_present(record: Mapping[str, Any], field_name: str) -> bool:
    value = record.get(field_name)
    if _present(value):
        return True
    snapshot = record.get("replay_snapshot")
    if isinstance(snapshot, Mapping) and _present(snapshot.get(field_name)):
        return True
    if field_name == "replay_snapshot_id":
        return isinstance(snapshot, Mapping) and _present(snapshot.get("replay_snapshot_id"))
    if field_name == "all_tf_candle_timestamps" and isinstance(snapshot, Mapping):
        return _present(snapshot.get("all_tf_candle_timestamps"))
    return False


def _present(value: Any) -> bool:
    if value is None:
        return False
    if value == "":
        return False
    if isinstance(value, (list, tuple, set, dict)) and not value:
        return False
    return True


def _primary_trust_block_reason(result: RuntimeTrustContractResult) -> str:
    if TRUST_SCHEMA_MISSING_REASON in result.reject_reasons:
        return TRUST_SCHEMA_MISSING_REASON
    if TRUST_SNAPSHOT_MISSING_REASON in result.reject_reasons:
        return TRUST_SNAPSHOT_MISSING_REASON
    return result.reject_reasons[0] if result.reject_reasons else "TRUST_CONTRACT_REJECTED"


def hash_market_state_envelope(envelope: MarketStateEnvelope | Mapping[str, Any]) -> str:
    coerced = coerce_market_state_envelope(envelope)
    return stable_hash(coerced.to_dict())


def build_market_state_envelope_from_snapshot(
    snapshot: Mapping[str, Any],
    *,
    exchange_default: str = "binance",
    require_verified_native_snapshot: bool = False,
) -> MarketStateEnvelope:
    if not isinstance(snapshot, Mapping):
        raise TypeError("snapshot must be a mapping")
    schema_version = str(snapshot.get("schema_version") or "")
    if (
        require_verified_native_snapshot
        and schema_version != "v2_native_feature_snapshot_v2"
    ):
        raise ValueError("active_native_feature_snapshot_v2_required")
    native_feature_worker = (
        snapshot.get("worker_id") == "v2_feature_pipeline_native_loop"
    )
    if native_feature_worker and schema_version != "v2_native_feature_snapshot_v2":
        raise ValueError("native_feature_snapshot_schema_downgrade_rejected")
    exact_native_snapshot = schema_version == "v2_native_feature_snapshot_v2"
    if exact_native_snapshot:
        if not native_feature_worker:
            raise ValueError("exact_native_feature_producer_identity_required")
        if snapshot.get("exact_source_clock_valid") is not True:
            raise ValueError("exact_source_clock_lineage_required")
        if snapshot.get("exact_feature_availability_valid") is not True:
            raise ValueError("exact_feature_availability_required")
        if parse_timestamp(snapshot.get("feature_available_at")) is None:
            raise ValueError("feature_available_at_missing_or_invalid")
        # A self-asserted boolean/timestamp in mutable Redis is not a
        # publication receipt. Keep v2 snapshots unconditionally inactive
        # until the immutable ledger validator binds the committed bytes,
        # snapshot id/hash, postcommit clock, and successful readback.
        raise ValueError("verified_feature_publication_receipt_required")
    embedded = snapshot.get("market_state_envelope")
    if embedded is not None and not exact_native_snapshot:
        return coerce_market_state_envelope(embedded)

    symbol = str(snapshot.get("symbol") or "").upper()
    exchange = str(snapshot.get("exchange") or exchange_default or "").lower() or "binance"
    timeframe = str(snapshot.get("timeframe") or "1m")
    decision_dt = parse_timestamp(
        snapshot.get("decision_time")
        or snapshot.get("decision_cutoff")
        or snapshot.get("generated_at")
        or snapshot.get("generated_utc")
    )
    if decision_dt is None:
        raise ValueError("decision_time_missing")
    explicit_feature_cutoff = snapshot.get("feature_cutoff") or snapshot.get("decision_cutoff")
    feature_cutoff_dt = parse_timestamp(explicit_feature_cutoff)
    if feature_cutoff_dt is None:
        feature_cutoff_dt = _expected_last_closed_cutoff(decision_dt, timeframe)
    timeframe_cutoffs_raw = snapshot.get("timeframe_cutoffs")
    timeframe_cutoffs: dict[str, str] = {}
    if isinstance(timeframe_cutoffs_raw, Mapping):
        for key, value in timeframe_cutoffs_raw.items():
            key_text = str(key or "").strip()
            if not key_text:
                continue
            parsed = parse_timestamp(value)
            if parsed is None:
                continue
            timeframe_cutoffs[key_text] = isoformat_utc(parsed)
    if not timeframe_cutoffs:
        timeframe_cutoffs[timeframe] = isoformat_utc(feature_cutoff_dt)
    flags = list(_normalize_string_tuple(snapshot.get("data_quality_flags")))
    flags.extend(_normalize_string_tuple(snapshot.get("missing_feature_flags")))
    flags.extend(_normalize_string_tuple(snapshot.get("stale_feature_flags")))
    flags = list(dict.fromkeys(flags))
    missing_candle_count = _int_value(snapshot.get("missing_candle_count"))
    duplicate_event_count = _int_value(snapshot.get("duplicate_event_count"))
    out_of_order_event_count = _int_value(snapshot.get("out_of_order_event_count"))
    if missing_candle_count > 0 and "missing_candles" not in flags:
        flags.append("missing_candles")
    if duplicate_event_count > 0 and "duplicate_events" not in flags:
        flags.append("duplicate_events")
    if out_of_order_event_count > 0 and "out_of_order_events" not in flags:
        flags.append("out_of_order_events")
    freshness_state = str(
        snapshot.get("feature_freshness_state")
        or snapshot.get("freshness_state")
        or "CURRENT"
    ).upper()
    if freshness_state != "CURRENT" and "feature_freshness_not_current" not in flags:
        flags.append("feature_freshness_not_current")
    finality_value = snapshot.get("is_final_candle")
    if finality_value is None:
        finality_value = snapshot.get("candle_closed_confirmed")
    if finality_value is None:
        finality_value = snapshot.get("closed_candle")
    if finality_value is None:
        finality_value = snapshot.get("is_closed")
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    feature_hash = str(snapshot.get("feature_hash") or stable_hash(features))
    data_quality_score = snapshot.get("data_quality_score")
    if data_quality_score is None:
        base_score = 1.0 if freshness_state == "CURRENT" else 0.65
        penalty = 0.1 * len(flags)
        if _bool_value(snapshot.get("is_backfilled")):
            penalty += 0.1
        data_quality_score = max(0.0, min(1.0, base_score - penalty))
    available_dt = parse_timestamp(
        snapshot.get("feature_available_at")
        or snapshot.get("available_at")
        or snapshot.get("source_available_time")
        or snapshot.get("generated_at")
        or feature_cutoff_dt
    )
    event_dt = parse_timestamp(
        snapshot.get("event_time")
        or snapshot.get("source_event_time")
        or snapshot.get("candle_close_time")
        or feature_cutoff_dt
    )
    ingested_dt = parse_timestamp(
        snapshot.get("ingested_at")
        or snapshot.get("source_ingested_at")
        or snapshot.get("generated_at")
        or available_dt
    )
    if available_dt is None or event_dt is None or ingested_dt is None:
        raise ValueError("envelope_timestamp_missing")
    latency_ms = snapshot.get("latency_ms")
    if latency_ms is None:
        latency_ms = max(
            0,
            int((decision_dt - available_dt).total_seconds() * 1000),
        )
    decision_id = str(snapshot.get("decision_id") or "").strip()
    if not decision_id:
        decision_id = "mst_" + stable_hash(
            {
                "symbol": symbol,
                "decision_time": isoformat_utc(decision_dt),
                "feature_cutoff": isoformat_utc(feature_cutoff_dt),
                "feature_hash": feature_hash,
            }
        )[:24]
    return MarketStateEnvelope(
        symbol=symbol,
        exchange=exchange,
        decision_time=isoformat_utc(decision_dt),
        event_time=isoformat_utc(event_dt),
        available_at=isoformat_utc(available_dt),
        ingested_at=isoformat_utc(ingested_dt),
        timeframe_cutoffs=timeframe_cutoffs,
        feature_cutoff=isoformat_utc(feature_cutoff_dt),
        feature_version=str(snapshot.get("feature_version") or snapshot.get("schema_version") or "unknown"),
        feature_hash=feature_hash,
        data_quality_score=max(0.0, min(1.0, _numeric(data_quality_score))),
        data_quality_flags=tuple(flags),
        is_backfilled=_bool_value(snapshot.get("is_backfilled")),
        is_final_candle=_bool_value(finality_value, default=True),
        missing_candle_count=missing_candle_count,
        duplicate_event_count=duplicate_event_count,
        out_of_order_event_count=out_of_order_event_count,
        source_disagreement_score=max(0.0, _numeric(snapshot.get("source_disagreement_score"))),
        latency_ms=_int_value(latency_ms),
        decision_id=decision_id,
    )


def coerce_market_state_envelope(
    value: MarketStateEnvelope | Mapping[str, Any],
) -> MarketStateEnvelope:
    if isinstance(value, MarketStateEnvelope):
        return value
    if isinstance(value, Mapping):
        if all(
            key in value
            for key in (
                "symbol",
                "exchange",
                "decision_time",
                "event_time",
                "available_at",
                "ingested_at",
                "timeframe_cutoffs",
                "feature_cutoff",
                "feature_version",
                "feature_hash",
                "data_quality_score",
            )
        ):
            return MarketStateEnvelope(
                symbol=str(value.get("symbol") or "").upper(),
                exchange=str(value.get("exchange") or "binance").lower(),
                decision_time=isoformat_utc(value.get("decision_time")),
                event_time=isoformat_utc(value.get("event_time")),
                available_at=isoformat_utc(value.get("available_at")),
                ingested_at=isoformat_utc(value.get("ingested_at")),
                timeframe_cutoffs={
                    str(key): isoformat_utc(val)
                    for key, val in dict(value.get("timeframe_cutoffs") or {}).items()
                },
                feature_cutoff=isoformat_utc(value.get("feature_cutoff")),
                feature_version=str(value.get("feature_version") or "unknown"),
                feature_hash=str(value.get("feature_hash") or ""),
                data_quality_score=max(0.0, min(1.0, _numeric(value.get("data_quality_score")))),
                data_quality_flags=_normalize_string_tuple(value.get("data_quality_flags")),
                is_backfilled=_bool_value(value.get("is_backfilled")),
                is_final_candle=_bool_value(value.get("is_final_candle"), default=True),
                missing_candle_count=_int_value(value.get("missing_candle_count")),
                duplicate_event_count=_int_value(value.get("duplicate_event_count")),
                out_of_order_event_count=_int_value(value.get("out_of_order_event_count")),
                source_disagreement_score=max(0.0, _numeric(value.get("source_disagreement_score"))),
                latency_ms=_int_value(value.get("latency_ms")),
                decision_id=str(value.get("decision_id") or "").strip(),
            )
        return build_market_state_envelope_from_snapshot(value)
    raise TypeError("market_state_envelope must be a mapping or MarketStateEnvelope")


def coerce_trust_gate_result(
    value: TrustGateResult | Mapping[str, Any],
) -> TrustGateResult:
    if isinstance(value, TrustGateResult):
        return value
    if isinstance(value, Mapping):
        return TrustGateResult(
            accepted=_bool_value(value.get("accepted")),
            severity=str(value.get("severity") or "reject"),
            reject_reasons=_normalize_string_tuple(value.get("reject_reasons")),
            warnings=_normalize_string_tuple(value.get("warnings")),
            data_quality_score=max(0.0, min(1.0, _numeric(value.get("data_quality_score")))),
            future_leak_detected=_bool_value(value.get("future_leak_detected")),
            cutoff_mismatch_detected=_bool_value(value.get("cutoff_mismatch_detected")),
            replay_required=_bool_value(value.get("replay_required"), default=True),
            metrics=dict(value.get("metrics") or {}),
        )
    raise TypeError("trust_gate_result must be a mapping or TrustGateResult")


class EventTimeAligner:
    def __init__(
        self,
        *,
        min_data_quality_score: float = 0.5,
        max_source_disagreement_score: float = 50.0,
        max_latency_ms: int = 300_000,
    ) -> None:
        self._min_data_quality_score = float(min_data_quality_score)
        self._max_source_disagreement_score = float(max_source_disagreement_score)
        self._max_latency_ms = int(max_latency_ms)

    def evaluate(
        self,
        *,
        envelope: MarketStateEnvelope | Mapping[str, Any],
        features: Mapping[str, Any] | None = None,
        required_feature_names: tuple[str, ...] | list[str] = (),
        masa_feature_cutoff: Any | None = None,
        live_mode: bool = False,
    ) -> TrustGateResult:
        env = coerce_market_state_envelope(envelope)
        reject_reasons: list[str] = []
        warnings: list[str] = []
        cutoff_mismatch = False
        future_leak = False
        decision_dt = parse_timestamp(env.decision_time)
        event_dt = parse_timestamp(env.event_time)
        available_dt = parse_timestamp(env.available_at)
        ingested_dt = parse_timestamp(env.ingested_at)
        feature_cutoff_dt = parse_timestamp(env.feature_cutoff)
        if None in {decision_dt, event_dt, available_dt, ingested_dt, feature_cutoff_dt}:
            reject_reasons.append("envelope_timestamp_missing")
        if decision_dt and feature_cutoff_dt and feature_cutoff_dt > decision_dt:
            future_leak = True
            reject_reasons.append("future_feature_cutoff")
        if decision_dt and available_dt and available_dt > decision_dt:
            future_leak = True
            reject_reasons.append("feature_available_after_decision_time")
        if decision_dt and event_dt and event_dt > decision_dt:
            future_leak = True
            reject_reasons.append("source_event_after_decision_time")
        if decision_dt and ingested_dt and ingested_dt > decision_dt:
            future_leak = True
            reject_reasons.append("ingested_after_decision_time")
        if not env.is_final_candle:
            reject_reasons.append("unfinished_candle")
        if env.is_backfilled and live_mode:
            reject_reasons.append("backfilled_state_used_as_live")
        if env.missing_candle_count > 0:
            reject_reasons.append("missing_candles")
        if env.duplicate_event_count > 0:
            reject_reasons.append("duplicate_events")
        if env.out_of_order_event_count > 0:
            reject_reasons.append("out_of_order_events")
        if env.source_disagreement_score > self._max_source_disagreement_score:
            reject_reasons.append("source_disagreement_exceeds_threshold")
        if env.latency_ms > self._max_latency_ms:
            reject_reasons.append("latency_exceeds_threshold")
        if env.data_quality_score < self._min_data_quality_score:
            reject_reasons.append("data_quality_below_threshold")
        if not env.timeframe_cutoffs:
            reject_reasons.append("missing_timeframe_cutoffs")
        if decision_dt is not None:
            for timeframe, cutoff in env.timeframe_cutoffs.items():
                cutoff_dt = parse_timestamp(cutoff)
                if cutoff_dt is None:
                    reject_reasons.append(f"invalid_timeframe_cutoff:{timeframe}")
                    continue
                expected_cutoff = _expected_last_closed_cutoff(decision_dt, timeframe)
                if cutoff_dt > decision_dt:
                    future_leak = True
                    reject_reasons.append(f"future_timeframe_cutoff:{timeframe}")
                # Exchange candles stamp closeTime as boundary-1ms
                # (e.g. 05:03:59.999 for the candle closing at 05:04:00).
                # Accept that convention as the same last-closed cutoff;
                # anything else (earlier candle / future) still rejects.
                cutoff_gap_seconds = (expected_cutoff - cutoff_dt).total_seconds()
                if cutoff_dt != expected_cutoff and not (0.0 < cutoff_gap_seconds <= 1.0):
                    cutoff_mismatch = True
                    reject_reasons.append(f"mixed_timeframe_cutoff:{timeframe}")
        if masa_feature_cutoff is not None:
            masa_cutoff_dt = parse_timestamp(masa_feature_cutoff)
            if masa_cutoff_dt is None:
                reject_reasons.append("masa_feature_cutoff_missing")
            else:
                if decision_dt and masa_cutoff_dt > decision_dt:
                    future_leak = True
                    reject_reasons.append("masa_future_feature_cutoff")
                if feature_cutoff_dt and masa_cutoff_dt != feature_cutoff_dt:
                    cutoff_mismatch = True
                    reject_reasons.append("masa_ppo_cutoff_mismatch")
        feature_map = dict(features or {})
        for name in required_feature_names:
            if name not in feature_map:
                continue
            raw = feature_map.get(name)
            if raw is None:
                reject_reasons.append(f"required_feature_missing:{name}")
                continue
            try:
                value = float(raw)
            except (TypeError, ValueError):
                reject_reasons.append(f"required_feature_non_numeric:{name}")
                continue
            if not math.isfinite(value):
                reject_reasons.append(f"required_feature_non_finite:{name}")
        severity = "reject" if reject_reasons else "accept"
        metrics = {
            "timeframe_cutoffs": dict(env.timeframe_cutoffs),
            "missing_candle_count": env.missing_candle_count,
            "duplicate_event_count": env.duplicate_event_count,
            "out_of_order_event_count": env.out_of_order_event_count,
            "latency_ms": env.latency_ms,
            "source_disagreement_score": env.source_disagreement_score,
        }
        if is_dataclass(features):
            warnings.append("feature_payload_dataclass_received")
        return TrustGateResult(
            accepted=not reject_reasons,
            severity=severity,
            reject_reasons=tuple(dict.fromkeys(reject_reasons)),
            warnings=tuple(dict.fromkeys(warnings)),
            data_quality_score=env.data_quality_score,
            future_leak_detected=future_leak,
            cutoff_mismatch_detected=cutoff_mismatch,
            replay_required=True,
            metrics=metrics,
        )
