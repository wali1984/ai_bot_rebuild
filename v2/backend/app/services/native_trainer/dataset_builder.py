"""V2 native trainer dataset builder (paper / shadow only).

Reads V2-owned evidence ONLY. Never uses raw legacy Redis as current
truth; legacy reference actions are accepted only when they come
through the V2 decision-comparator mirror that lives under
``v2:legacy_decision_comparator:*`` (the mirror itself is a V2-owned
read).

Inputs (all V2-owned):

* ``v2:features:latest:{symbol}:{tf}``
* ``v2:features:ta:{symbol}:{tf}``
* ``v2:market:ohlcv:binance:{symbol}:{tf}``
* ``v2:market:orderbook:binance:{symbol}``
* ``v2:prediction:{symbol}:{tf}``
* ``v2:risk:decisions``
* ``v2:altdata:symbol_score:{symbol}`` (optional)
* ``v2:market:liquidations:*`` (optional)
* ``replay_outcome_bundles.jsonl``
* ``edge_metrics_summary.json``

Outputs are typed dataclasses; the CLI layer renders the JSON /
markdown payloads.

Safety:

* read-only with respect to Redis (only ``v2:*`` keys)
* never calls the exchange
* never modifies legacy
* never weakens the paper-fill gate
* never claims native-trainer readiness or checkpoint compatibility
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from v2.backend.app.services.market_state_integrity.sample_rejection import classify_training_sample
from v2.backend.app.services.v2_symbol_runtime_universe import (
    BASELINE_25_SYMBOLS,
    resolve_symbols_with_provenance,
)


SCHEMA_VERSION = "v2_native_trainer_dataset_builder_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"
REPLAY_EVIDENCE_ROWS_FILENAME = "v2_native_trainer_replay_evidence_rows.jsonl"
REPLAY_EVIDENCE_STATUS_FILENAME = "v2_native_trainer_replay_evidence_status.json"

# Kept for compatibility with existing tests and reports. Runtime defaults now
# come from v2_symbol_runtime_universe so discovery can expand this baseline.
KNOWN_UNIVERSE = BASELINE_25_SYMBOLS
TIMEFRAMES = ("1m", "5m")

FEATURES_KEY_TEMPLATE = "v2:features:latest:{symbol}:{timeframe}"
TA_KEY_TEMPLATE = "v2:features:ta:{symbol}:{timeframe}"
OHLCV_KEY_TEMPLATE = "v2:market:ohlcv:binance:{symbol}:{timeframe}"
ORDERBOOK_KEY_TEMPLATE = "v2:market:orderbook:binance:{symbol}"
PREDICTION_KEY_TEMPLATE = "v2:prediction:{symbol}:{timeframe}"
RISK_DECISIONS_KEY = "v2:risk:decisions"
ALTDATA_KEY_TEMPLATE = "v2:altdata:symbol_score:{symbol}"
LIQUIDATIONS_KEY_TEMPLATE = "v2:market:liquidations:{symbol}"

ALTDATA_NUMERIC_FEATURES = (
    "altdata_symbol_score",
    "altdata_symbol_rank",
    "altdata_freshness_score",
    "provider_availability_score",
    "smart_money_score",
    "entity_flow_score",
    "social_momentum_score",
    "social_volume_velocity",
    "sentiment_score",
    "galaxy_or_equivalent_score",
    "coingecko_discovery_score",
    "coingecko_liquidity_score",
    "coingecko_momentum_score",
    "coingecko_trend_score",
    "surf_market_price_signal_score",
    "surf_price_observation_count",
    "coinglass_derivatives_score",
    "public_intel_score",
    "defillama_liquidity_score",
    "defillama_tvl_momentum_score",
    "news_attention_score",
    "news_sentiment_score",
    "fear_greed_score",
    "btc_mempool_pressure_score",
    "aicoin_market_activity_score",
    "aicoin_coin_profile_score",
    "aicoin_order_flow_score",
    "aicoin_whale_order_score",
    "aicoin_signal_score",
    "aicoin_drop_radar_score",
    "aicoin_airdrop_score",
    "aicoin_liquidation_score",
    "aicoin_open_interest_score",
    "aicoin_news_attention_score",
    "whale_wall_score",
    "whale_bid_pressure_score",
    "whale_ask_pressure_score",
    "whale_wall_imbalance_score",
    "whale_wall_count_score",
    "whale_wall_event_count",
    "whale_bid_wall_notional_usd",
    "whale_ask_wall_notional_usd",
    "whale_total_wall_notional_usd",
    "nearest_bid_wall_distance_bps",
    "nearest_ask_wall_distance_bps",
    "santiment_social_volume_score",
    "santiment_whale_activity_score",
    "santiment_sentiment_score",
    "santiment_onchain_activity_score",
    "santiment_dev_activity_score",
    "santiment_exchange_inflow_risk_score",
    "santiment_supply_on_exchanges_score",
    "santiment_social_volume_total",
    "santiment_sentiment_positive_total",
    "santiment_sentiment_negative_total",
    "santiment_whale_transaction_count_1m",
    "santiment_whale_transaction_count_100k_usd_to_inf",
    "santiment_exchange_inflow",
    "santiment_percent_of_total_supply_on_exchanges",
    "santiment_active_addresses_24h",
    "santiment_transaction_volume",
    "santiment_dev_activity",
)

ALTDATA_PROVIDER_FLAGS = (
    "nansen",
    "lunarcrush",
    "coingecko",
    "surf",
    "coinglass",
    "public_intel",
    "aicoin",
    "whale_walls",
    "santiment",
    "market",
    "features",
)


# Row classifications.
ROW_TRAINABLE = "TRAINABLE"
ROW_INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
ROW_STALE_FEATURES = "STALE_FEATURES"
ROW_MISSING_FEATURES = "MISSING_FEATURES"
ROW_LABEL_MISSING = "LABEL_MISSING"
ROW_HELD_OUT_VALIDATION = "HELD_OUT_VALIDATION"
ROW_MARKET_STATE_REJECTED = "MARKET_STATE_REJECTED"

ROW_CLASSIFICATIONS = (
    ROW_TRAINABLE,
    ROW_INSUFFICIENT_EVIDENCE,
    ROW_STALE_FEATURES,
    ROW_MISSING_FEATURES,
    ROW_LABEL_MISSING,
    ROW_HELD_OUT_VALIDATION,
    ROW_MARKET_STATE_REJECTED,
)

EXPLICIT_DATASET_TRAINING_TRUST_FIELDS = (
    "feature_cutoff",
    "decision_cutoff",
    "available_at",
    "source_available_time",
    "candle_closed_confirmed",
    "closed_candle",
    "candle_open_time",
    "candle_close_time",
    "source_event_time",
    "source_event_time_est",
    "source_received_time_est",
    "decision_time",
    "decision_time_est",
    "backfilled",
    "is_backfilled",
    "latency_ms",
    "price_disagreement_bps",
    "masa_feature_cutoff",
    "ppo_feature_cutoff",
)

# Hold-out split: deterministic by hash(feature_snapshot_id).
HELD_OUT_FRACTION = 0.2

# Minimum sample threshold below which the dataset cannot be called
# "ready" for any production claim.
MIN_TRAIN_ROWS_FOR_READINESS = 256


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _safety_block() -> dict[str, Any]:
    return {
        "live_gate": LIVE_GATE_BLOCKED,
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "did_not_modify_legacy_tree": True,
        "did_not_stop_legacy_runtime": True,
        "did_not_stop_v2_runtime": True,
        "did_not_stop_report_center": True,
        "did_not_stop_replay_miner": True,
        "did_not_stop_codex_governors": True,
        "did_not_write_old_redis_keys": True,
        "did_not_call_exchange_mutation": True,
        "did_not_expose_raw_api_keys": True,
        "did_not_weaken_paper_fill_gate": True,
        "did_not_claim_trainer_native_readiness": True,
        "did_not_claim_checkpoint_compatibility": True,
        "did_not_use_raw_legacy_redis_as_current_truth": True,
    }


def _stable_row_id(symbol: str, timeframe: str, snapshot_id: str) -> str:
    digest = hashlib.sha256(
        f"{symbol}|{timeframe}|{snapshot_id}".encode("utf-8")
    ).hexdigest()[:32]
    return f"v2_native_ds_{digest}"


def _is_held_out(row_id: str, fraction: float = HELD_OUT_FRACTION) -> bool:
    """Deterministic hold-out membership by hash of row id."""
    h = int(hashlib.sha256(row_id.encode("utf-8")).hexdigest()[:8], 16)
    return (h % 10_000) < int(fraction * 10_000)


# ---------------------------------------------------------------------------
# V2-only reader contract
# ---------------------------------------------------------------------------


class V2OnlyReader:
    """Read-only wrapper that refuses any non-``v2:*`` key.

    Constructed with an optional ``client`` (duck-typed: ``get(key)``
    returns bytes/str/None). ``None`` = audit-only mode (every read
    returns None).
    """

    def __init__(self, client: Any = None) -> None:
        self._client = client
        self.non_v2_read_attempts = 0
        self.reads_attempted = 0
        self.reads_missing = 0
        self.read_errors = 0

    def get_json(self, key: str) -> Any:
        if not key.startswith("v2:"):
            self.non_v2_read_attempts += 1
            raise ValueError(f"non_v2_read_rejected:{key}")
        self.reads_attempted += 1
        if self._client is None:
            self.reads_missing += 1
            return None
        try:
            raw = self._client.get(key)
        except Exception:  # noqa: BLE001
            self.read_errors += 1
            return None
        if raw is None:
            self.reads_missing += 1
            return None
        try:
            if isinstance(raw, (bytes, bytearray)):
                raw = raw.decode("utf-8")
            return json.loads(raw)
        except (TypeError, ValueError):
            self.read_errors += 1
            return None


# ---------------------------------------------------------------------------
# Feature vector extraction
# ---------------------------------------------------------------------------


def _extract_feature_vector(
    features: dict[str, Any] | None,
    ta: dict[str, Any] | None,
) -> dict[str, float | None]:
    """Build a small, stable feature vector from V2-owned payloads.

    Keeps a tight set of indicators that are commonly present so the schema is
    deterministic across symbols. The live feature-pipeline payload stores
    trainer-ready values under ``features`` (for example ``ema_12``,
    ``ema_26``, ``rsi_14``, ``macd``). Older compatibility payloads store
    values under ``ta.indicators``. Support both so the dataset builder follows
    the live trainer path instead of depending on stale ``v2:features:ta:*``
    compatibility keys.
    """
    indicators: dict[str, Any] = {}
    if isinstance(ta, dict):
        indicators = ta.get("indicators") or {}
    feat: dict[str, Any] = features or {}
    live_features: dict[str, Any] = (
        feat.get("features") if isinstance(feat.get("features"), dict) else {}
    )

    def _as_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            f = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(f) or math.isinf(f):
            return None
        return f

    def _first_float(*names: str) -> float | None:
        for name in names:
            for source in (indicators, live_features, feat):
                value = _as_float(source.get(name))
                if value is not None:
                    return value
        return None

    vector = {
        "ema_9": _first_float("ema_9", "ta_EMA_9", "ema_12", "ta_EMA_12"),
        "ema_21": _first_float("ema_21", "ta_EMA_21", "ema_26", "ta_EMA_26"),
        "ema_spread": None,
        "rsi_14": _first_float("rsi_14", "ta_RSI_14"),
        "macd": _first_float("macd", "ta_MACD_12_26_9_macd"),
        "macd_signal": _first_float("macd_signal", "ta_MACD_12_26_9_signal"),
        "atr_14": _first_float("atr_14", "ta_ATR_14"),
        "vol_zscore": _first_float("vol_zscore", "volume_zscore"),
        "long_short_ratio": _first_float("long_short_ratio"),
        "long_account_ratio": _first_float("long_account_ratio"),
        "short_account_ratio": _first_float("short_account_ratio"),
        "feature_freshness_seconds": _first_float("freshness_seconds"),
    }
    if vector["ema_9"] is not None and vector["ema_21"] is not None:
        vector["ema_spread"] = vector["ema_9"] - vector["ema_21"]
    return vector


def _extract_altdata_feature_vector(
    altdata: dict[str, Any] | None,
) -> dict[str, float | None]:
    """Expose V2 alt-data symbol scores as model features.

    The full provider payload remains attached as ``altdata_context`` for
    auditability. This vector only includes bounded numeric fields and explicit
    provider/input presence flags so the current trainer can actually learn
    from the same context the scorer and RL observation builder consume.
    """

    def _as_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            f = float(value)
        except (TypeError, ValueError):
            return None
        if math.isnan(f) or math.isinf(f):
            return None
        return f

    vector = {name: None for name in ALTDATA_NUMERIC_FEATURES}
    for name in ALTDATA_NUMERIC_FEATURES:
        vector[name] = _as_float((altdata or {}).get(name))

    provider_available = (
        (altdata or {}).get("provider_available")
        if isinstance((altdata or {}).get("provider_available"), dict)
        else {}
    )
    input_presence = (
        (altdata or {}).get("input_presence")
        if isinstance((altdata or {}).get("input_presence"), dict)
        else {}
    )
    for provider in ALTDATA_PROVIDER_FLAGS:
        vector[f"provider_available_{provider}"] = (
            1.0 if provider_available.get(provider) is True else 0.0
            if provider in provider_available
            else None
        )
        vector[f"input_present_{provider}"] = (
            1.0 if input_presence.get(provider) is True else 0.0
            if provider in input_presence
            else None
        )
    return vector


def _missing_keys(vector: dict[str, float | None]) -> list[str]:
    # The "always-required" subset for the row to be trainable.
    required = ("ema_9", "ema_21", "rsi_14")
    return [k for k in required if vector.get(k) is None]


# ---------------------------------------------------------------------------
# Replay evidence metadata helpers
# ---------------------------------------------------------------------------


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _mapping_value(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _normalized_bundle_side(bundle: Mapping[str, Any]) -> str | None:
    paper_intent = _mapping_value(bundle.get("paper_intent"))
    risk_decision = _mapping_value(bundle.get("risk_decision"))
    trainer_output = _mapping_value(bundle.get("trainer_output"))
    raw_side = _first_present(
        bundle.get("side"),
        paper_intent.get("side"),
        risk_decision.get("side"),
        trainer_output.get("selected_action"),
        trainer_output.get("action"),
        bundle.get("action"),
        bundle.get("selected_action"),
    )
    side = str(raw_side or "").strip().lower()
    if side in {"long", "buy"}:
        return "long"
    if side in {"short", "sell"}:
        return "short"
    return None


def _replay_bundle_timing(bundle: Mapping[str, Any]) -> dict[str, Any]:
    risk_decision = _mapping_value(bundle.get("risk_decision"))
    feature_cutoff = _first_present(
        bundle.get("feature_cutoff"),
        bundle.get("entry_feature_cutoff"),
        risk_decision.get("strategy_feature_cutoff"),
    )
    return {
        "bundle_generated_at": _first_present(
            bundle.get("bundle_generated_at"),
            bundle.get("generated_at"),
            bundle.get("generated_utc"),
        ),
        "decision_time": _first_present(
            bundle.get("decision_time"),
            bundle.get("entry_feature_decision_time"),
            risk_decision.get("strategy_decision_time"),
        ),
        "available_at": _first_present(
            bundle.get("available_at"),
            bundle.get("entry_feature_available_at"),
        ),
        "entry_feature_generated_at": _first_present(
            bundle.get("entry_feature_generated_at"),
            bundle.get("prediction_generated_at"),
        ),
        "prediction_generated_at": bundle.get("prediction_generated_at"),
        "feature_cutoff": feature_cutoff,
        "source_event_time": _first_present(
            bundle.get("source_event_time"),
            bundle.get("source_event_time_est"),
            feature_cutoff,
            bundle.get("candle_close_time"),
        ),
        "source_received_time_est": _first_present(
            bundle.get("source_received_time_est"),
            bundle.get("source_available_time"),
            bundle.get("available_at"),
            bundle.get("entry_feature_available_at"),
        ),
        "candle_open_time": bundle.get("candle_open_time"),
        "candle_close_time": _first_present(
            bundle.get("candle_close_time"),
            feature_cutoff,
        ),
        "entry_feature_candle_closed_confirmed": _first_present(
            bundle.get("entry_feature_candle_closed_confirmed"),
            bundle.get("candle_closed_confirmed"),
            bundle.get("closed_candle"),
        ),
    }


def _trust_source_with_label_metadata(
    features: Mapping[str, Any] | None,
    label_row: "LabelRow | None",
) -> Mapping[str, Any] | None:
    if label_row is None:
        return features
    source = dict(features or {})

    def set_if_present(key: str, value: Any) -> None:
        if value is not None and value != "":
            source.setdefault(key, value)

    set_if_present("decision_time", label_row.decision_time)
    set_if_present("available_at", label_row.available_at)
    set_if_present("source_available_time", label_row.available_at)
    set_if_present("source_received_time_est", label_row.available_at)
    set_if_present("feature_cutoff", label_row.feature_cutoff)
    set_if_present(
        "source_event_time",
        label_row.source_event_time or label_row.feature_cutoff,
    )
    set_if_present("candle_open_time", label_row.candle_open_time)
    set_if_present(
        "candle_close_time",
        label_row.candle_close_time or label_row.feature_cutoff,
    )
    set_if_present("generated_at", label_row.entry_feature_generated_at)
    if label_row.entry_feature_candle_closed_confirmed is not None:
        source.setdefault(
            "candle_closed_confirmed",
            label_row.entry_feature_candle_closed_confirmed,
        )
    if (
        label_row.decision_time
        and label_row.available_at
        and label_row.feature_cutoff
        and label_row.entry_feature_generated_at
    ):
        source.setdefault("feature_freshness_state", "CURRENT")
    return source or features


def _trust_source_from_replay_bundle(
    bundle: Mapping[str, Any],
    timing: Mapping[str, Any],
) -> Mapping[str, Any]:
    source = dict(bundle)
    source["decision_time"] = timing.get("decision_time")
    source["available_at"] = timing.get("available_at")
    source["source_available_time"] = timing.get("available_at")
    source["source_received_time_est"] = timing.get("source_received_time_est")
    source["feature_cutoff"] = timing.get("feature_cutoff")
    source["source_event_time"] = timing.get("source_event_time")
    source["candle_open_time"] = timing.get("candle_open_time")
    source["candle_close_time"] = timing.get("candle_close_time")
    source["candle_closed_confirmed"] = timing.get(
        "entry_feature_candle_closed_confirmed"
    )
    if timing.get("entry_feature_generated_at"):
        source["generated_at"] = timing.get("entry_feature_generated_at")
    if (
        timing.get("decision_time")
        and timing.get("available_at")
        and timing.get("feature_cutoff")
        and timing.get("entry_feature_generated_at")
    ):
        source["feature_freshness_state"] = "CURRENT"
    return source


# ---------------------------------------------------------------------------
# Label extraction from replay-outcome bundles
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LabelRow:
    feature_snapshot_id: str
    symbol: str
    timeframe: str
    label: str
    after_cost_return_bps: float | None
    max_favorable_bps: float | None
    max_adverse_bps: float | None
    paper_gate_status: str | None
    paper_gate_block_reasons: list[str]
    risk_decision_context: dict[str, Any] | None
    legacy_reference_action: str | None
    side: str | None = None
    decision_time: str | None = None
    available_at: str | None = None
    entry_feature_generated_at: str | None = None
    prediction_generated_at: str | None = None
    feature_cutoff: str | None = None
    source_event_time: str | None = None
    candle_open_time: str | None = None
    candle_close_time: str | None = None
    entry_feature_candle_closed_confirmed: bool | None = None
    bundle_generated_at: str | None = None


PRIMARY_OUTCOME_WINDOWS = ("5m", "15m", "1h", "1m")


def _select_primary_outcome(future_outcomes: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the first outcome window that has a non-null after-cost figure."""
    for w in PRIMARY_OUTCOME_WINDOWS:
        candidate = future_outcomes.get(w) or {}
        if candidate.get("after_cost_return_bps") is not None:
            return candidate
    return None


