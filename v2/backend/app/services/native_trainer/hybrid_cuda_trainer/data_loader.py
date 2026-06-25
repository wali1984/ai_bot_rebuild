"""V2-owned data loader for the hybrid trainer."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
    build_multi_timeframe_decision_snapshot,
    canonical_from_binance_rest,
    now_ms,
    parse_ms,
)
from v2.backend.app.services.market_state_integrity.scoring import OPTIONAL_OR_EVENT_FEATURE_TOKENS
from v2.backend.app.services.market_state_integrity.sample_rejection import classify_training_sample
from v2.backend.app.services.market_state_integrity.trust import (
    ENFORCEMENT_EPOCH,
    TRUST_PRODUCER_VERSION,
    TRUST_SCHEMA_VERSION,
)
from v2.backend.app.services.native_trainer.feedback_enrichment import (
    REQUIRED_FEEDBACK_FIELDS,
    REQUIRED_TRUST_ENVELOPE_FIELDS,
    audit_quality_rejection_reasons,
)
from v2.backend.app.services.native_trainer.durable_feature_snapshot_archive import (
    SnapshotArchiveError,
    default_archive_root,
    iter_snapshots,
    load_snapshot as load_durable_feature_snapshot,
)
from v2.backend.app.services.native_trainer.trusted_replay.dataset import (
    build_trusted_replay_row,
    snapshot_to_final_candle,
)

from .safety import V2OnlyJsonIO, assert_v2_key
from .tensor_builder import FeatureTensorRecord, V2UnifiedFeatureTensorBuilder


@dataclass(frozen=True)
class TrainingExample:
    symbol: str
    timeframe: str
    tensor: FeatureTensorRecord
    label_action_index: int
    label_expected_move_after_cost_bps: float
    payload_keys: tuple[str, ...]
    row_classification: str
    trust_row: dict[str, Any] | None = None


EXPLICIT_TRAINING_TRUST_FIELDS = (
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
    "decision_id",
    "mtf_snapshot_id",
    "mtf_snapshot_valid",
    "multi_timeframe_decision_snapshot",
)


def _has_explicit_training_trust_evidence(row: Mapping[str, Any]) -> bool:
    return any(row.get(field) is not None for field in EXPLICIT_TRAINING_TRUST_FIELDS)


def _parse_trust_time(value: Any) -> datetime | None:
    if value in (None, "") or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            parsed_epoch = float(value)
        except (TypeError, ValueError):
            return None
        if parsed_epoch <= 0 or parsed_epoch != parsed_epoch:
            return None
        if parsed_epoch > 10_000_000_000:
            parsed_epoch /= 1000.0
        try:
            return datetime.fromtimestamp(parsed_epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed_epoch = float(text)
        except (TypeError, ValueError):
            return None
        if parsed_epoch <= 0 or parsed_epoch != parsed_epoch:
            return None
        if parsed_epoch > 10_000_000_000:
            parsed_epoch /= 1000.0
        try:
            return datetime.fromtimestamp(parsed_epoch, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _trainer_feedback_row_usable(row: Mapping[str, Any]) -> bool:
    if row.get("trainer_consumable") is False:
        return False
    missing = row.get("missing_feedback_fields")
    if isinstance(missing, list) and missing:
        return False
    if _feedback_trust_rejection_reasons(row):
        return False
    if row.get("feedback_schema_version") and any(
        row.get(field) in (None, "") for field in REQUIRED_FEEDBACK_FIELDS
    ):
        return False
    if row.get("trainer_feedback_source") == "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE":
        if audit_quality_rejection_reasons(dict(row)):
            return False
    return True


def _paper_outcome_label_row_usable(row: Mapping[str, Any]) -> bool:
    """Return true only for closed-trade labels carrying trainer context.

    Bare realized-PnL labels are useful for reporting, but they do not tell the
    trainer which strategy, hedge state, regime, drawdown, liquidity, or
    microstructure context produced the outcome. Those rows must stay out of
    trainer labels now that strategy/hedge feedback is part of the contract.
    """
    if row.get("trainer_feedback_source") != "V2_PAPER_TRADE_MANAGEMENT_CLOSED_TRADE":
        return False
    if _feedback_trust_rejection_reasons(row):
        return False
    return all(row.get(field) not in (None, "") for field in REQUIRED_FEEDBACK_FIELDS) and not audit_quality_rejection_reasons(
        dict(row)
    )


def _feedback_trust_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    for field in REQUIRED_TRUST_ENVELOPE_FIELDS:
        value = row.get(field)
        if value in (None, "") or (field == "source_hashes" and (not isinstance(value, Mapping) or not value)):
            reasons.append(f"MISSING_TRUST_{field.upper()}")
    decision_time = _parse_trust_time(row.get("decision_time"))
    available_at = _parse_trust_time(row.get("available_at"))
    feature_cutoff = _parse_trust_time(row.get("feature_cutoff"))
    if available_at is not None and decision_time is not None and available_at > decision_time:
        reasons.append("AVAILABLE_AT_AFTER_DECISION_TIME")
    if feature_cutoff is not None and decision_time is not None and feature_cutoff > decision_time:
        reasons.append("FEATURE_CUTOFF_AFTER_DECISION_TIME")
    return reasons


def _extra_contract_rejection_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row.get("mtf_snapshot_id") is None:
        reasons.append("MTF_SNAPSHOT_ID_MISSING")
    if row.get("mtf_snapshot_valid") is not True:
        reasons.append("MTF_SNAPSHOT_INVALID")
    for reason in row.get("mtf_snapshot_reject_reasons") or []:
        reasons.append(f"MTF_SNAPSHOT:{reason}")
    masa_cutoff = _parse_trust_time(row.get("masa_feature_cutoff"))
    ppo_cutoff = _parse_trust_time(row.get("ppo_feature_cutoff"))
    decision_time = _parse_trust_time(row.get("decision_time_est"))
    if masa_cutoff is not None and ppo_cutoff is not None and masa_cutoff != ppo_cutoff:
        reasons.append("MASA_PPO_CUTOFF_MISMATCH")
    if masa_cutoff is not None and decision_time is not None and masa_cutoff > decision_time:
        reasons.append("MASA_FEATURE_CUTOFF_AFTER_DECISION_TIME")
    if row.get("backfilled") is True and str(row.get("source_mode") or "").lower() == "live":
        reasons.append("BACKFILLED_DATA_MARKED_LIVE")
    return reasons


def _missing_names_are_optional_or_event_dependent(value: Any) -> bool:
    if isinstance(value, Mapping):
        names = [str(name) for name in value.keys()]
    elif isinstance(value, (list, tuple)):
        names = [str(name) for name in value]
    else:
        return False
    names = [name for name in names if name.strip()]
    if not names:
        return False
    for name in names:
        lowered = name.lower()
        if not any(token in lowered for token in OPTIONAL_OR_EVENT_FEATURE_TOKENS):
            return False
    return True


def _example_trusted_for_training(example: TrainingExample) -> bool:
    row = example.trust_row or {}
    if row.get("accepted_for_training") is not True:
        return False
    if row.get("reject_reasons"):
        return False
    classification = str(example.row_classification).upper()
    if classification == "STALE_MASKED":
        return False
    if classification == "MISSING_MASKED":
        return True
    return classification == "TRAINABLE"


class V2HybridTrainerDataLoader:
    """Read V2 Redis/file payloads and build trainer examples."""

    def __init__(
        self,
        *,
        io: V2OnlyJsonIO | None = None,
        tensor_builder: V2UnifiedFeatureTensorBuilder | None = None,
        replay_bundle_paths: Iterable[Path] = (),
        trusted_replay_archive_root: Path | None = None,
    ) -> None:
        self.io = io or V2OnlyJsonIO(client=None)
        self.tensor_builder = tensor_builder or V2UnifiedFeatureTensorBuilder()
        self.replay_bundle_paths = tuple(Path(p) for p in replay_bundle_paths)
        self.trusted_replay_archive_root = trusted_replay_archive_root or default_archive_root()

    def _get(self, key: str) -> Any:
        assert_v2_key(key)
        return self.io.get_json(key)

    def _get_first(self, *keys: str) -> tuple[Any, str]:
        for key in keys:
            payload = self._get(key)
            if payload is not None:
                return payload, key
        return None, keys[0]

    def _get_current_coinank(self, key: str) -> Any:
        """Read the direct CoinAnk current-source key without permitting writes.

        The no-wrapper migration runs the legacy-owned CoinAnk ingestor as-is,
        and its current read contract is ``latest:coinank:*``. This method is
        deliberately read-only and only permits that narrow namespace so the
        trainer can consume current CoinAnk evidence without adding a bridge or
        writing old Redis keys.
        """
        if not key.startswith("latest:coinank:"):
            raise ValueError(f"non_current_coinank_key_rejected:{key}")
        self.io.audit.reads_attempted += 1
        client = self.io.client
        if client is None:
            self.io.audit.reads_missing += 1
            return None
        try:
            raw = client.get(key)
        except Exception as exc:  # noqa: BLE001
            self.io.audit.errors.append(f"get_failed:{key}:{type(exc).__name__}")
            self.io.audit.reads_missing += 1
            return None
        if raw is None:
            self.io.audit.reads_missing += 1
            return None
        if isinstance(raw, (bytes, bytearray)):
            raw = raw.decode("utf-8")
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except ValueError:
                self.io.audit.errors.append(f"json_decode_failed:{key}")
                return None
        return raw

    def _get_merged(self, *keys: str) -> tuple[Any, str]:
        merged: dict[str, Any] = {}
        used: list[str] = []
        for key in keys:
            payload = self._get(key)
            if not isinstance(payload, Mapping):
                continue
            merged.update(payload)
            features = payload.get("features")
            if isinstance(features, Mapping):
                merged.update(features)
            used.append(key)
        if merged:
            return merged, ",".join(used)
        return None, keys[0]

    @staticmethod
    def _closed_candle_series_from_raw(raw: Any, *, symbol: str, timeframe: str) -> list[dict[str, Any]]:
        current_ms = now_ms()
        rows = raw if isinstance(raw, list) else [raw]
        closed_rows: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, Mapping):
                close_ms = parse_ms(row.get("candle_close_time") or row.get("close_time"))
                is_closed = (
                    row.get("is_closed") is True
                    or row.get("closed_candle") is True
                    or row.get("candle_closed_confirmed") is True
                )
                if close_ms is None or close_ms > current_ms or not is_closed:
                    continue
                closed_rows.append(dict(row))
                continue
            if not isinstance(row, (list, tuple)) or len(row) < 7:
                continue
            close_ms = parse_ms(row[6])
            if close_ms is None or close_ms > current_ms:
                continue
            try:
                closed_rows.append(
                    canonical_from_binance_rest(
                        row,
                        symbol=symbol,
                        timeframe=timeframe,
                        ingested_at=close_ms,
                    ).to_dict()
                )
            except (TypeError, ValueError):
                continue
        closed_rows.sort(key=lambda item: int(parse_ms(item.get("candle_open_time") or item.get("open_time")) or 0))
        return closed_rows

    def _read_closed_candle_series(self, *, symbol: str, timeframe: str) -> tuple[Any, str]:
        closed_key = f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}"
        closed_payload = self._get(closed_key)
        raw_key = f"v2:market:ohlcv:binance:{symbol}:{timeframe}"
        raw_payload = self._get(raw_key)
        closed_from_raw = self._closed_candle_series_from_raw(raw_payload, symbol=symbol, timeframe=timeframe)
        if isinstance(closed_payload, list) and closed_payload:
            merged: dict[int, dict[str, Any]] = {}
            for row in self._closed_candle_series_from_raw(closed_payload, symbol=symbol, timeframe=timeframe):
                close_ms = parse_ms(row.get("candle_close_time") or row.get("close_time"))
                if close_ms is not None:
                    merged[int(close_ms)] = dict(row)
            for row in closed_from_raw:
                close_ms = parse_ms(row.get("candle_close_time") or row.get("close_time"))
                if close_ms is not None:
                    merged[int(close_ms)] = dict(row)
            if merged:
                return [merged[key] for key in sorted(merged)], f"{closed_key},{raw_key}"
            return closed_payload, closed_key
        if closed_from_raw:
            return closed_from_raw, raw_key
        return closed_payload, closed_key

    def load_payloads(self, *, symbol: str, timeframe: str) -> dict[str, Any]:
        keys = {
            "prices": f"v2:market:prices:{symbol}",
            "ohlcv": f"v2:market:ohlcv_closed:binance:{symbol}:{timeframe}",
            "orderbook": f"v2:market:orderbook:{symbol}",
            "funding": f"v2:market:funding:{symbol}",
            "open_interest": f"v2:market:open_interest:{symbol}",
            "open_interest_hist": f"v2:market:open_interest_hist:{symbol}:5m",
            "long_short": f"v2:market:long_short:{symbol}",
            "coinank": f"v2:market:coinank:{symbol}",
            "kucoin": f"v2:market:kucoin:{symbol}",
            "coinapi": f"v2:market:coinapi:{symbol}",
            "microstructure": f"v2:market:microstructure:{symbol}",
            "liquidations": "v2:liquidations:events",
            "liquidations_agg": f"v2:market:liquidations:aggregate:{symbol}",
            "liquidation_levels": f"v2:market:liquidation_levels:{symbol}",
            "liquidity_zones": f"v2:market:liquidity_zones:{symbol}",
            "technical_analysis": f"v2:technical_analysis:{symbol}:{timeframe}",
            "features_latest": f"v2:features:latest:{symbol}:{timeframe}",
            "features_ta": f"v2:features:ta:{symbol}:{timeframe}",
            "features_ta_full": f"v2:features:ta_full:{symbol}:{timeframe}",
            "unified_features": f"v2:unified_features:{symbol}:{timeframe}",
            "prediction": f"v2:prediction:{symbol}:{timeframe}",
            "symbol_score": f"v2:altdata:symbol_score:{symbol}",
            "risk_decisions": "v2:risk:decisions",
            "orchestrator_decisions": "v2:orchestrator:decisions",
            "paper_ledger": "v2:paper:ledger",
            "paper_positions": "v2:paper:positions",
            "paper_position_history": "v2:paper:position_history",
            "paper_outcome_labels": "v2:paper:outcome_labels",
            "trainer_feedback_outcomes": "v2:trainer:feedback:outcomes",
        }
        payloads = {name: self._get(key) for name, key in keys.items()}
        payloads["ohlcv"], keys["ohlcv"] = self._read_closed_candle_series(symbol=symbol, timeframe=timeframe)
        for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES:
            payloads[f"ohlcv_closed_{snapshot_timeframe}"], key = self._read_closed_candle_series(
                symbol=symbol,
                timeframe=snapshot_timeframe,
            )
            keys[f"ohlcv_closed_{snapshot_timeframe}"] = key
        microstructure, microstructure_key = self._get_merged(
            f"v2:market:microstructure:{symbol}",
            f"v2:market:coinapi:wsds:{symbol}",
            f"v2:features:microfeat:{symbol}:{timeframe}",
        )
        liquidation_levels, liquidation_levels_key = self._get_merged(
            f"v2:market:liquidation_levels:{symbol}",
            f"v2:liquidations:levels:{symbol}:{timeframe}",
            f"v2:unified_features:{symbol}:{timeframe}",
            f"v2:unified_features:{symbol}:{timeframe}:latest",
        )
        payloads["microstructure"] = microstructure
        payloads["liquidation_levels"] = liquidation_levels
        keys["microstructure"] = microstructure_key
        keys["liquidation_levels"] = liquidation_levels_key
        coinank_keys = {
            "coinank_open_interest": f"latest:coinank:open_interest:{symbol}:{timeframe}",
            "coinank_funding": f"latest:coinank:funding:{symbol}:{timeframe}",
            "coinank_long_short": f"latest:coinank:long_short:{symbol}:{timeframe}",
            "coinank_liquidations": f"latest:coinank:liquidations:{symbol}:{timeframe}",
            "coinank_market_order_flow": f"latest:coinank:market_order_flow:{symbol}:{timeframe}",
            "coinank_advanced": f"latest:coinank:advanced:{symbol}:{timeframe}",
        }
        for name, key in coinank_keys.items():
            payloads[name] = self._get_current_coinank(key)
            keys[name] = key
        nansen, nansen_key = self._get_first(
            f"v2:altdata:nansen:symbol:{symbol}",
            f"v2:altdata:nansen:{symbol}",
        )
        lunarcrush, lunarcrush_key = self._get_first(
            f"v2:altdata:lunarcrush:symbol:{symbol}",
            f"v2:altdata:lunarcrush:{symbol}",
        )
        public_intel, public_intel_key = self._get_first(
            f"v2:altdata:public_intel:symbol:{symbol}",
            f"v2:altdata:public_intel:{symbol}",
        )
        aicoin, aicoin_key = self._get_first(
            f"v2:altdata:aicoin:symbol:{symbol}",
            f"v2:altdata:aicoin:{symbol}",
        )
        whale_walls, whale_walls_key = self._get_first(
            f"v2:altdata:whale_walls:symbol:{symbol}",
            f"v2:altdata:whale_walls:{symbol}",
        )
        payloads.update(
            {
                "nansen": nansen,
                "lunarcrush": lunarcrush,
                "public_intel": public_intel,
                "aicoin": aicoin,
                "whale_walls": whale_walls,
            }
        )
        keys.update(
            {
                "nansen": nansen_key,
                "lunarcrush": lunarcrush_key,
                "public_intel": public_intel_key,
                "aicoin": aicoin_key,
                "whale_walls": whale_walls_key,
            }
        )
        payloads["_keys"] = keys
        return payloads

    def load_snapshot_payloads(self, *, symbol: str, timeframe: str) -> dict[str, Any] | None:
        latest_key = f"v2:features:latest:{symbol}:{timeframe}"
        latest = self._get(latest_key)
        if not isinstance(latest, Mapping):
            return None
        features = latest.get("features") if isinstance(latest.get("features"), Mapping) else None
        if not isinstance(features, Mapping) or not features:
            return None
        if str(latest.get("symbol") or "").upper() not in {"", symbol.upper()}:
            return None
        if str(latest.get("timeframe") or "") not in {"", timeframe}:
            return None
        payloads = self._payloads_from_feature_snapshot(snapshot=latest, features=features, feedback_row={})
        keys: dict[str, str] = {"features_latest": latest_key}
        supplemental_keys = {
            "funding": f"v2:market:funding:{symbol}",
            "open_interest": f"v2:market:open_interest:{symbol}",
            "open_interest_hist": f"v2:market:open_interest_hist:{symbol}:5m",
            "long_short": f"v2:market:long_short:{symbol}",
            "orderbook": f"v2:market:orderbook:{symbol}",
            "liquidations_agg": f"v2:market:liquidations:aggregate:{symbol}",
            "liquidation_levels": f"v2:market:liquidation_levels:{symbol}",
            "liquidity_zones": f"v2:market:liquidity_zones:{symbol}",
            "symbol_score": f"v2:altdata:symbol_score:{symbol}",
            "public_intel": f"v2:altdata:public_intel:symbol:{symbol}",
            "aicoin": f"v2:altdata:aicoin:symbol:{symbol}",
            "whale_walls": f"v2:altdata:whale_walls:symbol:{symbol}",
            "lunarcrush": f"v2:altdata:lunarcrush:symbol:{symbol}",
            "nansen": f"v2:altdata:nansen:symbol:{symbol}",
            "paper_positions": "v2:paper:positions",
            "risk_decisions": "v2:risk:decisions",
            "orchestrator_decisions": "v2:orchestrator:decisions",
        }
        for name, key in supplemental_keys.items():
            value = self._get(key)
            if value is not None:
                payloads[name] = value
            keys[name] = key
        microstructure, microstructure_key = self._get_merged(
            f"v2:market:microstructure:{symbol}",
            f"v2:market:coinapi:wsds:{symbol}",
            f"v2:features:microfeat:{symbol}:{timeframe}",
        )
        if microstructure is not None:
            payloads["microstructure"] = microstructure
        keys["microstructure"] = microstructure_key
        for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES:
            payloads[f"ohlcv_closed_{snapshot_timeframe}"], key = self._read_closed_candle_series(
                symbol=symbol,
                timeframe=snapshot_timeframe,
            )
            keys[f"ohlcv_closed_{snapshot_timeframe}"] = key
        payloads["_keys"] = keys
        return payloads

    def build_example(self, *, symbol: str, timeframe: str, snapshot_fast_path: bool = False) -> TrainingExample:
        payloads = self.load_snapshot_payloads(symbol=symbol, timeframe=timeframe) if snapshot_fast_path else None
        if payloads is None:
            payloads = self.load_payloads(symbol=symbol, timeframe=timeframe)
        return self._build_example_from_payloads(symbol=symbol, timeframe=timeframe, payloads=payloads)

    def _build_example_from_payloads(
        self,
        *,
        symbol: str,
        timeframe: str,
        payloads: Mapping[str, Any],
    ) -> TrainingExample:
        tensor = self.tensor_builder.build(
            symbol=symbol,
            timeframe=timeframe,
            payloads=payloads,
        )
        expected_move = self._label_expected_move_after_cost(
            payloads=payloads,
            tensor=tensor,
        )
        action = self._label_action(expected_move)
        if tensor.data_coverage_percent < 20.0:
            classification = "INSUFFICIENT_V2_DATA_COVERAGE"
        elif tensor.stale_feature_names:
            classification = "STALE_MASKED"
        elif tensor.missing_feature_names:
            classification = "MISSING_MASKED"
        else:
            classification = "TRAINABLE"
        trust_row = self._build_trust_row(
            symbol=symbol,
            timeframe=timeframe,
            payloads=payloads,
            tensor=tensor,
            classification=classification,
        )
        outcome_row = self._matched_closed_trade_outcome(payloads=payloads, tensor=tensor)
        if outcome_row is not None:
            targets = self._outcome_targets_from_row(outcome_row)
            trust_row.update(
                {
                    "learning_mode": "outcome_supervised",
                    "update_lane": "OUTCOME_SUPERVISED_CLOSED_TRADE",
                    "outcome_targets": targets,
                    "realized_after_cost_reward": targets["realized_after_cost_reward"],
                    "value_baseline": targets["value_baseline"],
                    "advantage": targets["advantage"],
                    "advantage_source": "realized_after_cost_reward_minus_value_baseline",
                    "realized_reward_source": "realized_net_pnl_bps_after_cost",
                    "uses_expected_move_as_realized_reward": False,
                    "selected_action": targets["selected_action"],
                    "directional_outcome": targets["directional_outcome"],
                    "trade_outcome": targets["trade_outcome"],
                    "action_was_profitable": targets["action_was_profitable"],
                }
            )
        if _has_explicit_training_trust_evidence(trust_row):
            trust_result = classify_training_sample(trust_row)
            trust_row["accepted_for_training"] = trust_result["accepted_for_training"]
            trust_row["valid_for_training"] = trust_result["valid_for_training"]
            trust_row["market_state_integrity_score"] = trust_result["market_state_integrity_score"]
            extra_reasons = _extra_contract_rejection_reasons(trust_row)
            trust_row["reject_reasons"] = sorted(set(list(trust_result["reject_reasons"]) + extra_reasons))
            trust_row["source_lineage"] = trust_result["source_lineage"]
            if trust_result["accepted_for_training"] is not True or extra_reasons:
                classification = "MARKET_STATE_REJECTED"
                trust_row["trainer_consumable"] = False
                trust_row["row_classification"] = classification
        else:
            trust_row["accepted_for_training"] = classification != "STALE_MASKED"
            trust_row["valid_for_training"] = trust_row["accepted_for_training"]
            trust_row["market_state_integrity_score"] = None
            trust_row["reject_reasons"] = []

        return TrainingExample(
            symbol=symbol,
            timeframe=timeframe,
            tensor=tensor,
            label_action_index=action,
            label_expected_move_after_cost_bps=expected_move,
            payload_keys=tuple((payloads.get("_keys") or {}).values()),
            row_classification=classification,
            trust_row=trust_row,
        )

    def _build_trust_row(
        self,
        *,
        symbol: str,
        timeframe: str,
        payloads: Mapping[str, Any],
        tensor: FeatureTensorRecord,
        classification: str,
    ) -> dict[str, Any]:
        latest = payloads.get("features_latest")
        latest = latest if isinstance(latest, Mapping) else {}
        prediction = payloads.get("prediction")
        prediction = prediction if isinstance(prediction, Mapping) else {}
        features = latest.get("features") if isinstance(latest.get("features"), Mapping) else {}
        features_full = dict(features)
        ohlcv = payloads.get("ohlcv")
        ohlcv = ohlcv if isinstance(ohlcv, Mapping) else {}
        tensor_values = dict(zip(tensor.feature_names, tensor.values))
        tensor_missing = dict(zip(tensor.feature_names, tensor.missing_mask))
        for key in ("open", "high", "low", "close"):
            if features_full.get(key) is None:
                features_full[key] = latest.get(key, ohlcv.get(key))
            if features_full.get(key) is None and tensor_missing.get(key) == 0:
                features_full[key] = tensor_values.get(key)
        decision_time = latest.get("decision_time") or latest.get("decision_cutoff") or latest.get("generated_at")
        mtf_snapshot = build_multi_timeframe_decision_snapshot(
            symbol=symbol,
            decision_time=decision_time,
            candles_by_timeframe={
                snapshot_timeframe: payloads.get(f"ohlcv_closed_{snapshot_timeframe}")
                for snapshot_timeframe in REQUIRED_DECISION_TIMEFRAMES
            },
        )
        snapshot_feature_cutoff = mtf_snapshot.get("feature_cutoff")
        snapshot_all_tf_candle_timestamps = mtf_snapshot.get("all_tf_candle_timestamps") or []
        snapshot_all_source_event_times = mtf_snapshot.get("all_source_event_times") or []
        return {
            "trust_schema_version": latest.get("trust_schema_version")
            or prediction.get("trust_schema_version")
            or TRUST_SCHEMA_VERSION,
            "enforcement_epoch": latest.get("enforcement_epoch")
            or prediction.get("enforcement_epoch")
            or ENFORCEMENT_EPOCH,
            "producer": latest.get("producer") or prediction.get("producer") or "v2_hybrid_cuda_trainer_data_loader",
            "producer_version": latest.get("producer_version")
            or prediction.get("producer_version")
            or TRUST_PRODUCER_VERSION,
            "created_at": latest.get("created_at") or prediction.get("created_at") or latest.get("generated_at"),
            "symbol": symbol,
            "timeframe": timeframe,
            "decision_id": mtf_snapshot.get("decision_id"),
            "prediction_id": prediction.get("prediction_id"),
            "mtf_snapshot_id": mtf_snapshot.get("mtf_snapshot_id"),
            "replay_snapshot_id": prediction.get("replay_snapshot_id") or latest.get("replay_snapshot_id"),
            "replay_snapshot_key": prediction.get("replay_snapshot_key") or latest.get("replay_snapshot_key"),
            "replay_snapshot_write_success": prediction.get("replay_snapshot_write_success"),
            "mtf_snapshot_valid": mtf_snapshot.get("valid"),
            "mtf_snapshot_reject_reasons": list(mtf_snapshot.get("reject_reasons") or []),
            "multi_timeframe_decision_snapshot": mtf_snapshot,
            "feature_snapshot_id": tensor.feature_snapshot_id,
            "feature_vector_hash": tensor.tensor_id,
            "feature_cutoff": latest.get("feature_cutoff")
            or latest.get("decision_cutoff")
            or snapshot_feature_cutoff
            or latest.get("generated_at"),
            "available_at": latest.get("available_at") or latest.get("source_available_time") or latest.get("generated_at"),
            "latency_ms": latest.get("latency_ms"),
            "generated_at": latest.get("generated_at") or latest.get("generated_utc"),
            "feature_freshness_state": latest.get("feature_freshness_state"),
            "trainer_consumable": classification == "TRAINABLE",
            "row_classification": classification,
            "missing_feature_count": len(tensor.missing_feature_names),
            "missing_feature_names": list(tensor.missing_feature_names),
            "stale_feature_count": len(tensor.stale_feature_names),
            "stale_feature_names": list(tensor.stale_feature_names),
            "candle_closed_confirmed": latest.get("candle_closed_confirmed")
            if "candle_closed_confirmed" in latest
            else latest.get("closed_candle"),
            "candle_open_time": latest.get("candle_open_time"),
            "candle_close_time": latest.get("candle_close_time"),
            "source_event_time_est": latest.get("source_event_time") or latest.get("source_event_time_est"),
            "source_received_time_est": latest.get("source_received_time_est")
            or latest.get("source_available_time")
            or latest.get("available_at"),
            "source_available_time": latest.get("source_available_time") or latest.get("available_at"),
            "decision_time_est": decision_time,
            "masa_feature_cutoff": prediction.get("masa_feature_cutoff") or latest.get("masa_feature_cutoff"),
            "ppo_feature_cutoff": prediction.get("ppo_feature_cutoff")
            or latest.get("ppo_feature_cutoff")
            or latest.get("feature_cutoff")
            or snapshot_feature_cutoff,
            "all_tf_candle_timestamps": snapshot_all_tf_candle_timestamps
            or latest.get("all_tf_candle_timestamps")
            or [],
            "all_source_event_times": snapshot_all_source_event_times
            or latest.get("all_source_event_times")
            or [],
            "source_lineage": latest.get("source_lineage") or {},
            "price_disagreement_bps": latest.get("price_disagreement_bps") or prediction.get("price_disagreement_bps"),
            "duplicate_event_count": latest.get("duplicate_event_count"),
            "out_of_order_event_count": latest.get("out_of_order_event_count"),
            "missing_candle_count": latest.get("missing_candle_count"),
            "backfilled": latest.get("backfilled") if "backfilled" in latest else latest.get("is_backfilled"),
            "is_backfilled": latest.get("is_backfilled") if "is_backfilled" in latest else latest.get("backfilled"),
            "source_mode": latest.get("source_mode") or prediction.get("source_mode"),
            "features": dict(features_full),
        }

    def load_training_examples(
        self,
        *,
        symbols: Iterable[str],
        timeframes: Iterable[str],
        limit: int | None = None,
        trusted_only: bool = False,
        closed_trade_only: bool = False,
        snapshot_fast_path: bool = False,
    ) -> list[TrainingExample]:
        examples: list[TrainingExample] = []
        if trusted_only:
            for example in self._closed_trade_snapshot_training_examples():
                examples.append(example)
                if limit is not None and len(examples) >= int(limit):
                    return examples
            if closed_trade_only:
                return examples
        for symbol in symbols:
            for timeframe in timeframes:
                example = self.build_example(
                    symbol=symbol,
                    timeframe=timeframe,
                    snapshot_fast_path=snapshot_fast_path,
                )
                if trusted_only and not _example_trusted_for_training(example):
                    continue
                examples.append(example)
                if limit is not None and len(examples) >= int(limit):
                    return examples
        return examples

    def load_trusted_replay_examples(self, *, limit: int | None = None) -> list[TrainingExample]:
        examples: list[TrainingExample] = []
        scan_limit = None if limit is None else max(int(limit) * 20, int(limit))
        scan_limit = min(scan_limit, 100_000) if scan_limit is not None else 100_000
        archive_snapshots = list(iter_snapshots(self.trusted_replay_archive_root, limit=scan_limit))
        archive_candles: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for archived_snapshot in archive_snapshots:
            candle, _reasons = snapshot_to_final_candle(archived_snapshot)
            if candle is None:
                continue
            pair = (str(candle.get("symbol") or "").upper(), str(candle.get("timeframe") or ""))
            archive_candles.setdefault(pair, []).append(candle)
        for rows in archive_candles.values():
            rows.sort(key=lambda row: str(row.get("candle_close_time") or ""))
        candle_cache: dict[tuple[str, str], tuple[Any, str]] = {}
        for snapshot in archive_snapshots:
            if limit is not None and len(examples) >= int(limit):
                break
            symbol = str(snapshot.get("symbol") or "").upper()
            timeframe = str(snapshot.get("timeframe") or "")
            if not symbol or not timeframe:
                continue
            cache_key = (symbol, timeframe)
            if cache_key not in candle_cache:
                candle_cache[cache_key] = self._read_closed_candle_series(symbol=symbol, timeframe=timeframe)
            candles, candle_key = candle_cache[cache_key]
            candle_rows = list(archive_candles.get(cache_key) or [])
            if isinstance(candles, list):
                candle_rows.extend(candles)
            replay_row, reasons = build_trusted_replay_row(snapshot, candles=candle_rows)
            if replay_row is None:
                continue
            features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
            if not features:
                continue
            payloads = self._payloads_from_feature_snapshot(
                snapshot=snapshot,
                features=features,
                feedback_row=replay_row,
            )
            payloads["_keys"] = {
                "features_latest": f"durable_feature_snapshot_archive:{snapshot.get('snapshot_id')}",
                "trainer_feedback_outcomes": replay_row["sample_id"],
                "ohlcv": candle_key,
            }
            tensor = self.tensor_builder.build(symbol=symbol, timeframe=timeframe, payloads=payloads)
            if tensor.data_coverage_percent < 20.0:
                continue
            classification = (
                "STALE_MASKED"
                if tensor.stale_feature_names
                else "MISSING_MASKED"
                if tensor.missing_feature_names
                else "TRAINABLE"
            )
            trust_row = dict(replay_row)
            trust_row.update(
                {
                    "row_classification": classification,
                    "missing_feature_names": list(tensor.missing_feature_names),
                    "missing_feature_count": len(tensor.missing_feature_names),
                    "stale_feature_names": list(tensor.stale_feature_names),
                    "stale_feature_count": len(tensor.stale_feature_names),
                    "feature_vector_hash": tensor.tensor_id,
                    "market_state_integrity_score": replay_row.get("market_state_integrity_score"),
                    "reject_reasons": list(reasons),
                    "source_lineage": {
                        "durable_feature_snapshot_archive": True,
                        "feature_snapshot_id": snapshot.get("snapshot_id"),
                        "content_sha256": snapshot.get("content_sha256"),
                        "candle_source_key": candle_key,
                    },
                }
            )
            examples.append(
                TrainingExample(
                    symbol=symbol,
                    timeframe=timeframe,
                    tensor=tensor,
                    label_action_index=self._label_action(float(replay_row["future_return_after_cost_bps"])),
                    label_expected_move_after_cost_bps=float(replay_row["future_return_after_cost_bps"]),
                    payload_keys=tuple((payloads.get("_keys") or {}).values()),
                    row_classification=classification,
                    trust_row=trust_row,
                )
            )
        return examples

    def _closed_trade_snapshot_training_examples(self) -> list[TrainingExample]:
        payload = self._get("v2:trainer:feedback:outcomes")
        if not isinstance(payload, list):
            return []
        examples: list[TrainingExample] = []
        for row in payload:
            if not isinstance(row, Mapping) or not _trainer_feedback_row_usable(row):
                continue
            example = self._closed_trade_snapshot_training_example(row)
            if example is not None:
                examples.append(example)
        return examples

    def _closed_trade_feature_snapshot(
        self,
        *,
        row: Mapping[str, Any],
        feature_snapshot_id: Any,
    ) -> tuple[Mapping[str, Any] | None, str | None]:
        snapshot_key = f"v2:features:snapshot:{feature_snapshot_id}"
        snapshot = self._get(snapshot_key)
        if isinstance(snapshot, Mapping):
            return snapshot, snapshot_key
        for field in ("entry_feature_snapshot", "feature_snapshot"):
            embedded = row.get(field)
            if not isinstance(embedded, Mapping):
                continue
            embedded_id = embedded.get("feature_snapshot_id") or embedded.get("snapshot_id")
            if embedded_id in (None, "") or str(embedded_id) != str(feature_snapshot_id):
                continue
            features = embedded.get("features") if isinstance(embedded.get("features"), Mapping) else {}
            if not features:
                continue
            return embedded, f"trainer_feedback.{field}"
        try:
            archived = load_durable_feature_snapshot(
                feature_snapshot_id,
                root=self.trusted_replay_archive_root,
            )
        except SnapshotArchiveError:
            archived = None
        if isinstance(archived, Mapping):
            features = archived.get("features") if isinstance(archived.get("features"), Mapping) else {}
            archived_id = archived.get("feature_snapshot_id") or archived.get("snapshot_id")
            if features and str(archived_id or feature_snapshot_id) == str(feature_snapshot_id):
                return archived, f"durable_feature_snapshot_archive:{feature_snapshot_id}"
        return None, None

    def _closed_trade_snapshot_training_example(self, row: Mapping[str, Any]) -> TrainingExample | None:
        feature_snapshot_id = row.get("entry_feature_snapshot_id") or row.get("feature_snapshot_id")
        if feature_snapshot_id in (None, ""):
            return None
        snapshot, snapshot_source = self._closed_trade_feature_snapshot(
            row=row,
            feature_snapshot_id=feature_snapshot_id,
        )
        if not isinstance(snapshot, Mapping):
            return None
        symbol = str(row.get("symbol") or "").upper()
        timeframe = str(row.get("timeframe") or "")
        if not symbol or not timeframe:
            return None
        snapshot_payload_id = snapshot.get("feature_snapshot_id") or snapshot.get("snapshot_id")
        if snapshot_payload_id and str(snapshot_payload_id) != str(feature_snapshot_id):
            return None
        if str(snapshot.get("symbol") or "").upper() not in {"", symbol}:
            return None
        if str(snapshot.get("timeframe") or "") not in {"", timeframe}:
            return None
        decision_time = _parse_trust_time(row.get("decision_time"))
        snapshot_available_at = _parse_trust_time(snapshot.get("available_at") or snapshot.get("generated_utc") or snapshot.get("generated_at"))
        snapshot_feature_cutoff = _parse_trust_time(snapshot.get("feature_cutoff") or snapshot.get("source_available_time"))
        if decision_time is None:
            return None
        if snapshot_available_at is not None and snapshot_available_at > decision_time:
            return None
        if snapshot_feature_cutoff is not None and snapshot_feature_cutoff > decision_time:
            return None
        features = snapshot.get("features") if isinstance(snapshot.get("features"), Mapping) else {}
        if not features:
            return None
        payloads = self._payloads_from_feature_snapshot(snapshot=snapshot, features=features, feedback_row=row)
        tensor = self.tensor_builder.build(symbol=symbol, timeframe=timeframe, payloads=payloads)
        if tensor.data_coverage_percent < 20.0:
            return None
        targets = self._outcome_targets_from_row(row)
        directional_value = self._directional_label_bps_from_outcome(row)
        action = self._label_action(directional_value)
        classification = "STALE_MASKED" if tensor.stale_feature_names else "MISSING_MASKED" if tensor.missing_feature_names else "TRAINABLE"
        trust_row = dict(row)
        trust_row.update(
            {
                "learning_mode": "outcome_supervised",
                "update_lane": "OUTCOME_SUPERVISED_CLOSED_TRADE",
                "outcome_targets": targets,
                "realized_after_cost_reward": targets["realized_after_cost_reward"],
                "value_baseline": targets["value_baseline"],
                "advantage": targets["advantage"],
                "advantage_source": "realized_after_cost_reward_minus_value_baseline",
                "realized_reward_source": "realized_net_pnl_bps_after_cost",
                "uses_expected_move_as_realized_reward": False,
                "selected_action": targets["selected_action"],
                "directional_outcome": targets["directional_outcome"],
                "trade_outcome": targets["trade_outcome"],
                "action_was_profitable": targets["action_was_profitable"],
                "accepted_for_training": True,
                "valid_for_training": True,
                "market_state_integrity_score": row.get("market_state_integrity_score"),
                "reject_reasons": [],
                "source_lineage": {
                    "trainer_feedback_id": row.get("trainer_feedback_id"),
                    "entry_prediction_id": row.get("entry_prediction_id") or row.get("prediction_id"),
                    "entry_feature_snapshot_id": feature_snapshot_id,
                    "feature_snapshot_key": snapshot_source or f"v2:features:snapshot:{feature_snapshot_id}",
                    "snapshot_backed_closed_trade_feedback": True,
                },
                "snapshot_backed_closed_trade_feedback": True,
            }
        )
        return TrainingExample(
            symbol=symbol,
            timeframe=timeframe,
            tensor=tensor,
            label_action_index=action,
            label_expected_move_after_cost_bps=directional_value,
            payload_keys=(
                f"v2:trainer:feedback:outcomes:{row.get('trainer_feedback_id')}",
                f"v2:features:snapshot:{feature_snapshot_id}",
            ),
            row_classification=classification,
            trust_row=trust_row,
        )

    @staticmethod
    def _payloads_from_feature_snapshot(
        *,
        snapshot: Mapping[str, Any],
        features: Mapping[str, Any],
        feedback_row: Mapping[str, Any],
    ) -> dict[str, Any]:
        price = next(
            (
                value
                for value in (
                    features.get("last_price"),
                    features.get("price_last"),
                    features.get("close"),
                    features.get("ohlcv_close"),
                )
                if value not in (None, "")
            ),
            None,
        )
        ohlcv_payload = {
            **dict(features),
            "closed_candle": snapshot.get("closed_candle") if "closed_candle" in snapshot else snapshot.get("candle_closed_confirmed"),
            "is_closed": snapshot.get("is_closed") if "is_closed" in snapshot else snapshot.get("candle_closed_confirmed"),
            "candle_closed_confirmed": snapshot.get("candle_closed_confirmed"),
        }
        return {
            "features_latest": snapshot,
            "ohlcv": ohlcv_payload,
            "features_ta": {"indicators": dict(features)},
            "features_ta_full": {"features": dict(features)},
            "technical_analysis": {"indicators": dict(features)},
            "prices": {
                "price": price,
                "last": price,
                "last_price": price,
                "ticker_24hr": {
                    "lastPrice": price,
                    "quoteVolume": features.get("quote_volume"),
                },
                "funding": {
                    "markPrice": features.get("mark_price"),
                    "indexPrice": features.get("index_price"),
                },
                "basis_pct": features.get("basis_pct"),
            },
            "funding": dict(features),
            "open_interest": dict(features),
            "open_interest_hist": dict(features),
            "long_short": dict(features),
            "orderbook": dict(features),
            "microstructure": dict(features),
            "liquidation_levels": dict(features),
            "liquidity_zones": dict(features),
            "liquidations": {},
            "liquidations_agg": dict(features),
            "symbol_score": dict(features),
            "public_intel": dict(features),
            "aicoin": dict(features),
            "whale_walls": dict(features),
            "paper_positions": {},
            "risk_decisions": {},
            "orchestrator_decisions": {},
            "prediction": dict(feedback_row),
            "trainer_feedback_outcomes": [dict(feedback_row)],
            "paper_outcome_labels": [],
        }

    def _label_expected_move_after_cost(
        self,
        *,
        payloads: Mapping[str, Any],
        tensor: FeatureTensorRecord,
    ) -> float:
        outcome_move = self._label_from_closed_trade_outcome(payloads=payloads, tensor=tensor)
        if outcome_move is not None:
            return outcome_move
        latest = payloads.get("features_latest")
        existing_prediction = payloads.get("prediction")
        for payload in (existing_prediction, latest, payloads.get("unified_features")):
            if isinstance(payload, Mapping):
                val = payload.get("expected_move_after_cost_bps")
                if val is not None:
                    try:
                        return float(val)
                    except (TypeError, ValueError):
                        pass
        values = dict(zip(tensor.feature_names, tensor.values))
        ema_12 = values.get("ema_12", 0.0)
        ema_26 = values.get("ema_26", 0.0)
        rsi = values.get("rsi_14", 50.0)
        macd = values.get("macd", 0.0)
        macd_signal = values.get("macd_signal", 0.0)
        spread_signal = (ema_12 - ema_26) * 0.35
        rsi_signal = (rsi - 50.0) * 0.18
        macd_signal_bps = (macd - macd_signal) * 4.0
        return float(max(-80.0, min(80.0, spread_signal + rsi_signal + macd_signal_bps)))

    def _label_from_closed_trade_outcome(
        self,
        *,
        payloads: Mapping[str, Any],
        tensor: FeatureTensorRecord,
    ) -> float | None:
        row = self._matched_closed_trade_outcome(payloads=payloads, tensor=tensor)
        if row is None:
            return None
        value = self._directional_label_bps_from_outcome(row)
        return float(max(-250.0, min(250.0, value)))

    def _matched_closed_trade_outcome(
        self,
        *,
        payloads: Mapping[str, Any],
        tensor: FeatureTensorRecord,
    ) -> Mapping[str, Any] | None:
        candidates: list[Mapping[str, Any]] = []
        for key in ("trainer_feedback_outcomes", "paper_outcome_labels"):
            payload = payloads.get(key)
            rows: list[Mapping[str, Any]] = []
            if isinstance(payload, list):
                rows.extend(row for row in payload if isinstance(row, Mapping))
            elif isinstance(payload, Mapping):
                payload_rows = payload.get("outcome_labels") or payload.get("rows")
                if isinstance(payload_rows, list):
                    rows.extend(row for row in payload_rows if isinstance(row, Mapping))
                else:
                    rows.append(payload)
            if key == "trainer_feedback_outcomes":
                rows = [row for row in rows if _trainer_feedback_row_usable(row)]
            if key == "paper_outcome_labels":
                rows = [row for row in rows if _paper_outcome_label_row_usable(row)]
            candidates.extend(rows)
        matched: list[Mapping[str, Any]] = []
        for row in candidates:
            if str(row.get("symbol") or "").upper() != tensor.symbol.upper():
                continue
            timeframe = row.get("timeframe")
            if timeframe and str(timeframe) != tensor.timeframe:
                continue
            if not row.get("entry_prediction_id") and not row.get("entry_feature_snapshot_id"):
                continue
            if not row.get("exit_time"):
                continue
            value = row.get("realized_pnl_bps")
            try:
                float(value)
            except (TypeError, ValueError):
                continue
            matched.append(row)
        if not matched:
            return None
        matched.sort(key=lambda row: str(row.get("exit_time") or ""))
        return matched[-1]

    @staticmethod
    def _directional_label_bps_from_outcome(row: Mapping[str, Any]) -> float:
        value = float(row.get("realized_net_pnl_bps") or row.get("realized_pnl_bps") or 0.0)
        directional = str(row.get("directional_outcome") or "").strip().upper()
        if directional == "UP":
            return abs(value)
        if directional == "DOWN":
            return -abs(value)
        if directional == "FLAT":
            return 0.0
        # realized_pnl_bps is position PnL, not price direction. For SHORT
        # trades, positive PnL means price moved down, so invert the sign.
        action = str(row.get("selected_action") or row.get("action") or row.get("side") or "").strip().lower()
        if action == "short":
            value = -value
        return float(value)

    @staticmethod
    def _outcome_targets_from_row(row: Mapping[str, Any]) -> dict[str, Any]:
        realized_bps = float(row.get("realized_net_pnl_bps") or row.get("realized_pnl_bps") or 0.0)
        realized_usd = float(row.get("realized_net_pnl_usd") or row.get("realized_pnl_usd") or row.get("realized_pnl") or 0.0)
        selected_action = str(row.get("selected_action") or row.get("action") or row.get("side") or "").strip().lower()
        directional = str(row.get("directional_outcome") or "").strip().upper()
        if not directional:
            directional_value = V2HybridTrainerDataLoader._directional_label_bps_from_outcome(row)
            directional = "UP" if directional_value > 0.0 else "DOWN" if directional_value < 0.0 else "FLAT"
        trade_outcome = str(row.get("trade_outcome") or "").strip().upper()
        if trade_outcome not in {"WIN", "LOSS", "BREAKEVEN"}:
            trade_outcome = "WIN" if realized_usd > 0.0 else "LOSS" if realized_usd < 0.0 else "BREAKEVEN"
        value_baseline = float(row.get("value_baseline") or row.get("policy_value") or row.get("old_value") or 0.0)
        realized_reward = realized_bps / 100.0
        return {
            "realized_net_pnl_bps": realized_bps,
            "realized_net_pnl_usd": realized_usd,
            "directional_outcome": directional,
            "trade_outcome": trade_outcome,
            "selected_action": selected_action,
            "action_was_profitable": bool(
                row.get("action_was_profitable")
                if row.get("action_was_profitable") is not None
                else realized_usd > 0.0
            ),
            "holding_period": row.get("holding_period") or row.get("hold_time_seconds"),
            "fees": row.get("fees"),
            "slippage": row.get("slippage"),
            "funding": row.get("funding"),
            "MFE": row.get("MFE") if row.get("MFE") is not None else row.get("mfe_bps"),
            "MAE": row.get("MAE") if row.get("MAE") is not None else row.get("mae_bps"),
            "exit_reason": row.get("exit_reason") or row.get("close_reason"),
            "realized_after_cost_reward": realized_reward,
            "value_baseline": value_baseline,
            "advantage": realized_reward - value_baseline,
        }

    @staticmethod
    def _label_action(expected_move_after_cost_bps: float) -> int:
        if expected_move_after_cost_bps >= 4.0:
            return 1
        if expected_move_after_cost_bps <= -4.0:
            return 2
        return 0


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows
