from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from v2.backend.app.services.market_state_integrity.sample_rejection import (
    classify_training_sample,
)
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    REQUIRED_FEEDBACK_FIELDS,
    REQUIRED_TRUST_ENVELOPE_FIELDS,
)


TRAINER_FEEDBACK_REDIS_KEY = "v2:trainer:feedback:outcomes"
MATURATION_STATUS_REDIS_KEY = "v2:trainer:strategy_supply_feedback_maturation_status"
FEEDBACK_SOURCE = "V2_STRATEGY_SUPPLY_SHADOW_OUTCOME"


def utc_iso(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            parsed = datetime.fromtimestamp(float(value) / (1000.0 if value > 10_000_000_000 else 1.0), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
        return parsed.astimezone(timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def coerce_float(value: Any) -> float | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed != parsed:
        return None
    return parsed


def first_present(*values: Any) -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if isinstance(payload, dict):
            rows.append(payload)
    return rows


def append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(dict(payload), sort_keys=True, separators=(",", ":")) + "\n")


def row_identity(row: Mapping[str, Any]) -> str:
    raw = "|".join(
        str(first_present(row.get(field), ""))
        for field in (
            "candidate_id",
            "hypothesis_id",
            "strategy_supply_hypothesis_id",
            "symbol",
            "timeframe",
            "side",
            "decision_time",
        )
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def timeframe_delta(timeframe: Any) -> timedelta | None:
    text = str(timeframe or "").strip().lower()
    if not text:
        return None
    unit = text[-1]
    try:
        amount = int(text[:-1])
    except ValueError:
        return None
    if amount <= 0:
        return None
    if unit == "m":
        return timedelta(minutes=amount)
    if unit == "h":
        return timedelta(hours=amount)
    if unit == "d":
        return timedelta(days=amount)
    return None


def decode_json_payload(raw: Any) -> Any:
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except ValueError:
            return None
    return raw


def read_redis_json(client: Any | None, key: str) -> Any:
    if client is None:
        return None
    try:
        raw = client.get(key)
    except Exception:
        return None
    return decode_json_payload(raw)


def snapshot_features(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, Mapping):
        return {}
    features = snapshot.get("features")
    return dict(features) if isinstance(features, Mapping) else {}


def snapshot_price(snapshot: Mapping[str, Any]) -> float | None:
    features = snapshot_features(snapshot)
    for value in (
        features.get("close"),
        features.get("last_price"),
        features.get("price_last"),
        features.get("ohlcv_close"),
        snapshot.get("close"),
        snapshot.get("last_price"),
        snapshot.get("current_price"),
        snapshot.get("price"),
    ):
        parsed = coerce_float(value)
        if parsed is not None and parsed > 0.0:
            return parsed
    return None


def snapshot_time(snapshot: Mapping[str, Any], *fields: str) -> datetime | None:
    for field in fields:
        parsed = parse_utc(snapshot.get(field))
        if parsed is not None:
            return parsed
    return None


def entry_snapshot_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    snapshot = row.get("entry_feature_snapshot")
    if not isinstance(snapshot, Mapping):
        snapshot = row.get("feature_snapshot") if isinstance(row.get("feature_snapshot"), Mapping) else None
    reasons: list[str] = []
    if not isinstance(snapshot, Mapping) or not snapshot_features(snapshot):
        return ["MISSING_PIT_ENTRY_FEATURE_SNAPSHOT"]
    if snapshot.get("candle_closed_confirmed") is False:
        reasons.append("UNFINISHED_ENTRY_FEATURE_CANDLE")
    expected_id = first_present(row.get("entry_feature_snapshot_id"), row.get("feature_snapshot_id"))
    snapshot_id = first_present(snapshot.get("feature_snapshot_id"), snapshot.get("snapshot_id"))
    if expected_id not in (None, "") and snapshot_id not in (None, "") and str(expected_id) != str(snapshot_id):
        reasons.append("ENTRY_FEATURE_SNAPSHOT_ID_MISMATCH")
    decision_time = parse_utc(row.get("decision_time"))
    available_at = snapshot_time(snapshot, "available_at", "generated_at", "source_available_time")
    feature_cutoff = snapshot_time(snapshot, "feature_cutoff", "candle_close_time", "source_event_time_est")
    if decision_time is None:
        reasons.append("MISSING_OR_UNPARSEABLE_DECISION_TIME")
    if available_at is None:
        reasons.append("MISSING_OR_UNPARSEABLE_ENTRY_AVAILABLE_AT")
    if feature_cutoff is None:
        reasons.append("MISSING_OR_UNPARSEABLE_ENTRY_FEATURE_CUTOFF")
    if decision_time is not None and available_at is not None and available_at > decision_time:
        reasons.append("ENTRY_AVAILABLE_AT_AFTER_DECISION_TIME")
    if decision_time is not None and feature_cutoff is not None and feature_cutoff > decision_time:
        reasons.append("ENTRY_FEATURE_CUTOFF_AFTER_DECISION_TIME")
    return sorted(set(reasons))


def latest_exit_snapshot(client: Any | None, symbol: str, timeframe: str) -> dict[str, Any] | None:
    payload = read_redis_json(client, f"v2:features:latest:{symbol.upper()}:{timeframe}")
    return dict(payload) if isinstance(payload, Mapping) else None


def exit_snapshot_rejection_reasons(
    snapshot: Mapping[str, Any] | None,
    *,
    label_close_time: datetime,
    now: datetime,
) -> list[str]:
    if not isinstance(snapshot, Mapping) or not snapshot_features(snapshot):
        return ["MISSING_EXIT_FEATURE_SNAPSHOT"]
    if snapshot.get("candle_closed_confirmed") is False:
        return ["UNFINISHED_EXIT_FEATURE_CANDLE"]
    feature_cutoff = snapshot_time(snapshot, "feature_cutoff", "candle_close_time", "source_event_time_est")
    available_at = snapshot_time(snapshot, "available_at", "generated_at", "source_available_time")
    reasons: list[str] = []
    if feature_cutoff is None:
        reasons.append("MISSING_OR_UNPARSEABLE_EXIT_FEATURE_CUTOFF")
    elif feature_cutoff < label_close_time:
        reasons.append("EXIT_FEATURE_BEFORE_LABEL_CLOSE")
    elif feature_cutoff > now:
        reasons.append("EXIT_FEATURE_CUTOFF_AFTER_NOW")
    if available_at is None:
        reasons.append("MISSING_OR_UNPARSEABLE_EXIT_AVAILABLE_AT")
    elif available_at > now:
        reasons.append("EXIT_AVAILABLE_AT_AFTER_NOW")
    if snapshot_price(snapshot) is None:
        reasons.append("MISSING_EXIT_PRICE")
    return sorted(set(reasons))


def context_payload(row: Mapping[str, Any], context_type: str, values: Mapping[str, Any]) -> dict[str, Any]:
    clean = {key: value for key, value in values.items() if value not in (None, "", [], {})}
    payload = {
        "source": "V2_STRATEGY_SUPPLY_SHADOW_EVIDENCE",
        "context_type": context_type,
        "status": "provided" if clean else "explicitly_unavailable",
    }
    payload.update(clean)
    if not clean:
        payload["unavailable_reason"] = f"MISSING_{context_type}_FIELDS"
    return payload


def feature_value(row: Mapping[str, Any], features: Mapping[str, Any], *names: str) -> Any:
    for name in names:
        value = features.get(name)
        if value not in (None, ""):
            return value
    for name in names:
        value = row.get(name)
        if value not in (None, ""):
            return value
    return None


def set_feature_alias(features: dict[str, Any], target: str, *values: Any) -> None:
    if features.get(target) not in (None, ""):
        return
    value = first_present(*values)
    if value in (None, ""):
        return
    parsed = coerce_float(value)
    features[target] = parsed if parsed is not None else value


def funding_rate_from_bps(*values: Any) -> float | None:
    for value in values:
        parsed = coerce_float(value)
        if parsed is not None:
            return parsed / 10_000.0
    return None


def mask_names_from_flags(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        return sorted(str(name) for name, flag in value.items() if bool(flag) and str(name).strip())
    if isinstance(value, (list, tuple)):
        return sorted(str(name) for name in value if str(name).strip())
    return []


def trainer_entry_feature_snapshot(row: Mapping[str, Any]) -> dict[str, Any]:
    raw_snapshot = row.get("entry_feature_snapshot")
    if not isinstance(raw_snapshot, Mapping):
        raw_snapshot = row.get("feature_snapshot") if isinstance(row.get("feature_snapshot"), Mapping) else {}
    snapshot = deepcopy(dict(raw_snapshot))
    features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
    features = dict(features)

    set_feature_alias(
        features,
        "close",
        features.get("close"),
        features.get("ohlcv_close"),
        features.get("last_price"),
        row.get("entry_price"),
        row.get("current_price"),
    )
    set_feature_alias(features, "last_price", features.get("last_price"), features.get("close"), row.get("current_price"))
    for name in ("open", "high", "low"):
        set_feature_alias(features, name, features.get(name), features.get(f"ohlcv_{name}"), row.get(name))

    set_feature_alias(
        features,
        "bid_ask_spread_bps",
        features.get("bid_ask_spread_bps"),
        features.get("orderbook_spread_bps"),
        features.get("observed_spread_bps"),
        row.get("observed_bid_ask_spread_bps"),
        row.get("actual_observed_spread_entry_bps"),
        row.get("observed_spread_bps"),
    )
    set_feature_alias(
        features,
        "orderbook_depth_usd",
        features.get("orderbook_depth_usd"),
        features.get("depth_usd"),
        features.get("depth_total_usd"),
        row.get("orderbook_depth_usd"),
        row.get("expected_exit_depth_usd"),
    )
    set_feature_alias(features, "bid_depth_usd", features.get("bid_depth_usd"), row.get("bid_depth_usd"))
    set_feature_alias(features, "ask_depth_usd", features.get("ask_depth_usd"), row.get("ask_depth_usd"))
    set_feature_alias(features, "open_interest", features.get("open_interest"), row.get("open_interest"))
    set_feature_alias(features, "long_short_ratio", features.get("long_short_ratio"), row.get("long_short_ratio"))
    set_feature_alias(features, "mark_price", features.get("mark_price"), row.get("mark_price"))
    set_feature_alias(features, "basis_pct", features.get("basis_pct"), row.get("basis_pct"))
    set_feature_alias(features, "funding_bps", features.get("funding_bps"), row.get("funding_bps"), row.get("expected_funding_bps"))
    if features.get("funding_rate") in (None, ""):
        funding_rate = coerce_float(feature_value(row, features, "funding_rate"))
        if funding_rate is None:
            funding_rate = funding_rate_from_bps(
                features.get("funding_bps"),
                features.get("expected_funding_bps"),
                row.get("funding_bps"),
                row.get("expected_funding_bps"),
            )
        if funding_rate is not None:
            features["funding_rate"] = funding_rate
    set_feature_alias(
        features,
        "liquidation_cluster_distance_usd",
        features.get("liquidation_cluster_distance_usd"),
        row.get("liquidation_cluster_distance_usd"),
    )
    set_feature_alias(
        features,
        "public_intel_score",
        features.get("public_intel_score"),
        row.get("public_intel_score"),
    )
    snapshot["features"] = features

    for field in ("feature_snapshot_id", "symbol", "timeframe"):
        if snapshot.get(field) in (None, "") and row.get(field) not in (None, ""):
            snapshot[field] = row.get(field)
    for field in ("available_at", "generated_at", "feature_cutoff", "candle_open_time", "candle_close_time"):
        if snapshot.get(field) in (None, "") and row.get(field) not in (None, ""):
            snapshot[field] = row.get(field)
    snapshot.setdefault("feature_freshness_state", row.get("feature_freshness_state") or "CURRENT")
    if snapshot.get("candle_closed_confirmed") is None and row.get("candle_closed_confirmed") is not None:
        snapshot["candle_closed_confirmed"] = row.get("candle_closed_confirmed")

    if "missing_feature_flags" not in snapshot and "missing_feature_count" not in snapshot:
        snapshot["missing_feature_flags"] = {}
        snapshot["missing_feature_count"] = 0
    if "stale_feature_flags" not in snapshot and "stale_feature_count" not in snapshot:
        snapshot["stale_feature_flags"] = {}
        snapshot["stale_feature_count"] = 0
    if not isinstance(snapshot.get("source_availability"), Mapping):
        source_hashes = row.get("source_hashes") if isinstance(row.get("source_hashes"), Mapping) else {}
        if not source_hashes and isinstance(row.get("provider_hashes"), Mapping):
            source_hashes = row.get("provider_hashes") or {}
        if source_hashes:
            snapshot["source_availability"] = {
                str(name): {
                    "content_hash": value,
                    "available_at": first_present(row.get("available_at"), snapshot.get("available_at")),
                }
                for name, value in source_hashes.items()
            }
    snapshot["strategy_supply_feedback_lineage_preserved"] = True
    return snapshot


def apply_trainer_gate_fields(row: dict[str, Any], *, entry_snapshot: Mapping[str, Any]) -> None:
    features = snapshot_features(entry_snapshot)
    missing_names = mask_names_from_flags(entry_snapshot.get("missing_feature_flags"))
    stale_names = mask_names_from_flags(entry_snapshot.get("stale_feature_flags"))
    row.update(
        {
            "features": dict(features),
            "missing_feature_names": missing_names,
            "missing_feature_count": int(coerce_float(entry_snapshot.get("missing_feature_count")) or len(missing_names)),
            "stale_feature_names": stale_names,
            "stale_feature_count": int(coerce_float(entry_snapshot.get("stale_feature_count")) or len(stale_names)),
            "missing_feature_lineage_source": "strategy_supply_entry_feature_snapshot_flags",
            "source_availability": entry_snapshot.get("source_availability") if isinstance(entry_snapshot.get("source_availability"), Mapping) else {},
            "feature_freshness_state": first_present(
                row.get("feature_freshness_state"),
                entry_snapshot.get("feature_freshness_state"),
                "CURRENT",
            ),
            "candle_closed_confirmed": row.get("candle_closed_confirmed")
            if row.get("candle_closed_confirmed") is not None
            else entry_snapshot.get("candle_closed_confirmed"),
            "closed_candle": row.get("closed_candle")
            if row.get("closed_candle") is not None
            else entry_snapshot.get("closed_candle") or entry_snapshot.get("candle_closed_confirmed"),
            "candle_open_time": first_present(row.get("candle_open_time"), entry_snapshot.get("candle_open_time")),
            "candle_close_time": first_present(
                row.get("candle_close_time"),
                entry_snapshot.get("candle_close_time"),
                row.get("feature_cutoff"),
            ),
            "source_event_time_est": first_present(
                row.get("source_event_time_est"),
                row.get("source_event_time"),
                row.get("feature_cutoff"),
                entry_snapshot.get("source_event_time_est"),
                entry_snapshot.get("feature_cutoff"),
            ),
            "source_received_time_est": first_present(
                row.get("source_received_time_est"),
                row.get("available_at"),
                entry_snapshot.get("source_available_time"),
                entry_snapshot.get("available_at"),
            ),
            "decision_cutoff_time_est": first_present(
                row.get("decision_cutoff_time_est"),
                row.get("decision_time"),
                row.get("feature_cutoff"),
            ),
        }
    )
    sample = classify_training_sample(dict(row))
    row["market_state_integrity_score"] = sample.get("market_state_integrity_score")
    row["accepted_for_training"] = sample.get("accepted_for_training") is True
    row["valid_for_training"] = sample.get("valid_for_training") is True
    row["reject_reasons"] = list(sample.get("reject_reasons") or [])


def trainer_feedback_row_for_publish(record: Mapping[str, Any]) -> dict[str, Any] | None:
    row = record.get("trainer_feedback_row")
    if not isinstance(row, Mapping):
        return None
    feedback_row = dict(row)
    entry_snapshot = trainer_entry_feature_snapshot({**dict(record), **feedback_row})
    feedback_row["entry_feature_snapshot"] = entry_snapshot
    apply_trainer_gate_fields(feedback_row, entry_snapshot=entry_snapshot)
    missing_feedback, missing_trust = feedback_missing_fields(feedback_row)
    feedback_row["missing_feedback_fields"] = missing_feedback
    feedback_row["missing_trust_fields"] = missing_trust
    feedback_row["trainer_consumable"] = (
        not missing_feedback
        and not missing_trust
        and feedback_row.get("accepted_for_training") is True
        and not feedback_row.get("reject_reasons")
    )
    feedback_row["trainer_feedback_blockers"] = [
        *(f"MISSING_FEEDBACK_{field}" for field in missing_feedback),
        *(f"MISSING_TRUST_{field}" for field in missing_trust),
        *(f"TRAINING_GATE_{reason}" for reason in feedback_row.get("reject_reasons") or []),
    ]
    return feedback_row


def build_contexts(row: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    entry_snapshot = trainer_entry_feature_snapshot(row)
    features = snapshot_features(entry_snapshot)
    liquidity = context_payload(
        row,
        "LIQUIDITY",
        {
            "orderbook_depth_usd": first_present(
                row.get("orderbook_depth_usd"),
                row.get("expected_exit_depth_usd"),
                features.get("orderbook_depth_usd"),
                features.get("depth_usd"),
                features.get("depth_total_usd"),
            ),
            "bid_depth_usd": first_present(row.get("bid_depth_usd"), features.get("bid_depth_usd")),
            "ask_depth_usd": first_present(row.get("ask_depth_usd"), features.get("ask_depth_usd")),
        },
    )
    liquidation = context_payload(
        row,
        "LIQUIDATION",
        {
            "liquidation_buffer_usd": first_present(row.get("liquidation_buffer_usd"), features.get("liquidation_buffer_usd")),
            "liquidation_buffer_bps": first_present(row.get("liquidation_buffer_bps"), features.get("liquidation_buffer_bps")),
            "liquidation_cluster_distance_usd": first_present(
                row.get("liquidation_cluster_distance_usd"),
                features.get("liquidation_cluster_distance_usd"),
            ),
        },
    )
    microstructure = context_payload(
        row,
        "MICROSTRUCTURE",
        {
            "bid_ask_spread_bps": first_present(
                row.get("observed_bid_ask_spread_bps"),
                row.get("actual_observed_spread_entry_bps"),
                row.get("observed_spread_bps"),
                features.get("bid_ask_spread_bps"),
                features.get("orderbook_spread_bps"),
            ),
            "orderbook_depth_usd": first_present(
                row.get("orderbook_depth_usd"),
                row.get("expected_exit_depth_usd"),
                features.get("orderbook_depth_usd"),
                features.get("depth_usd"),
            ),
        },
    )
    oi_funding = context_payload(
        row,
        "OI_FUNDING",
        {
            "funding_bps": first_present(row.get("expected_funding_bps"), row.get("funding_bps"), features.get("funding_bps")),
            "funding_rate": first_present(row.get("funding_rate"), features.get("funding_rate")),
            "open_interest": first_present(row.get("open_interest"), features.get("open_interest")),
            "long_short_ratio": first_present(row.get("long_short_ratio"), features.get("long_short_ratio")),
        },
    )
    public_intel = context_payload(
        row,
        "PUBLIC_INTEL",
        {
            "public_intel_score": first_present(row.get("public_intel_score"), features.get("public_intel_score")),
            "sentiment_score": first_present(row.get("sentiment_score"), features.get("sentiment_score")),
        },
    )
    return {
        "liquidity_context": liquidity,
        "liquidity_zone_context": liquidity,
        "liquidation_distance_context": liquidation,
        "microstructure_context": microstructure,
        "oi_funding_context": oi_funding,
        "public_intel_context": public_intel,
        "major_move_context": context_payload(
            row,
            "MAJOR_MOVE",
            {"squeeze_evidence_score": row.get("squeeze_evidence_score")},
        ),
    }


def feedback_missing_fields(row: Mapping[str, Any]) -> tuple[list[str], list[str]]:
    missing_feedback = [field for field in REQUIRED_FEEDBACK_FIELDS if row.get(field) in (None, "")]
    missing_trust = [
        field
        for field in REQUIRED_TRUST_ENVELOPE_FIELDS
        if row.get(field) in (None, "") or (field == "source_hashes" and not isinstance(row.get(field), Mapping))
    ]
    return missing_feedback, missing_trust


def build_feedback_row(
    pending: Mapping[str, Any],
    *,
    exit_snapshot: Mapping[str, Any],
    label_close_time: datetime,
    generated_utc: str,
) -> dict[str, Any]:
    symbol = str(pending.get("symbol") or "").upper()
    timeframe = str(pending.get("timeframe") or "")
    side = str(pending.get("side") or "").strip().lower()
    entry_price = coerce_float(first_present(pending.get("entry_price"), pending.get("current_price")))
    exit_price = snapshot_price(exit_snapshot)
    notional_usd = coerce_float(pending.get("notional_usd"))
    expected_cost_usd = coerce_float(pending.get("expected_cost_usd"))
    assert entry_price is not None and exit_price is not None and notional_usd is not None
    cost_bps = abs(expected_cost_usd or 0.0) / notional_usd * 10_000.0
    price_return_bps = (exit_price - entry_price) / entry_price * 10_000.0
    signed_gross_bps = -price_return_bps if side == "short" else price_return_bps
    realized_net_bps = signed_gross_bps - cost_bps
    realized_net_usd = notional_usd * realized_net_bps / 10_000.0
    identity = row_identity(pending)
    feedback_id = "strategy_supply_feedback:" + hashlib.sha256(
        f"{identity}|{exit_snapshot.get('feature_cutoff')}|{exit_price}".encode("utf-8")
    ).hexdigest()[:24]
    feature_snapshot_id = first_present(pending.get("entry_feature_snapshot_id"), pending.get("feature_snapshot_id"))
    source_hashes = pending.get("source_hashes") if isinstance(pending.get("source_hashes"), Mapping) else {}
    if not source_hashes and isinstance(pending.get("provider_hashes"), Mapping):
        source_hashes = dict(pending.get("provider_hashes") or {})
    entry_snapshot = trainer_entry_feature_snapshot(pending)
    contexts = build_contexts(pending)
    market_regime = first_present(pending.get("market_regime"), pending.get("market_regime_at_entry"), "unknown")
    row: dict[str, Any] = {
        "schema_version": "strategy_supply_trainer_feedback_outcome_v1",
        "feedback_schema_version": "strategy_supply_shadow_outcome_feedback_v1",
        "trust_envelope_schema_version": "strategy_supply_shadow_feedback_trust_envelope_v1",
        "trainer_feedback_source": FEEDBACK_SOURCE,
        "trainer_feedback_id": feedback_id,
        "generated_utc": generated_utc,
        "prediction_id": first_present(pending.get("prediction_id"), pending.get("hypothesis_id"), pending.get("candidate_id")),
        "signal_id": first_present(pending.get("signal_id"), pending.get("candidate_id"), pending.get("hypothesis_id")),
        "feature_snapshot_id": feature_snapshot_id,
        "entry_feature_snapshot_id": feature_snapshot_id,
        "entry_feature_snapshot": entry_snapshot,
        "market_state_id": first_present(pending.get("market_state_id"), f"strategy_supply_market_state:{feature_snapshot_id}"),
        "timeframe": timeframe,
        "symbol": symbol,
        "side": side,
        "action": side,
        "selected_action": side,
        "entry_price": entry_price,
        "exit_price": exit_price,
        "realized_pnl": round(realized_net_usd, 10),
        "realized_pnl_usd": round(realized_net_usd, 10),
        "realized_net_pnl_usd": round(realized_net_usd, 10),
        "realized_pnl_bps": round(realized_net_bps, 10),
        "realized_net_pnl_bps": round(realized_net_bps, 10),
        "strategy_id": first_present(pending.get("strategy_id"), pending.get("hypothesis_id"), "strategy_supply_shadow"),
        "strategy_family": first_present(pending.get("strategy_family"), "strategy_supply_shadow"),
        "strategy_subtype": first_present(pending.get("strategy_subtype"), "shadow_candidate"),
        "hedge_state": first_present(pending.get("hedge_state"), "not_hedged"),
        "hedge_reason": first_present(pending.get("hedge_reason"), "strategy_supply_shadow_no_hedge"),
        "entry_reason": first_present(pending.get("entry_reason"), "strategy_supply_positive_hypothesis"),
        "exit_reason": "future_window_elapsed_closed_candle",
        "hold_time_seconds": int((label_close_time - parse_utc(pending.get("decision_time"))).total_seconds()),
        "market_regime_at_entry": market_regime,
        "market_regime_at_exit": first_present(exit_snapshot.get("market_regime"), market_regime),
        "market_regime": market_regime,
        "future_window_label_source": "strategy_supply_shadow_future_window_label",
        "drawdown_at_entry": first_present(pending.get("drawdown_at_entry"), 0.0),
        "directional_outcome": "UP" if exit_price > entry_price else "DOWN" if exit_price < entry_price else "FLAT",
        "trade_outcome": "WIN" if realized_net_usd > 0.0 else "LOSS" if realized_net_usd < 0.0 else "BREAKEVEN",
        "action_was_profitable": realized_net_usd > 0.0,
        "fees": coerce_float(pending.get("expected_fees_usd")) or 0.0,
        "slippage": coerce_float(pending.get("expected_slippage_usd")) or 0.0,
        "funding": coerce_float(pending.get("expected_funding_usd")) or 0.0,
        "expected_cost_usd": expected_cost_usd,
        "expected_cost_bps": round(cost_bps, 10),
        "mfe_bps": max(0.0, signed_gross_bps),
        "mae_bps": min(0.0, signed_gross_bps),
        "MFE": max(0.0, signed_gross_bps),
        "MAE": min(0.0, signed_gross_bps),
        "intra_trade_high_price": max(entry_price, exit_price),
        "intra_trade_low_price": min(entry_price, exit_price),
        "close_id": feedback_id,
        "outcome_label_id": feedback_id,
        "decision_id": first_present(
            pending.get("decision_id"),
            pending.get("guardian_decision_id"),
            pending.get("allocator_decision_id"),
            pending.get("hypothesis_id"),
            feedback_id,
        ),
        "mtf_snapshot_id": first_present(pending.get("mtf_snapshot_id"), feature_snapshot_id),
        "feature_cutoff": first_present(pending.get("feature_cutoff"), pending.get("entry_feature_cutoff")),
        "decision_time": pending.get("decision_time"),
        "available_at": first_present(pending.get("available_at"), pending.get("entry_feature_available_at")),
        "model_version": first_present(pending.get("model_version"), "strategy_supply_shadow_v1"),
        "checkpoint_id": first_present(pending.get("checkpoint_id"), "strategy_supply_shadow_no_checkpoint"),
        "source_hashes": dict(source_hashes),
        "candidate_selected_before_outcome": True,
        "candidate_selected_after_outcome": False,
        "post_outcome_candidate_selection": False,
        "future_labels_used_as_features": False,
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
        "paper_only": True,
        "places_real_order": False,
        "routes_to_live": False,
        "live_order": False,
        "test_order": False,
        "leverage_mutation": False,
        "margin_mode_mutation": False,
        "quarantine_reason": "NONE",
        "quarantine_reasons": [],
        "source_strategy_supply_shadow_evidence_only": True,
    }
    row.update(contexts)
    apply_trainer_gate_fields(row, entry_snapshot=entry_snapshot)
    missing_feedback, missing_trust = feedback_missing_fields(row)
    row["missing_feedback_fields"] = missing_feedback
    row["missing_trust_fields"] = missing_trust
    row["trainer_consumable"] = (
        not missing_feedback
        and not missing_trust
        and row.get("accepted_for_training") is True
        and not row.get("reject_reasons")
    )
    row["trainer_feedback_blockers"] = [
        *(f"MISSING_FEEDBACK_{field}" for field in missing_feedback),
        *(f"MISSING_TRUST_{field}" for field in missing_trust),
        *(f"TRAINING_GATE_{reason}" for reason in row.get("reject_reasons") or []),
    ]
    return row


def merge_feedback_rows_into_redis(client: Any | None, rows: list[dict[str, Any]]) -> int:
    if client is None or not rows:
        return 0
    existing_payload = read_redis_json(client, TRAINER_FEEDBACK_REDIS_KEY)
    existing = list(existing_payload) if isinstance(existing_payload, list) else []
    seen = {
        str(item.get("trainer_feedback_id"))
        for item in existing
        if isinstance(item, Mapping) and item.get("trainer_feedback_id") not in (None, "")
    }
    added = 0
    for row in rows:
        feedback_id = str(row.get("trainer_feedback_id") or "")
        if not feedback_id or feedback_id in seen:
            continue
        existing.append(row)
        seen.add(feedback_id)
        added += 1
    if added:
        client.set(TRAINER_FEEDBACK_REDIS_KEY, json.dumps(existing, sort_keys=True))
    return added


def mature_strategy_supply_feedback(
    *,
    pending_path: Path,
    matured_path: Path,
    rejected_path: Path,
    status_path: Path | None = None,
    redis_client: Any | None = None,
    now: datetime | None = None,
    publish_to_redis: bool = False,
) -> dict[str, Any]:
    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    generated_utc = utc_iso(now_dt)
    pending_rows = load_jsonl(pending_path)
    existing_matured_rows = load_jsonl(matured_path)
    existing_matured = {row_identity(row) for row in existing_matured_rows}
    existing_rejected = {row_identity(row) for row in load_jsonl(rejected_path)}
    feedback_rows: list[dict[str, Any]] = []
    for row in existing_matured_rows:
        feedback_row = trainer_feedback_row_for_publish(row)
        if feedback_row is not None and feedback_row.get("trainer_consumable") is True:
            feedback_rows.append(feedback_row)
    status = {
        "schema_version": "strategy_supply_feedback_maturation_status_v1",
        "generated_utc": generated_utc,
        "pending_path": str(pending_path),
        "matured_path": str(matured_path),
        "rejected_path": str(rejected_path),
        "pending_rows": len(pending_rows),
        "pending_rows_waiting_for_label": 0,
        "matured_rows": len(existing_matured_rows),
        "new_matured_rows_appended": 0,
        "positive_outcomes": sum(
            1 for row in existing_matured_rows if row.get("trade_outcome") == "WIN"
        ),
        "negative_outcomes": sum(
            1 for row in existing_matured_rows if row.get("trade_outcome") == "LOSS"
        ),
        "dirty_rows_excluded": 0,
        "future_leakage_violations": 0,
        "trainer_feedback_rows_ready": len(feedback_rows),
        "existing_matured_trainer_feedback_rows_ready": len(feedback_rows),
        "trainer_feedback_rows_published_to_redis": 0,
        "PPO_rows_consumed": 0,
        "MASA_rows_consumed": 0,
        "checkpoint_after_consumption": None,
        "consumption_note": "Rows are published for the next trainer loader cycle; this tool does not run PPO/MASA training.",
        "counts_as_a_plus": False,
        "counts_as_live_ready": False,
    }
    for row in pending_rows:
        identity = row_identity(row)
        if identity in existing_matured:
            continue
        decision_time = parse_utc(row.get("decision_time"))
        delta = timeframe_delta(row.get("timeframe"))
        entry_reasons = entry_snapshot_rejection_reasons(row)
        numeric_reasons: list[str] = []
        if coerce_float(first_present(row.get("entry_price"), row.get("current_price"))) is None:
            numeric_reasons.append("MISSING_ENTRY_PRICE")
        if coerce_float(row.get("notional_usd")) is None:
            numeric_reasons.append("MISSING_NOTIONAL_USD")
        if coerce_float(row.get("expected_cost_usd")) is None:
            numeric_reasons.append("MISSING_EXPECTED_COST_USD")
        if decision_time is None or delta is None:
            numeric_reasons.append("MISSING_LABEL_WINDOW")
        dirty_reasons = sorted(set(entry_reasons + numeric_reasons))
        if dirty_reasons:
            status["dirty_rows_excluded"] += 1
            if any("AFTER_DECISION_TIME" in reason for reason in dirty_reasons):
                status["future_leakage_violations"] += 1
            if identity not in existing_rejected:
                append_jsonl(
                    rejected_path,
                    {
                        "schema_version": "strategy_supply_maturation_rejected_evidence_v1",
                        "generated_utc": generated_utc,
                        "candidate_identity": identity,
                        "hypothesis_id": row.get("hypothesis_id"),
                        "candidate_id": row.get("candidate_id"),
                        "symbol": row.get("symbol"),
                        "timeframe": row.get("timeframe"),
                        "side": row.get("side"),
                        "decision_time": row.get("decision_time"),
                        "reasons": dirty_reasons,
                        "counts_as_a_plus": False,
                        "counts_as_live_ready": False,
                    },
                )
                existing_rejected.add(identity)
            continue
        assert decision_time is not None and delta is not None
        label_close_time = decision_time + delta
        if now_dt < label_close_time:
            status["pending_rows_waiting_for_label"] += 1
            continue
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        exit_snapshot = latest_exit_snapshot(redis_client, symbol, timeframe)
        exit_reasons = exit_snapshot_rejection_reasons(
            exit_snapshot,
            label_close_time=label_close_time,
            now=now_dt,
        )
        if exit_reasons:
            status["pending_rows_waiting_for_label"] += 1
            continue
        assert isinstance(exit_snapshot, Mapping)
        feedback_row = build_feedback_row(
            row,
            exit_snapshot=exit_snapshot,
            label_close_time=label_close_time,
            generated_utc=generated_utc,
        )
        matured_record = {
            **dict(row),
            "schema_version": "strategy_supply_matured_evidence_v1",
            "generated_utc": generated_utc,
            "outcome_label_status": "MATURED_FROM_CLOSED_FUTURE_WINDOW",
            "label_close_time": utc_iso(label_close_time),
            "exit_feature_cutoff": exit_snapshot.get("feature_cutoff"),
            "exit_available_at": first_present(exit_snapshot.get("available_at"), exit_snapshot.get("generated_at")),
            "exit_price": feedback_row.get("exit_price"),
            "realized_net_pnl_usd": feedback_row.get("realized_net_pnl_usd"),
            "realized_net_pnl_bps": feedback_row.get("realized_net_pnl_bps"),
            "directional_outcome": feedback_row.get("directional_outcome"),
            "trade_outcome": feedback_row.get("trade_outcome"),
            "trainer_feedback_id": feedback_row.get("trainer_feedback_id"),
            "trainer_feedback_row": feedback_row,
            "future_labels_used_as_features": False,
            "counts_as_a_plus": False,
            "counts_as_live_ready": False,
        }
        append_jsonl(matured_path, matured_record)
        existing_matured.add(identity)
        feedback_rows.append(feedback_row)
        status["matured_rows"] += 1
        status["new_matured_rows_appended"] += 1
        if feedback_row.get("trade_outcome") == "WIN":
            status["positive_outcomes"] += 1
        elif feedback_row.get("trade_outcome") == "LOSS":
            status["negative_outcomes"] += 1
        if feedback_row.get("trainer_consumable") is True:
            status["trainer_feedback_rows_ready"] += 1
    if publish_to_redis:
        status["trainer_feedback_rows_published_to_redis"] = merge_feedback_rows_into_redis(
            redis_client,
            [row for row in feedback_rows if row.get("trainer_consumable") is True],
        )
    if status_path is not None:
        status_path.parent.mkdir(parents=True, exist_ok=True)
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n")
    if redis_client is not None:
        try:
            redis_client.set(MATURATION_STATUS_REDIS_KEY, json.dumps(status, sort_keys=True))
        except Exception:
            pass
    return status