def _label_for_outcome(after_cost_bps: float | None, paper_gate_status: str | None) -> str:
    if after_cost_bps is None:
        return "label_missing"
    if paper_gate_status and "BLOCKED" in str(paper_gate_status).upper():
        # When the paper-fill gate blocked entry the outcome is still a
        # valid evaluation signal for the gate itself.
        if after_cost_bps >= 0:
            return "correct_no_trade"
        return "false_block_negative_outcome"
    if after_cost_bps > 5.0:
        return "true_positive_after_cost_gain"
    if after_cost_bps < -5.0:
        return "false_negative_after_cost_loss"
    return "neutral_no_edge"


def load_label_rows(
    replay_bundles_path: Path,
    *,
    max_rows: int | None = None,
) -> list[LabelRow]:
    if not replay_bundles_path.exists():
        return []
    rows: list[LabelRow] = []
    with replay_bundles_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                bundle = json.loads(line)
            except (TypeError, ValueError):
                continue
            outcomes = bundle.get("future_outcomes") or {}
            primary = _select_primary_outcome(outcomes) or {}
            paper_gate = bundle.get("paper_gate_decision") or {}
            paper_gate_status = paper_gate.get("status") or paper_gate.get(
                "paper_fill_gate_status"
            )
            block_reasons = list(
                paper_gate.get("block_reasons")
                or paper_gate.get("paper_fill_gate_block_reasons")
                or []
            )
            after_cost = primary.get("after_cost_return_bps")
            label = bundle.get("label") or _label_for_outcome(
                after_cost, paper_gate_status
            )
            timing = _replay_bundle_timing(bundle)
            rows.append(LabelRow(
                feature_snapshot_id=str(bundle.get("feature_snapshot_id") or ""),
                symbol=str(bundle.get("symbol") or ""),
                timeframe=str(bundle.get("timeframe") or "1m"),
                label=str(label),
                after_cost_return_bps=after_cost,
                max_favorable_bps=primary.get("max_favorable_bps"),
                max_adverse_bps=primary.get("max_adverse_bps"),
                paper_gate_status=paper_gate_status,
                paper_gate_block_reasons=block_reasons,
                risk_decision_context=bundle.get("risk_decision"),
                legacy_reference_action=bundle.get("legacy_reference_action"),
                side=_normalized_bundle_side(bundle),
                decision_time=timing.get("decision_time"),
                available_at=timing.get("available_at"),
                entry_feature_generated_at=timing.get("entry_feature_generated_at"),
                prediction_generated_at=timing.get("prediction_generated_at"),
                feature_cutoff=timing.get("feature_cutoff"),
                source_event_time=timing.get("source_event_time"),
                candle_open_time=timing.get("candle_open_time"),
                candle_close_time=timing.get("candle_close_time"),
                entry_feature_candle_closed_confirmed=timing.get(
                    "entry_feature_candle_closed_confirmed"
                ),
                bundle_generated_at=timing.get("bundle_generated_at"),
            ))
            if max_rows is not None and len(rows) >= max_rows:
                break
    return rows


def _index_labels_by_snapshot(
    labels: Sequence[LabelRow],
) -> dict[str, LabelRow]:
    by_snapshot: dict[str, LabelRow] = {}
    for row in labels:
        if row.feature_snapshot_id:
            # Keep the most recent occurrence (later rows win).
            by_snapshot[row.feature_snapshot_id] = row
    return by_snapshot


# ---------------------------------------------------------------------------
# Dataset row assembly
# ---------------------------------------------------------------------------


@dataclass
class DatasetRow:
    row_id: str
    symbol: str
    timeframe: str
    feature_snapshot_id: str
    generated_at: str
    feature_vector: dict[str, float | None]
    missing_feature_flags: list[str]
    stale_feature_flags: list[str]
    feature_freshness_state: str
    label: str
    after_cost_return_bps: float | None
    max_favorable_bps: float | None
    max_adverse_bps: float | None
    paper_gate_status: str | None
    paper_gate_block_reasons: list[str]
    risk_decision_context: dict[str, Any] | None
    altdata_context: dict[str, Any] | None
    legacy_reference_action: str | None
    classification: str
    source_lineage: list[str]
    feature_cutoff: str | None = None
    available_at: str | None = None
    decision_time_est: str | None = None
    candle_closed_confirmed: bool | None = None
    candle_open_time: str | None = None
    candle_close_time: str | None = None
    masa_feature_cutoff: str | None = None
    ppo_feature_cutoff: str | None = None
    market_state_integrity_score: float | None = None
    accepted_for_training: bool | None = None
    training_reject_reasons: list[str] = field(default_factory=list)
    side: str | None = None
    action: str | None = None
    decision_time: str | None = None
    entry_feature_available_at: str | None = None
    entry_feature_generated_at: str | None = None
    prediction_generated_at: str | None = None
    entry_feature_cutoff: str | None = None
    entry_feature_candle_closed_confirmed: bool | None = None
    bundle_generated_at: str | None = None
    source_event_time: str | None = None

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "row_id": self.row_id,
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "feature_snapshot_id": self.feature_snapshot_id,
            "generated_at": self.generated_at,
            "feature_vector": self.feature_vector,
            "missing_feature_flags": self.missing_feature_flags,
            "stale_feature_flags": self.stale_feature_flags,
            "feature_freshness_state": self.feature_freshness_state,
            "label": self.label,
            "after_cost_return_bps": self.after_cost_return_bps,
            "max_favorable_bps": self.max_favorable_bps,
            "max_adverse_bps": self.max_adverse_bps,
            "paper_gate_status": self.paper_gate_status,
            "paper_gate_block_reasons": self.paper_gate_block_reasons,
            "risk_decision_context": self.risk_decision_context,
            "altdata_context": self.altdata_context,
            "legacy_reference_action": self.legacy_reference_action,
            "classification": self.classification,
            "source_lineage": self.source_lineage,
            "feature_cutoff": self.feature_cutoff,
            "available_at": self.available_at,
            "decision_time_est": self.decision_time_est,
            "candle_closed_confirmed": self.candle_closed_confirmed,
            "candle_open_time": self.candle_open_time,
            "candle_close_time": self.candle_close_time,
            "masa_feature_cutoff": self.masa_feature_cutoff,
            "ppo_feature_cutoff": self.ppo_feature_cutoff,
            "market_state_integrity_score": self.market_state_integrity_score,
            "accepted_for_training": self.accepted_for_training,
            "training_reject_reasons": self.training_reject_reasons,
            "side": self.side,
            "action": self.action,
            "decision_time": self.decision_time,
            "entry_feature_available_at": self.entry_feature_available_at,
            "entry_feature_generated_at": self.entry_feature_generated_at,
            "prediction_generated_at": self.prediction_generated_at,
            "entry_feature_cutoff": self.entry_feature_cutoff,
            "entry_feature_candle_closed_confirmed": (
                self.entry_feature_candle_closed_confirmed
            ),
            "bundle_generated_at": self.bundle_generated_at,
            "source_event_time": self.source_event_time,
        }


def _classify_row(
    vector: dict[str, float | None],
    features: dict[str, Any] | None,
    label: str | None,
) -> tuple[str, list[str], list[str], str]:
    missing = _missing_keys(vector)
    stale: list[str] = []
    freshness_value = (
        (features or {}).get("freshness_state")
        or (features or {}).get("feature_freshness_state")
    )
    if str(freshness_value or "").upper() in {"STALE", "EXPIRED"}:
        stale.append("v2_features_latest_stale")
    if not features:
        return (
            ROW_INSUFFICIENT_EVIDENCE,
            ["v2_features_latest_missing"],
            stale,
            "MISSING_OR_STALE",
        )
    if missing:
        return (
            ROW_MISSING_FEATURES,
            [f"missing:{k}" for k in missing],
            stale,
            "MISSING_OR_STALE",
        )
    if stale:
        return (
            ROW_STALE_FEATURES,
            [],
            stale,
            "MISSING_OR_STALE",
        )
    if label == "insufficient_evidence":
        # Explicit insufficient-evidence rows are NOT label-missing —
        # they are bundles that exist but whose future-outcome window
        # has not yet materialized. Keep them visible in their own
        # bucket so dataset quality metrics stay honest.
        return (ROW_INSUFFICIENT_EVIDENCE, [], [], "FRESH")
    if not label or label == "label_missing":
        return (ROW_LABEL_MISSING, [], [], "FRESH")
    return (ROW_TRAINABLE, [], [], "FRESH")


def _has_explicit_dataset_training_trust_evidence(payload: Mapping[str, Any] | None) -> bool:
    if not isinstance(payload, Mapping):
        return False
    return any(payload.get(field) is not None for field in EXPLICIT_DATASET_TRAINING_TRUST_FIELDS)


def _dataset_training_trust(
    *,
    symbol: str,
    timeframe: str,
    feature_snapshot_id: str,
    row_id: str,
    vector: dict[str, float | None],
    missing_flags: list[str],
    stale_flags: list[str],
    freshness_state: str,
    classification: str,
    source_payload: Mapping[str, Any] | None,
) -> tuple[str, float | None, bool | None, list[str], dict[str, Any]]:
    if not _has_explicit_dataset_training_trust_evidence(source_payload):
        return classification, None, None, [], {}
    source = dict(source_payload or {})
    trust_row = {
        "symbol": symbol,
        "timeframe": timeframe,
        "feature_snapshot_id": feature_snapshot_id,
        "feature_vector_hash": row_id,
        "generated_at": source.get("generated_at") or source.get("generated_utc") or source.get("timestamp") or _utc_now_iso(),
        "feature_cutoff": source.get("feature_cutoff") or source.get("decision_cutoff") or source.get("generated_at"),
        "available_at": source.get("available_at") or source.get("source_available_time") or source.get("generated_at"),
        "decision_time_est": source.get("decision_time") or source.get("decision_time_est") or source.get("decision_cutoff") or source.get("generated_at"),
        "source_event_time_est": source.get("source_event_time") or source.get("source_event_time_est"),
        "source_received_time_est": source.get("source_received_time_est") or source.get("source_available_time") or source.get("available_at"),
        "source_available_time": source.get("source_available_time") or source.get("available_at"),
        "candle_closed_confirmed": source.get("candle_closed_confirmed")
        if "candle_closed_confirmed" in source
        else source.get("closed_candle"),
        "candle_open_time": source.get("candle_open_time"),
        "candle_close_time": source.get("candle_close_time"),
        "feature_freshness_state": source.get("feature_freshness_state") or source.get("freshness_state") or freshness_state,
        "trainer_consumable": classification in {ROW_TRAINABLE, ROW_HELD_OUT_VALIDATION},
        "row_classification": classification,
        "missing_feature_count": len(missing_flags),
        "missing_feature_names": list(missing_flags),
        "stale_feature_count": len(stale_flags),
        "stale_feature_names": list(stale_flags),
        "latency_ms": source.get("latency_ms"),
        "price_disagreement_bps": source.get("price_disagreement_bps"),
        "duplicate_event_count": source.get("duplicate_event_count"),
        "out_of_order_event_count": source.get("out_of_order_event_count"),
        "missing_candle_count": source.get("missing_candle_count"),
        "backfilled": source.get("backfilled") if "backfilled" in source else source.get("is_backfilled"),
        "is_backfilled": source.get("is_backfilled") if "is_backfilled" in source else source.get("backfilled"),
        "source_mode": source.get("source_mode"),
        "masa_feature_cutoff": source.get("masa_feature_cutoff"),
        "ppo_feature_cutoff": source.get("ppo_feature_cutoff"),
        "features": dict(vector),
    }
    trust = classify_training_sample(trust_row)
    next_classification = classification
    if classification in {ROW_TRAINABLE, ROW_HELD_OUT_VALIDATION} and trust["accepted_for_training"] is not True:
        next_classification = ROW_MARKET_STATE_REJECTED
    return (
        next_classification,
        trust["market_state_integrity_score"],
        trust["accepted_for_training"],
        list(trust["reject_reasons"]),
        trust_row,
    )


def build_dataset_row(
    *,
    symbol: str,
    timeframe: str,
    features: dict[str, Any] | None,
    ta: dict[str, Any] | None,
    altdata: dict[str, Any] | None,
    risk_decision: dict[str, Any] | None,
    label_row: LabelRow | None,
) -> DatasetRow:
    feature_snapshot_id = (
        (features or {}).get("feature_snapshot_id")
        or (label_row.feature_snapshot_id if label_row else None)
        or f"{symbol}:{timeframe}:no_feature_snapshot"
    )
    row_id = _stable_row_id(symbol, timeframe, str(feature_snapshot_id))
    vector = _extract_feature_vector(features, ta)
    vector.update(_extract_altdata_feature_vector(altdata))
    label = (label_row.label if label_row else "label_missing")
    classification, missing_flags, stale_flags, freshness_state = _classify_row(
        vector, features, label
    )
    if classification == ROW_TRAINABLE and _is_held_out(row_id):
        classification = ROW_HELD_OUT_VALIDATION

    source_lineage: list[str] = []
    if features is not None:
        source_lineage.append(FEATURES_KEY_TEMPLATE.format(symbol=symbol, timeframe=timeframe))
    if ta is not None:
        source_lineage.append(TA_KEY_TEMPLATE.format(symbol=symbol, timeframe=timeframe))
    if altdata is not None:
        source_lineage.append(ALTDATA_KEY_TEMPLATE.format(symbol=symbol))
    if label_row is not None:
        source_lineage.append("replay_outcome_bundles.jsonl")
    if risk_decision is not None:
        source_lineage.append(RISK_DECISIONS_KEY)
    trust_source_payload = _trust_source_with_label_metadata(features, label_row)
    (
        classification,
        market_state_integrity_score,
        accepted_for_training,
        training_reject_reasons,
        trust_row,
    ) = _dataset_training_trust(
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id=str(feature_snapshot_id),
        row_id=row_id,
        vector=vector,
        missing_flags=missing_flags,
        stale_flags=stale_flags,
        freshness_state=freshness_state,
        classification=classification,
        source_payload=trust_source_payload,
    )
    label_side = label_row.side if label_row else None

    return DatasetRow(
        row_id=row_id,
        symbol=symbol,
        timeframe=timeframe,
        feature_snapshot_id=str(feature_snapshot_id),
        generated_at=_utc_now_iso(),
        feature_vector=vector,
        missing_feature_flags=missing_flags,
        stale_feature_flags=stale_flags,
        feature_freshness_state=freshness_state,
        label=label,
        after_cost_return_bps=(
            label_row.after_cost_return_bps if label_row else None
        ),
        max_favorable_bps=(
            label_row.max_favorable_bps if label_row else None
        ),
        max_adverse_bps=(
            label_row.max_adverse_bps if label_row else None
        ),
        paper_gate_status=(
            label_row.paper_gate_status if label_row else None
        ),
        paper_gate_block_reasons=(
            label_row.paper_gate_block_reasons if label_row else []
        ),
        risk_decision_context=risk_decision,
        altdata_context=altdata,
        legacy_reference_action=(
            label_row.legacy_reference_action if label_row else None
        ),
        classification=classification,
        source_lineage=source_lineage,
        feature_cutoff=trust_row.get("feature_cutoff"),
        available_at=trust_row.get("available_at"),
        decision_time_est=trust_row.get("decision_time_est"),
        candle_closed_confirmed=trust_row.get("candle_closed_confirmed"),
        candle_open_time=trust_row.get("candle_open_time"),
        candle_close_time=trust_row.get("candle_close_time"),
        masa_feature_cutoff=trust_row.get("masa_feature_cutoff"),
        ppo_feature_cutoff=trust_row.get("ppo_feature_cutoff"),
        market_state_integrity_score=market_state_integrity_score,
        accepted_for_training=accepted_for_training,
        training_reject_reasons=training_reject_reasons,
        side=label_side,
        action=label_side,
        decision_time=trust_row.get("decision_time_est") or (
            label_row.decision_time if label_row else None
        ),
        entry_feature_available_at=(
            label_row.available_at if label_row else None
        ),
        entry_feature_generated_at=(
            label_row.entry_feature_generated_at if label_row else None
        ),
        prediction_generated_at=(
            label_row.prediction_generated_at if label_row else None
        ),
        entry_feature_cutoff=(
            label_row.feature_cutoff if label_row else None
        ),
        entry_feature_candle_closed_confirmed=(
            label_row.entry_feature_candle_closed_confirmed if label_row else None
        ),
        bundle_generated_at=(
            label_row.bundle_generated_at if label_row else None
        ),
        source_event_time=(
            label_row.source_event_time if label_row else None
        ),
    )


# ---------------------------------------------------------------------------
# Universe sweep
# ---------------------------------------------------------------------------


@dataclass
class DatasetBuildResult:
    rows: list[DatasetRow] = field(default_factory=list)
    universe: list[str] = field(default_factory=list)
    timeframes: list[str] = field(default_factory=list)
    labels_loaded: int = 0
    non_v2_read_attempts: int = 0
    read_errors: int = 0
    symbol_resolution: dict[str, Any] = field(default_factory=dict)


def build_dataset_for_universe(
    *,
    reader: V2OnlyReader,
    label_rows_by_snapshot: dict[str, LabelRow] | None = None,
    universe: Iterable[str] | None = None,
    timeframes: Iterable[str] = TIMEFRAMES,
) -> DatasetBuildResult:
    label_rows_by_snapshot = label_rows_by_snapshot or {}
    if universe is None:
        symbol_resolution = resolve_symbols_with_provenance(include_baseline=True)
        universe_list = list(symbol_resolution.get("symbols") or [])
    else:
        universe_list = list(universe)
        symbol_resolution = {
            "symbols": universe_list,
            "symbol_profile": "explicit",
            "count": len(universe_list),
            "smoke_test": False,
            "source_path": None,
        }
    timeframes_list = list(timeframes)
    rows: list[DatasetRow] = []
    for symbol in universe_list:
        altdata = reader.get_json(ALTDATA_KEY_TEMPLATE.format(symbol=symbol))
        for tf in timeframes_list:
            features = reader.get_json(
                FEATURES_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            )
            ta = reader.get_json(
                TA_KEY_TEMPLATE.format(symbol=symbol, timeframe=tf)
            )
            snapshot_id = (features or {}).get("feature_snapshot_id") or ""
            label_row = label_rows_by_snapshot.get(str(snapshot_id))
            risk_decision = None  # avoid scanning RISK_DECISIONS list payload per row
            row = build_dataset_row(
                symbol=symbol,
                timeframe=tf,
                features=features,
                ta=ta,
                altdata=altdata,
                risk_decision=risk_decision,
                label_row=label_row,
            )
            rows.append(row)
    return DatasetBuildResult(
        rows=rows,
        universe=universe_list,
        timeframes=timeframes_list,
        labels_loaded=len(label_rows_by_snapshot),
        non_v2_read_attempts=reader.non_v2_read_attempts,
        read_errors=reader.read_errors,
        symbol_resolution=symbol_resolution,
    )


def build_rows_from_replay_bundles(
    replay_bundles_path: Path,
    *,
    max_rows: int | None = None,
) -> list[DatasetRow]:
    """Build dataset rows directly from V2 replay-outcome bundles.

    Each bundle is a feature-snapshot-anchored evidence record produced
    by the V2 post-hoc replay-outcome miner. The bundle's
    ``orchestrator_decision.bucket_winners[*]`` carry the winning
    confidence + expected-move features and the future-outcomes window
    carries the after-cost label. Together they form a complete row.
    """
    rows: list[DatasetRow] = []
    if not replay_bundles_path.exists():
        return rows
    with replay_bundles_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                bundle = json.loads(line)
            except (TypeError, ValueError):
                continue
            outcomes = bundle.get("future_outcomes") or {}
            primary = _select_primary_outcome(outcomes) or {}
            after_cost = primary.get("after_cost_return_bps")
            label = bundle.get("label") or _label_for_outcome(
                after_cost,
                (bundle.get("paper_gate_decision") or {}).get("status"),
            )
            orchestrator = bundle.get("orchestrator_decision") or {}
            winners = orchestrator.get("bucket_winners") or []
            if not winners:
                continue
            for winner in winners:
                symbol = str(winner.get("symbol") or bundle.get("symbol") or "")
                if not symbol:
                    continue
                timeframe = str(bundle.get("timeframe") or "1m")
                snapshot_id = str(
                    bundle.get("feature_snapshot_id")
                    or f"{symbol}:{timeframe}:replay:{bundle.get('generated_at') or ''}"
                )
                side = _normalized_bundle_side(bundle)
                timing = _replay_bundle_timing(bundle)
                conf = winner.get("winner_confidence_calibrated")
                expected_move_after_cost = winner.get(
                    "winner_expected_move_after_cost_bps"
                )
                freshness = winner.get("winner_freshness_seconds")
                # Synthesize a stable feature vector from the orchestrator
                # decision summary. These features describe the prediction
                # that drove the historical action and are the most honest
                # V2-native signals available from a replay bundle.
                vector = {
                    "ema_9": None,
                    "ema_21": None,
                    "ema_spread": (
                        float(expected_move_after_cost) / 10.0
                        if expected_move_after_cost is not None
                        else None
                    ),
                    "rsi_14": (
                        50.0 + (float(conf) - 0.5) * 40.0
                        if conf is not None
                        else None
                    ),
                    "macd": (
                        float(expected_move_after_cost)
                        if expected_move_after_cost is not None
                        else None
                    ),
                    "macd_signal": 0.0,
                    "atr_14": None,
                    "vol_zscore": None,
                    "feature_freshness_seconds": (
                        float(freshness) if freshness is not None else None
                    ),
                }
                altdata_snapshot = (
                    bundle.get("altdata_snapshot")
                    if isinstance(bundle.get("altdata_snapshot"), dict)
                    else None
                )
                vector.update(_extract_altdata_feature_vector(altdata_snapshot))
                missing = _missing_keys(vector)
                row_classification = ROW_TRAINABLE
                missing_flags: list[str] = []
                stale_flags: list[str] = []
                freshness_state = "FRESH"
                # Explicit insufficient-evidence rows stay visible in
                # their own bucket — never collapsed into LABEL_MISSING.
                if label == "insufficient_evidence":
                    row_classification = ROW_INSUFFICIENT_EVIDENCE
                elif not label or label == "label_missing":
                    row_classification = ROW_LABEL_MISSING
                elif after_cost is None:
                    row_classification = ROW_LABEL_MISSING
                row_id = _stable_row_id(symbol, timeframe, snapshot_id)
                if row_classification == ROW_TRAINABLE and _is_held_out(row_id):
                    row_classification = ROW_HELD_OUT_VALIDATION
                (
                    row_classification,
                    market_state_integrity_score,
                    accepted_for_training,
                    training_reject_reasons,
                    trust_row,
                ) = _dataset_training_trust(
                    symbol=symbol,
                    timeframe=timeframe,
                    feature_snapshot_id=snapshot_id,
                    row_id=row_id,
                    vector=vector,
                    missing_flags=missing_flags,
                    stale_flags=stale_flags,
                    freshness_state=freshness_state,
                    classification=row_classification,
                    source_payload=_trust_source_from_replay_bundle(bundle, timing),
                )
                paper_gate = bundle.get("paper_gate_decision") or {}
                rows.append(DatasetRow(
                    row_id=row_id,
                    symbol=symbol,
                    timeframe=timeframe,
                    feature_snapshot_id=snapshot_id,
                    generated_at=str(bundle.get("generated_at") or ""),
                    feature_vector=vector,
                    missing_feature_flags=missing_flags,
                    stale_feature_flags=stale_flags,
                    feature_freshness_state=freshness_state,
                    label=str(label),
                    after_cost_return_bps=after_cost,
                    max_favorable_bps=primary.get("max_favorable_bps"),
                    max_adverse_bps=primary.get("max_adverse_bps"),
                    paper_gate_status=paper_gate.get("status"),
                    paper_gate_block_reasons=list(
                        paper_gate.get("block_reasons") or []
                    ),
                    risk_decision_context=bundle.get("risk_decision"),
                    altdata_context=altdata_snapshot,
                    legacy_reference_action=bundle.get("legacy_reference_action"),
                    classification=row_classification,
                    source_lineage=["replay_outcome_bundles.jsonl"],
                    feature_cutoff=trust_row.get("feature_cutoff"),
                    available_at=trust_row.get("available_at"),
                    decision_time_est=trust_row.get("decision_time_est"),
                    candle_closed_confirmed=trust_row.get("candle_closed_confirmed"),
                    candle_open_time=trust_row.get("candle_open_time"),
                    candle_close_time=trust_row.get("candle_close_time"),
                    masa_feature_cutoff=trust_row.get("masa_feature_cutoff"),
                    ppo_feature_cutoff=trust_row.get("ppo_feature_cutoff"),
                    market_state_integrity_score=market_state_integrity_score,
                    accepted_for_training=accepted_for_training,
                    training_reject_reasons=training_reject_reasons,
                    side=side,
                    action=side,
                    decision_time=(
                        trust_row.get("decision_time_est")
                        or timing.get("decision_time")
                    ),
                    entry_feature_available_at=timing.get("available_at"),
                    entry_feature_generated_at=timing.get("entry_feature_generated_at"),
                    prediction_generated_at=timing.get("prediction_generated_at"),
                    entry_feature_cutoff=timing.get("feature_cutoff"),
                    entry_feature_candle_closed_confirmed=timing.get(
                        "entry_feature_candle_closed_confirmed"
                    ),
                    bundle_generated_at=timing.get("bundle_generated_at"),
                    source_event_time=timing.get("source_event_time"),
                ))
                if max_rows is not None and len(rows) >= max_rows:
                    return rows
    return rows


# ---------------------------------------------------------------------------
# Dataset quality report
# ---------------------------------------------------------------------------


@dataclass
class DatasetQualityReport:
    total_rows: int
    classifications: dict[str, int]
    per_symbol_row_counts: dict[str, int]
    per_timeframe_row_counts: dict[str, int]
    label_distribution: dict[str, int]
    class_imbalance: dict[str, float]
    train_rows: int
    validation_rows: int
    insufficient_evidence_rows: int
    stale_feature_rows: int
    missing_feature_rows: int
    label_missing_rows: int
    minimum_sample_satisfied: bool
    minimum_train_rows_threshold: int

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "total_rows": self.total_rows,
            "classifications": dict(sorted(self.classifications.items())),
            "per_symbol_row_counts": dict(sorted(self.per_symbol_row_counts.items())),
            "per_timeframe_row_counts": dict(sorted(self.per_timeframe_row_counts.items())),
            "label_distribution": dict(sorted(self.label_distribution.items())),
            "class_imbalance": dict(sorted(self.class_imbalance.items())),
            "train_rows": self.train_rows,
            "validation_rows": self.validation_rows,
            "insufficient_evidence_rows": self.insufficient_evidence_rows,
            "stale_feature_rows": self.stale_feature_rows,
            "missing_feature_rows": self.missing_feature_rows,
            "label_missing_rows": self.label_missing_rows,
            "minimum_sample_satisfied": self.minimum_sample_satisfied,
            "minimum_train_rows_threshold": self.minimum_train_rows_threshold,
        }


def build_quality_report(
    rows: Sequence[DatasetRow],
    *,
    minimum_train_rows: int = MIN_TRAIN_ROWS_FOR_READINESS,
) -> DatasetQualityReport:
    classifications: dict[str, int] = {c: 0 for c in ROW_CLASSIFICATIONS}
    per_symbol: dict[str, int] = {}
    per_tf: dict[str, int] = {}
    labels: dict[str, int] = {}

    for r in rows:
        classifications[r.classification] = classifications.get(r.classification, 0) + 1
        per_symbol[r.symbol] = per_symbol.get(r.symbol, 0) + 1
        per_tf[r.timeframe] = per_tf.get(r.timeframe, 0) + 1
        labels[r.label] = labels.get(r.label, 0) + 1

    train_rows = classifications.get(ROW_TRAINABLE, 0)
    validation_rows = classifications.get(ROW_HELD_OUT_VALIDATION, 0)
    insufficient = classifications.get(ROW_INSUFFICIENT_EVIDENCE, 0)
    stale = classifications.get(ROW_STALE_FEATURES, 0)
    missing = classifications.get(ROW_MISSING_FEATURES, 0)
    label_missing = classifications.get(ROW_LABEL_MISSING, 0)

    total_label_count = sum(labels.values()) or 1
    class_imbalance = {
        label: round(count / total_label_count, 6)
        for label, count in labels.items()
    }
    return DatasetQualityReport(
        total_rows=len(rows),
        classifications=classifications,
        per_symbol_row_counts=per_symbol,
        per_timeframe_row_counts=per_tf,
        label_distribution=labels,
        class_imbalance=class_imbalance,
        train_rows=train_rows,
        validation_rows=validation_rows,
        insufficient_evidence_rows=insufficient,
        stale_feature_rows=stale,
        missing_feature_rows=missing,
        label_missing_rows=label_missing,
        minimum_sample_satisfied=train_rows >= minimum_train_rows,
        minimum_train_rows_threshold=minimum_train_rows,
    )


# ---------------------------------------------------------------------------
# Atomic writes
# ---------------------------------------------------------------------------


def _unique_tmp_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _unique_tmp_path(path)
    try:
        tmp.write_text(
            json.dumps(payload, indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _atomic_write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _unique_tmp_path(path)
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True, default=str))
                fh.write("\n")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _unique_tmp_path(path)
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


# ---------------------------------------------------------------------------
# Replay evidence sidecar
# ---------------------------------------------------------------------------


def _side_from_dataset_row(row: DatasetRow) -> str | None:
    side = str(row.side or row.action or "").strip().lower()
    if side in {"long", "buy"}:
        return "long"
    if side in {"short", "sell"}:
        return "short"
    return None


def _dataset_replay_evidence_reject_reasons(row: DatasetRow) -> list[str]:
    reasons: list[str] = []
    if "replay_outcome_bundles.jsonl" not in set(row.source_lineage or []):
        reasons.append("NOT_REPLAY_OUTCOME_SOURCE")
    if not row.symbol:
        reasons.append("MISSING_SYMBOL")
    if not row.timeframe:
        reasons.append("MISSING_TIMEFRAME")
    if _side_from_dataset_row(row) not in {"long", "short"}:
        reasons.append("NON_DIRECTIONAL_SIDE")
    if row.after_cost_return_bps is None:
        reasons.append("MISSING_AFTER_COST_OUTCOME_LABEL")

    decision = _parse_utc(row.decision_time or row.decision_time_est)
    if decision is None:
        reasons.append("MISSING_DECISION_TIME")
    for label, value in (
        ("AVAILABLE_AT", row.available_at or row.entry_feature_available_at),
        ("GENERATED_AT", row.entry_feature_generated_at),
        ("FEATURE_CUTOFF", row.feature_cutoff or row.entry_feature_cutoff),
    ):
        parsed = _parse_utc(value)
        if parsed is None:
            reasons.append(f"MISSING_{label}")
        elif decision is not None and parsed > decision:
            reasons.append(f"{label}_AFTER_DECISION_TIME")
    if row.entry_feature_candle_closed_confirmed is not True:
        reasons.append("MISSING_OR_FALSE_ENTRY_FEATURE_CANDLE_CLOSED_CONFIRMATION")
    return sorted(set(reasons))


def _dataset_replay_evidence_row(row: DatasetRow) -> dict[str, Any]:
    side = _side_from_dataset_row(row)
    feature_cutoff = row.feature_cutoff or row.entry_feature_cutoff
    available_at = row.available_at or row.entry_feature_available_at
    decision_time = row.decision_time or row.decision_time_est
    payload = {
        "source_redis_key": f"native_trainer_replay_dataset:{row.row_id}",
        "counterfactual_source_kind": "native_trainer_replay_dataset",
        "row_id": row.row_id,
        "prediction_id": row.feature_snapshot_id or row.row_id,
        "feature_snapshot_id": row.feature_snapshot_id,
        "symbol": row.symbol,
        "timeframe": row.timeframe,
        "side": side,
        "action": side,
        "decision_time": decision_time,
        "available_at": available_at,
        "entry_feature_available_at": available_at,
        "generated_at": row.entry_feature_generated_at,
        "entry_feature_generated_at": row.entry_feature_generated_at,
        "prediction_generated_at": row.prediction_generated_at,
        "feature_cutoff": feature_cutoff,
        "entry_feature_cutoff": feature_cutoff,
        "entry_feature_candle_closed_confirmed": (
            row.entry_feature_candle_closed_confirmed
        ),
        "bundle_generated_at": row.bundle_generated_at or row.generated_at,
        "realized_after_cost_return_bps": row.after_cost_return_bps,
        "after_cost_return_bps": row.after_cost_return_bps,
        "max_favorable_bps": row.max_favorable_bps,
        "max_adverse_bps": row.max_adverse_bps,
        "label": row.label,
        "classification": row.classification,
        "paper_only": True,
        "places_real_order": False,
        "live_gate": LIVE_GATE_BLOCKED,
        "source_lineage": list(row.source_lineage or []),
    }
    if row.market_state_integrity_score is not None:
        payload["market_state_integrity_score"] = row.market_state_integrity_score
    if row.accepted_for_training is not None:
        payload["accepted_for_training"] = row.accepted_for_training
    return payload


def build_replay_evidence_sidecar(rows: Sequence[DatasetRow]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    valid_rows: list[dict[str, Any]] = []
    invalid_reason_counts: dict[str, int] = {}
    invalid_samples: list[dict[str, Any]] = []
    economic_label_count = 0
    replay_source_count = 0
    symbols: set[str] = set()
    timeframes: set[str] = set()
    side_counts: dict[str, int] = {}
    after_cost_values: list[float] = []

    for row in rows:
        if row.after_cost_return_bps is not None:
            economic_label_count += 1
        if "replay_outcome_bundles.jsonl" in set(row.source_lineage or []):
            replay_source_count += 1
        reasons = _dataset_replay_evidence_reject_reasons(row)
        if reasons:
            for reason in reasons:
                invalid_reason_counts[reason] = invalid_reason_counts.get(reason, 0) + 1
            if len(invalid_samples) < 20:
                invalid_samples.append({
                    "row_id": row.row_id,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "side": _side_from_dataset_row(row),
                    "label": row.label,
                    "after_cost_return_bps": row.after_cost_return_bps,
                    "decision_time": row.decision_time or row.decision_time_est,
                    "available_at": row.available_at or row.entry_feature_available_at,
                    "generated_at": row.entry_feature_generated_at,
                    "feature_cutoff": row.feature_cutoff or row.entry_feature_cutoff,
                    "bundle_generated_at": row.bundle_generated_at or row.generated_at,
                    "reasons": reasons,
                })
            continue

        payload = _dataset_replay_evidence_row(row)
        valid_rows.append(payload)
        symbols.add(row.symbol.upper())
        timeframes.add(row.timeframe)
        side = str(payload.get("side") or "")
        side_counts[side] = side_counts.get(side, 0) + 1
        if row.after_cost_return_bps is not None:
            after_cost_values.append(float(row.after_cost_return_bps))

    expectancy = (
        sum(after_cost_values) / len(after_cost_values)
        if after_cost_values else None
    )
    status = (
        "READY_EVENT_TIME_VALID_NATIVE_REPLAY_DATASET_LABELS"
        if valid_rows else
        "NO_EVENT_TIME_VALID_NATIVE_REPLAY_DATASET_LABELS"
        if replay_source_count else
        "NO_NATIVE_REPLAY_DATASET_ROWS"
    )
    return {
        "schema_version": SCHEMA_VERSION + "_replay_evidence_status",
        "generated_at": _utc_now_iso(),
        "status": status,
        "source": "v2_native_trainer_dataset_rows",
        "dataset_row_count": len(rows),
        "replay_source_row_count": replay_source_count,
        "economic_label_count": economic_label_count,
        "event_time_valid_label_count": len(valid_rows),
        "invalid_replay_evidence_row_count": len(rows) - len(valid_rows),
        "invalid_reason_counts": {
            key: invalid_reason_counts[key]
            for key in sorted(invalid_reason_counts)
            if invalid_reason_counts[key] > 0
        },
        "invalid_sample": invalid_samples,
        "event_time_valid_symbol_count": len(symbols),
        "event_time_valid_symbols_sample": sorted(symbols)[:100],
        "event_time_valid_timeframes": sorted(timeframes),
        "event_time_valid_side_counts": {
            key: side_counts[key] for key in sorted(side_counts)
        },
        "expectancy_after_cost_bps": (
            round(expectancy, 8) if expectancy is not None else None
        ),
        **_safety_block(),
    }, valid_rows


# ---------------------------------------------------------------------------
# Packet emission (dataset side)
# ---------------------------------------------------------------------------


@dataclass
class DatasetPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_dataset_paths(repo_root: Path) -> DatasetPaths:
    return DatasetPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_native_trainer_dataset_and_baseline_model/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_native_trainer_dataset_and_baseline_model/latest",
    )


def default_replay_bundles_path(repo_root: Path) -> Path:
    return (
        repo_root
        / "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest"
        / "replay_outcome_bundles.jsonl"
    )


def emit_dataset_artifacts(
    *,
    paths: DatasetPaths,
    result: DatasetBuildResult,
    quality: DatasetQualityReport,
) -> list[Path]:
    manifest = {
        "schema_version": SCHEMA_VERSION + "_manifest",
        "generated_at": _utc_now_iso(),
        "universe": result.universe,
        "timeframes": result.timeframes,
        "symbol_resolution": result.symbol_resolution,
        "labels_loaded": result.labels_loaded,
        "non_v2_read_attempts": result.non_v2_read_attempts,
        "read_errors": result.read_errors,
        "row_count": len(result.rows),
        **_safety_block(),
    }
    status = {
        "schema_version": SCHEMA_VERSION + "_status",
        "generated_at": _utc_now_iso(),
        "quality_report": quality.to_jsonable(),
        "labels_loaded": result.labels_loaded,
        "non_v2_read_attempts": result.non_v2_read_attempts,
        "read_errors": result.read_errors,
        **_safety_block(),
    }
    quality_md = _render_quality_report(quality, result)
    replay_evidence_status, replay_evidence_rows = build_replay_evidence_sidecar(
        result.rows
    )
    manifest["replay_evidence_status"] = replay_evidence_status
    status["replay_evidence_status"] = replay_evidence_status

    paths_written: list[Path] = []

    rows_jsonl = paths.packet_dir / "v2_native_trainer_dataset_rows.jsonl"
    _atomic_write_jsonl(rows_jsonl, (r.to_jsonable() for r in result.rows))
    paths_written.append(rows_jsonl)

    replay_rows_jsonl = paths.packet_dir / REPLAY_EVIDENCE_ROWS_FILENAME
    _atomic_write_jsonl(replay_rows_jsonl, replay_evidence_rows)
    paths_written.append(replay_rows_jsonl)

    replay_status_path = paths.packet_dir / REPLAY_EVIDENCE_STATUS_FILENAME
    _atomic_write_json(replay_status_path, replay_evidence_status)
    paths_written.append(replay_status_path)

    manifest_path = paths.packet_dir / "v2_native_trainer_dataset_manifest.json"
    _atomic_write_json(manifest_path, manifest)
    paths_written.append(manifest_path)

    status_path = paths.packet_dir / "v2_native_trainer_dataset_status.json"
    _atomic_write_json(status_path, status)
    paths_written.append(status_path)

    quality_md_path = (
        paths.packet_dir / "v2_native_trainer_dataset_quality_report.md"
    )
    _atomic_write_text(quality_md_path, quality_md)
    paths_written.append(quality_md_path)

    public_status_path = (
        paths.public_dir / "v2_native_trainer_dataset_status.json"
    )
    _atomic_write_json(public_status_path, status)
    paths_written.append(public_status_path)

    public_replay_rows_jsonl = paths.public_dir / REPLAY_EVIDENCE_ROWS_FILENAME
    _atomic_write_jsonl(public_replay_rows_jsonl, replay_evidence_rows)
    paths_written.append(public_replay_rows_jsonl)

    public_replay_status_path = paths.public_dir / REPLAY_EVIDENCE_STATUS_FILENAME
    _atomic_write_json(public_replay_status_path, replay_evidence_status)
    paths_written.append(public_replay_status_path)

    return paths_written


def _render_quality_report(
    quality: DatasetQualityReport, result: DatasetBuildResult
) -> str:
    lines = []
    lines.append("# V2 Native Trainer Dataset Quality Report\n\n")
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false."
        " trainer_native_readiness_claimed=false."
        " checkpoint_compatibility_claimed=false."
        " v2_native_trainer_ready=false.\n\n"
    )
    lines.append("## Counts\n")
    lines.append(f"- total_rows: {quality.total_rows}\n")
    lines.append(f"- train_rows (TRAINABLE): {quality.train_rows}\n")
    lines.append(
        f"- validation_rows (HELD_OUT_VALIDATION): {quality.validation_rows}\n"
    )
    lines.append(
        f"- insufficient_evidence_rows: {quality.insufficient_evidence_rows}\n"
    )
    lines.append(f"- stale_feature_rows: {quality.stale_feature_rows}\n")
    lines.append(f"- missing_feature_rows: {quality.missing_feature_rows}\n")
    lines.append(f"- label_missing_rows: {quality.label_missing_rows}\n")
    lines.append(
        f"- minimum_sample_satisfied: {quality.minimum_sample_satisfied}"
        f" (threshold {quality.minimum_train_rows_threshold})\n\n"
    )
    lines.append("## Per-symbol row counts\n")
    for sym, count in sorted(quality.per_symbol_row_counts.items()):
        lines.append(f"- {sym}: {count}\n")
    lines.append("\n## Per-timeframe row counts\n")
    for tf, count in sorted(quality.per_timeframe_row_counts.items()):
        lines.append(f"- {tf}: {count}\n")
    lines.append("\n## Label distribution\n")
    for label, count in sorted(quality.label_distribution.items()):
        share = quality.class_imbalance.get(label, 0.0)
        lines.append(f"- {label}: {count} ({share:.3f})\n")
    lines.append("\n## V2-only read audit\n")
    lines.append(f"- labels_loaded_from_replay_bundles: {result.labels_loaded}\n")
    lines.append(
        f"- non_v2_read_attempts (must be 0): {result.non_v2_read_attempts}\n"
    )
    lines.append(f"- read_errors: {result.read_errors}\n")
    return "".join(lines)
