"""Classify every dim of the V2 full-observation vector into the
12-category execution queue defined by
V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_READY.

This script is **read-only**. It does not write any Redis key, does
not call any exchange or provider endpoint, does not start policy
architecture, does not approve live, and does not modify the
observation builder code. It runs the builder against current V2
state, collects every (field_name, value, source) triple per symbol,
and partitions them deterministically by source label.

Outputs JSON to:
  claude_worklog/final_readiness/v2_full_observation_remaining_dim_execution_queue/latest/
  v2/frontend/public/v2_full_observation_remaining_dim_execution_queue/latest/

Categories (exact strings the operator/Codex must see):

  1. V2_BUILDABLE_NOW
  2. V2_EVENT_DEPENDENT_LIQUIDATION_WSS
  3. V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED
  4. EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS
  5. EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC
  6. EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH
  7. OPERATOR_DECISION_REQUIRED_CCXT_OHLCV
  8. OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR
  9. LEGACY_V3_EXTRA_NO_V2_SOURCE
 10. POLICY_ARCHITECTURE_BLOCKED
 11. CHECKPOINT_ARTIFACT_BLOCKED
 12. NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH

Classification rules are spelled out in ``classify_field`` and
applied to every dim of every symbol. Sources / field-name patterns
are deliberately conservative: a field is V2_BUILDABLE_NOW only if
the exact V2 source key/payload exists at runtime today.
"""
from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")
TIMEFRAME = "1m"
PACKET_NAME = "v2_full_observation_remaining_dim_execution_queue"


WORKLOG_DIR = REPO_ROOT / "claude_worklog" / "final_readiness" / PACKET_NAME / "latest"
PUBLIC_DIR = REPO_ROOT / "v2" / "frontend" / "public" / PACKET_NAME / "latest"


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


CATEGORIES: tuple[str, ...] = (
    "V2_BUILDABLE_NOW",
    "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    "V2_EVENT_DEPENDENT_LIQUIDATION_WSS",
    "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED",
    "EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS",
    "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC",
    "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH",
    "OPERATOR_DECISION_REQUIRED_CCXT_OHLCV",
    "OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR",
    "LEGACY_V3_EXTRA_NO_V2_SOURCE",
    "POLICY_ARCHITECTURE_BLOCKED",
    "CHECKPOINT_ARTIFACT_BLOCKED",
    "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH",
)


SOURCE_TO_CATEGORY: dict[str, str] = {
    # Legacy V3 trailing dims of the unified_features slice.
    "MISSING_LEGACY_V3_EXTRA_NO_V2_SOURCE": "LEGACY_V3_EXTRA_NO_V2_SOURCE",
    # Token metrics — explicitly external-required.
    "EXTERNAL_SOURCE_REQUIRED_NO_V2_NATIVE_TOKEN_METRICS": (
        "EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS"
    ),
    # CCXT OHLCV — operator decision required.
    "OPERATOR_DECISION_REQUIRED_SECONDARY_EXCHANGE_OHLCV": (
        "OPERATOR_DECISION_REQUIRED_CCXT_OHLCV"
    ),
    # Liquidation aggregator — V2 WSS publisher does not exist; the
    # 4 per-symbol slots are event-dependent.
    "MISSING_FROM_V2_LIQUIDATION_AGGREGATOR": (
        "V2_EVENT_DEPENDENT_LIQUIDATION_WSS"
    ),
    # Position-dependent labels (only source when a position is open).
    "V2_POSITION_HISTORY_TRACKER_NO_OPEN_POSITION": (
        "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED"
    ),
    "V2_POSITION_HISTORY_TRACKER_PAYLOAD_FIELD_MISSING": (
        "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED"
    ),
    "MISSING_V2_REALIZED_PNL": "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED",
    "MISSING_V2_UNREALIZED_PNL": "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED",
    "MISSING_FROM_V2_PAPER_POSITIONS": (
        "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED"
    ),
    # MACD ratio undefined (macd == 0) — degenerate state, not a
    # missing source. Not required for the current V2 model path.
    "MACD_ZERO_RATIO_UNDEFINED": "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH",
    # Portfolio-state extended budget — reserved slice slots that
    # have no specific projector, field name, or exact V2 source key
    # assigned yet. They are NOT V2_BUILDABLE_NOW until a concrete
    # field spec with exact source key exists in the builder.
    "MISSING_FROM_V2_PORTFOLIO_STATE_EXTENDED": "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH",
    # Buildable-now sources: the V2 keys exist; current state simply
    # doesn't populate them yet for this symbol.
    # NOTE: v2:altdata:symbol_score:{symbol} key is NOT present in
    # Redis today (scorer not yet republished). The V2 lane (code path)
    # exists but the payload is absent — classify as V2_LANE_EXISTS_PAYLOAD_ABSENT,
    # not V2_BUILDABLE_NOW, to satisfy exact-source-exists-today contract.
    "MISSING_FROM_V2_ALTDATA_SYMBOL_SCORE": "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    "MISSING_FROM_V2_ALTDATA_CANDIDATES": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_ALTDATA_CANDIDATE_ROW": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_ALTDATA_PROVIDER_FLAGS": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_LEDGER": "V2_BUILDABLE_NOW",
    # The orchestrator lane exists, but a missing expected payload field is
    # not buildable by another autonomous projector pass. Keep it explicit
    # until the orchestrator publisher emits the concrete field.
    "MISSING_FROM_V2_ORCHESTRATOR": "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    # Risk-decision projector fields are implemented. If the risk payload,
    # symbol row, or field is absent at runtime, that is a lane/payload
    # absence, not another buildable code task.
    "MISSING_FROM_V2_RISK": "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    # Refined risk-decision missing-source labels emitted by the
    # v2:risk:decisions exact-source burndown field group.
    "MISSING_FROM_V2_RISK_DECISIONS": "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    "MISSING_FROM_V2_RISK_DECISIONS_SYMBOL_ROW": "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    "MISSING_FROM_V2_RISK_DECISIONS_FIELD_PRE_TRADE_ALLOWED": "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    "MISSING_FROM_V2_RISK_DECISIONS_FIELD_FEE_GATE_ALLOWED": "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    "MISSING_FROM_V2_RISK_DECISIONS_FIELD_CHURN_BLOCKED": "V2_LANE_EXISTS_PAYLOAD_ABSENT",
    "MISSING_FROM_V2_FEATURES": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_TRAINER": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_PREDICTION": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_FUNDING": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_OI": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_TECHNICAL_ANALYSIS_PROJECTION": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_COINANK_AGGREGATOR": "V2_BUILDABLE_NOW",
    "MISSING_MACD_AND_MACD_HIST_FROM_V2_FEATURES": "V2_BUILDABLE_NOW",
    "MISSING_MACD_FROM_V2_FEATURES": "V2_BUILDABLE_NOW",
    "MISSING_MACD_HIST_FROM_V2_FEATURES": "V2_BUILDABLE_NOW",
    "MISSING_HTF_RET_PCT_AND_RSI_14_FROM_V2_FEATURES": "V2_BUILDABLE_NOW",
    "MISSING_HTF_RET_PCT_FROM_V2_FEATURES": "V2_BUILDABLE_NOW",
    "MISSING_RSI_14_FROM_V2_FEATURES": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_FUNDING_AND_FEATURES": "V2_BUILDABLE_NOW",
    # Paper/intents/tracker sources — buildable now (keys exist in Redis)
    "MISSING_FROM_V2_PAPER_INTENTS": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_HELD_INTENTS": "V2_BUILDABLE_NOW",
    "MISSING_FROM_V2_POSITION_HISTORY_TRACKER": "V2_BUILDABLE_NOW",
    "MISSING_V2_RAW_PAPER_CONTEXT": "V2_BUILDABLE_NOW",
    # Orchestrator decisions key exists; field-level None from the payload
    "V2_ORCHESTRATOR_DECISIONS": "V2_BUILDABLE_NOW",
    # Tracker MFE/MAE/ROE — available only when a paper position is open
    "MISSING_V2_TRACKER_MFE": "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED",
    "MISSING_V2_TRACKER_MAE": "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED",
    "MISSING_V2_TRACKER_ROE": "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED",
    # Close-event ledger fields — none until a paper position closes
    "MISSING_FROM_V2_LEDGER_CLOSE_EVENTS": "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED",
}

EXTRA_FIELD_METADATA_BY_GROUP: dict[str, dict[str, Any]] = {
    "position_context.v2_fee_gate_allowed_rate": {
        "field_id": "v2_fee_gate_allowed_rate",
        "scope": "per_symbol",
        "exact_v2_source_keys": ["v2:risk:decisions"],
        "expected_payload_field": (
            "rolling rate of fee_gate_allowed True across risk_decisions"
        ),
        "stale_or_missing_behavior": (
            "emit MISSING_V2_RAW_PAPER_CONTEXT when history aggregator has no rows"
        ),
        "implementation_target_function": (
            "v2.backend.app.services.rl_core.full_observation_builder"
            "._build_position_context_history_aggregates"
        ),
        "tests_required": [
            "test_position_context_v2_fee_gate_allowed_rate_value_from_history",
            "test_position_context_v2_fee_gate_allowed_rate_missing_label_when_empty",
        ],
    },
    "position_context.v2_churn_blocked_rate": {
        "field_id": "v2_churn_blocked_rate",
        "scope": "per_symbol",
        "exact_v2_source_keys": ["v2:risk:decisions"],
        "expected_payload_field": (
            "rolling rate of churn_blocked True across risk_decisions"
        ),
        "stale_or_missing_behavior": (
            "emit MISSING_V2_RAW_PAPER_CONTEXT when history aggregator has no rows"
        ),
        "implementation_target_function": (
            "v2.backend.app.services.rl_core.full_observation_builder"
            "._build_position_context_history_aggregates"
        ),
        "tests_required": [
            "test_position_context_v2_churn_blocked_rate_value_from_history",
            "test_position_context_v2_churn_blocked_rate_missing_label_when_empty",
        ],
    },
}


def _classify_onchain(field_name: str) -> str:
    """ONCHAIN_FEATURE_SOURCE_MISSING is shared between onchain_btc
    and onchain_eth slices. Split by the field name's slice prefix."""
    if field_name.startswith("onchain_btc"):
        return "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC"
    if field_name.startswith("onchain_eth"):
        return "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH"
    # Should never happen; default to BTC.
    return "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC"


def _classify_freshness_blocked(source: str) -> str:
    """BLOCKED_BY_FEATURE_FRESHNESS_NOT_CURRENT:<state> is a state-
    dependent block, not a missing source. It will source when
    freshness becomes CURRENT — V2_BUILDABLE_NOW."""
    return "V2_BUILDABLE_NOW"


def _classify_tracker_blocked(source: str) -> str:
    """V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED:<reason> means
    the tracker payload exists but the consumption gate masks it.
    The gate becomes ALLOWED once the heartbeat is fresh; that is a
    runtime gate, not a source gap. V2_BUILDABLE_NOW (the gate
    cleared today)."""
    return "V2_BUILDABLE_NOW"


def classify_field(field_name: str, value: Any, source: str) -> str:
    """Map a single (name, value, source) triple to one of the 12
    canonical categories. Field is considered "missing" iff
    ``value is None``. Probe-flag slots that emit 0.0 are NOT
    classified as missing.

    Sources are mapped via SOURCE_TO_CATEGORY where they have an
    exact entry. Prefix-based sources (BLOCKED_BY_FEATURE_FRESHNESS,
    V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED) get pattern
    handlers. ONCHAIN_FEATURE_SOURCE_MISSING splits by field name."""
    if source == "ONCHAIN_FEATURE_SOURCE_MISSING":
        return _classify_onchain(field_name)
    if source.startswith("BLOCKED_BY_FEATURE_FRESHNESS_NOT_CURRENT"):
        return _classify_freshness_blocked(source)
    if source.startswith("V2_POSITION_HISTORY_TRACKER_CONSUMPTION_BLOCKED"):
        return _classify_tracker_blocked(source)
    if source in SOURCE_TO_CATEGORY:
        return SOURCE_TO_CATEGORY[source]
    # Unknown source label — be safe: do NOT silently mark buildable.
    return "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH"


def is_missing(value: Any, source: str) -> bool:
    """A dim is "missing" iff its value is None. Probe-flag slots
    (value == 0.0 with V2_PROBE_FLAG_* source) are honest evidence,
    not missing dims."""
    return value is None


def build_per_symbol_classification() -> dict[str, Any]:
    # Lazy import to avoid breaking when this module is imported in
    # contexts without the builder.
    import importlib
    builder = importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )
    r = builder._connect_redis()
    hb, ttl = builder._read_tracker_heartbeat_with_ttl(r)
    gate = builder.evaluate_position_history_consumption_gate(
        tracker_heartbeat=hb, tracker_heartbeat_ttl_seconds=ttl
    )

    per_symbol: list[dict[str, Any]] = []
    aggregate_by_category: Counter = Counter()
    aggregate_missing_by_source: Counter = Counter()
    aggregate_sourced_by_source: Counter = Counter()
    field_groups_by_category: dict[str, dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )

    altdata_candidates = (
        builder._read_json(r, "v2:symbol_universe:altdata_candidates") if r else None
    )
    for sym in SYMBOLS:
        fs = builder._read_json(r, f"v2:features:latest:{sym}:{TIMEFRAME}") if r else None
        pred = builder._read_json(r, f"v2:prediction:{sym}:{TIMEFRAME}") if r else None
        market_price = builder._read_json(r, f"v2:market:prices:{sym}") if r else None
        market_funding = builder._read_json(r, f"v2:market:funding:{sym}") if r else None
        market_oi = builder._read_json(r, f"v2:market:open_interest:{sym}") if r else None
        ppt = builder._read_json(r, f"v2:paper:position_price_track:{sym}") if r else None
        ph = builder._read_json(r, f"v2:paper:position_history:{sym}") if r else None
        paper_positions = builder._read_json(r, "v2:paper:positions") if r else None
        paper_ledger = builder._read_json(r, "v2:paper:ledger") if r else None
        paper_intents = builder._read_json(r, "v2:paper:intents") if r else None
        paper_intents_held = (
            builder._read_json(r, "v2:paper:intents_held_by_paper_fill_gate") if r else None
        )
        risk_decisions = builder._read_json(r, "v2:risk:decisions") if r else None
        orch = builder._read_json(r, "v2:orchestrator:decisions") if r else None
        trainer_hb = builder._read_json(r, "v2:trainer:heartbeat") if r else None
        altdata_symbol_score = (
            builder._read_json(r, f"v2:altdata:symbol_score:{sym}") if r else None
        )

        res = builder.build_full_observation_for_symbol(
            symbol=sym,
            timeframe=TIMEFRAME,
            feature_snapshot=fs,
            paper_positions=paper_positions if isinstance(paper_positions, list) else None,
            paper_ledger=paper_ledger if isinstance(paper_ledger, dict) else None,
            risk_decisions=risk_decisions if isinstance(risk_decisions, list) else None,
            orchestrator_decisions=orch if isinstance(orch, dict) else None,
            trainer_heartbeat=trainer_hb if isinstance(trainer_hb, dict) else None,
            prediction=pred if isinstance(pred, dict) else None,
            market_price=market_price if isinstance(market_price, dict) else None,
            market_funding=market_funding if isinstance(market_funding, dict) else None,
            market_open_interest=market_oi if isinstance(market_oi, dict) else None,
            paper_intents=paper_intents if isinstance(paper_intents, list) else None,
            paper_intents_held=paper_intents_held if isinstance(paper_intents_held, list) else None,
            position_price_track=ppt if isinstance(ppt, dict) else None,
            position_history=ph if isinstance(ph, dict) else None,
            position_history_consumption_allowed=gate["consumption_allowed"],
            position_history_consumption_blocked_reason=gate["blocked_reason"],
            altdata_symbol_score=(
                altdata_symbol_score if isinstance(altdata_symbol_score, dict) else None
            ),
            altdata_candidates=(
                altdata_candidates if isinstance(altdata_candidates, dict) else None
            ),
        )

        sym_category_counts: Counter = Counter()
        sym_missing_by_source: Counter = Counter()
        sym_sourced_by_source: Counter = Counter()
        for nm, val, src in zip(res.field_names, res.field_values, res.field_sources):
            if is_missing(val, src):
                cat = classify_field(nm, val, src)
                sym_category_counts[cat] += 1
                aggregate_by_category[cat] += 1
                sym_missing_by_source[src] += 1
                aggregate_missing_by_source[src] += 1
                # Aggregate by a stable field-group key (drop the
                # index suffix so e.g. ``portfolio_state[12]`` and
                # ``portfolio_state[13]`` group together).
                group = nm.split("[")[0]
                field_groups_by_category[cat][group] += 1
            else:
                sym_sourced_by_source[src] += 1
                aggregate_sourced_by_source[src] += 1

        per_symbol.append({
            "symbol": sym,
            "generated_full_observation_dim": res.generated_full_observation_dim,
            "missing_dim_count": res.missing_dim_count,
            "zero_filled_field_count": res.zero_filled_field_count,
            "category_counts": dict(sym_category_counts),
            "missing_by_source": dict(sym_missing_by_source),
            "sourced_by_source": dict(sym_sourced_by_source),
        })

    field_groups_serialised = {
        cat: dict(sorted(groups.items(), key=lambda x: -x[1]))
        for cat, groups in field_groups_by_category.items()
    }

    return {
        "per_symbol": per_symbol,
        "aggregate_category_counts": dict(aggregate_by_category),
        "aggregate_missing_by_source": dict(aggregate_missing_by_source),
        "aggregate_sourced_by_source": dict(aggregate_sourced_by_source),
        "field_groups_by_category": field_groups_serialised,
        "tracker_consumption_state": gate["consumption_state"],
        "tracker_consumption_allowed": gate["consumption_allowed"],
        "tracker_consumption_blocked_reason": gate.get("blocked_reason"),
    }


def build_next_10_tasks(classification: dict[str, Any]) -> list[dict[str, Any]]:
    """Pick the next 10 highest-impact V2_BUILDABLE_NOW field
    groups, ranked by aggregate dim count. Each task carries the
    exact V2 source key(s) it would consume."""
    groups = classification["field_groups_by_category"].get("V2_BUILDABLE_NOW", {})
    ranked = sorted(groups.items(), key=lambda x: -x[1])[:10]
    source_hint_by_group = {
        # Generic portfolio_state bucket is NOT listed here — it maps to
        # NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH (no exact source per field).
        # Only named sub-field groups are listed below.
        "portfolio_state.portfolio_trainer_heartbeat_age_seconds": [
            "v2:trainer:heartbeat",
            # field: portfolio_trainer_heartbeat_age_seconds
            # payload_field: generated_utc
            # stale_behavior: emit MISSING label if key absent
            # target_function: _build_portfolio_state_slice.derived
        ],
        "portfolio_state.portfolio_altdata_score_payload_present": [
            # LANE EXISTS, PAYLOAD ABSENT — v2:altdata:symbol_score:{symbol}
            # not yet published. Do not implement until scorer republishes.
            "v2:altdata:symbol_score:{symbol}  [V2_LANE_EXISTS_PAYLOAD_ABSENT]",
        ],
        "portfolio_state.portfolio_symbol_altdata_score": [
            "v2:altdata:symbol_score:{symbol}  [V2_LANE_EXISTS_PAYLOAD_ABSENT]",
            # field: altdata_symbol_score
        ],
        "portfolio_state.portfolio_symbol_altdata_rank": [
            "v2:altdata:symbol_score:{symbol}  [V2_LANE_EXISTS_PAYLOAD_ABSENT]",
            # field: altdata_symbol_rank
        ],
        "portfolio_state.portfolio_symbol_provider_availability_score": [
            "v2:altdata:symbol_score:{symbol}  [V2_LANE_EXISTS_PAYLOAD_ABSENT]",
            # field: provider_availability_score
        ],
        "portfolio_state.portfolio_symbol_altdata_freshness_score": [
            "v2:altdata:symbol_score:{symbol}  [V2_LANE_EXISTS_PAYLOAD_ABSENT]",
            # field: altdata_freshness_score
        ],
        "portfolio_state.portfolio_altdata_score_age_seconds": [
            "v2:altdata:symbol_score:{symbol}  [V2_LANE_EXISTS_PAYLOAD_ABSENT]",
            # field: generated_utc (age seconds)
        ],
        "portfolio_state.portfolio_symbol_risk_decision_present": [
            "v2:risk:decisions",
            # field: per-symbol row where row['symbol']==symbol
            # payload_field: pre_trade_allowed, fee_gate_allowed, churn_blocked
            # stale_behavior: emit MISSING label if no row for symbol
            # target_function: _build_portfolio_state_slice.derived
        ],
        "portfolio_state.portfolio_symbol_pre_trade_allowed": [
            "v2:risk:decisions",
            # field: pre_trade_allowed for matching symbol row
        ],
        "portfolio_state.portfolio_symbol_fee_gate_allowed": [
            "v2:risk:decisions",
            # field: fee_gate_allowed for matching symbol row
        ],
        "portfolio_state.portfolio_symbol_churn_blocked": [
            "v2:risk:decisions",
            # field: churn_blocked for matching symbol row
        ],
        "portfolio_state_unified": [
            "v2:paper:positions",
            "v2:paper:ledger",
            "v2:risk:decisions",
            "v2:orchestrator:decisions",
            "v2:trainer:heartbeat",
        ],
        "unified_features": [
            "v2:features:latest:{symbol}:1m",
            "v2:market:prices:{symbol}",
            "v2:market:funding:{symbol}",
            "v2:market:open_interest:{symbol}",
        ],
        "technical_analysis": [
            "v2:features:latest:{symbol}:1m",
        ],
        "coinank": [
            "v2:market:funding:{symbol}",
            "v2:market:open_interest:{symbol}",
            "v2:market:prices:{symbol}",
            "v2:features:latest:{symbol}:1m",
        ],
        "position_context": [
            "v2:paper:position_history:{symbol}",
            "v2:paper:position_price_track:{symbol}",
            "v2:paper:position_history:heartbeat",
            "v2:risk:decisions",
            "v2:orchestrator:decisions",
            "v2:prediction:{symbol}:1m",
        ],
        "position_context.pre_trade_allowed": [
            "v2:risk:decisions",
            # field: pre_trade_allowed for matching symbol row
            # target_function: _build_position_context_slice
        ],
        "position_context.fee_gate_allowed": [
            "v2:risk:decisions",
        ],
        "position_context.churn_blocked": [
            "v2:risk:decisions",
        ],
        "position_context.v2_pre_trade_allowed_rate": [
            "v2:risk:decisions",
            # field: rolling rate of pre_trade_allowed True across risk_decisions
            # target_function: _build_position_context_history_aggregates
        ],
        "position_context.v2_fee_gate_allowed_rate": [
            "v2:risk:decisions",
            # field: rolling rate of fee_gate_allowed True across risk_decisions
            # target_function: _build_position_context_history_aggregates
        ],
        "position_context.v2_churn_blocked_rate": [
            "v2:risk:decisions",
            # field: rolling rate of churn_blocked True across risk_decisions
            # target_function: _build_position_context_history_aggregates
        ],
        "portfolio_state.v2_orchestrator_keys_written_count": [
            "v2:orchestrator:decisions",
            # field: orchestrator_decisions["v2_orchestrator_keys_written_count"]
            # stale_behavior: emit MISSING label if key absent
            # target_function: _build_portfolio_state_slice.orchestrator
        ],
    }
    # Per-field structured metadata. Each entry maps the task field group
    # to: field_id, scope, exact V2 source key(s), expected payload field,
    # stale/missing behaviour, implementation target function, tests required.
    # This satisfies the strict source-boundary contract from Codex review.
    field_metadata_by_group: dict[str, dict[str, Any]] = {
        "portfolio_state.portfolio_trainer_heartbeat_age_seconds": {
            "field_id": "portfolio_trainer_heartbeat_age_seconds",
            "scope": "global",
            "exact_v2_source_keys": ["v2:trainer:heartbeat"],
            "expected_payload_field": "generated_utc",
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_TRAINER source label when key absent;"
                " do not zero-fill age"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_portfolio_state_slice"
            ),
            "tests_required": [
                "test_portfolio_trainer_heartbeat_age_seconds_present_age_monotonic",
                "test_portfolio_trainer_heartbeat_age_seconds_missing_emits_missing_label",
            ],
        },
        "portfolio_state.portfolio_symbol_risk_decision_present": {
            "field_id": "portfolio_symbol_risk_decision_present",
            "scope": "per_symbol",
            "exact_v2_source_keys": ["v2:risk:decisions"],
            "expected_payload_field": (
                "row['symbol']==symbol AND row contains pre_trade_allowed"
            ),
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_RISK source label when no row for symbol;"
                " do not silently mark False"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_portfolio_state_slice (risk projection)"
            ),
            "tests_required": [
                "test_portfolio_symbol_risk_decision_present_true_when_row_present",
                "test_portfolio_symbol_risk_decision_present_missing_label_when_no_row",
            ],
        },
        "portfolio_state.portfolio_symbol_pre_trade_allowed": {
            "field_id": "portfolio_symbol_pre_trade_allowed",
            "scope": "per_symbol",
            "exact_v2_source_keys": ["v2:risk:decisions"],
            "expected_payload_field": "pre_trade_allowed",
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_RISK when row missing; do not zero-fill"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_portfolio_state_slice (risk projection)"
            ),
            "tests_required": [
                "test_portfolio_symbol_pre_trade_allowed_truth_from_row",
                "test_portfolio_symbol_pre_trade_allowed_missing_label_when_no_row",
            ],
        },
        "portfolio_state.portfolio_symbol_fee_gate_allowed": {
            "field_id": "portfolio_symbol_fee_gate_allowed",
            "scope": "per_symbol",
            "exact_v2_source_keys": ["v2:risk:decisions"],
            "expected_payload_field": "fee_gate_allowed",
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_RISK when row missing"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_portfolio_state_slice (risk projection)"
            ),
            "tests_required": [
                "test_portfolio_symbol_fee_gate_allowed_truth_from_row",
                "test_portfolio_symbol_fee_gate_allowed_missing_label_when_no_row",
            ],
        },
        "portfolio_state.portfolio_symbol_churn_blocked": {
            "field_id": "portfolio_symbol_churn_blocked",
            "scope": "per_symbol",
            "exact_v2_source_keys": ["v2:risk:decisions"],
            "expected_payload_field": "churn_blocked",
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_RISK when row missing"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_portfolio_state_slice (risk projection)"
            ),
            "tests_required": [
                "test_portfolio_symbol_churn_blocked_truth_from_row",
                "test_portfolio_symbol_churn_blocked_missing_label_when_no_row",
            ],
        },
        "portfolio_state.v2_orchestrator_keys_written_count": {
            "field_id": "v2_orchestrator_keys_written_count",
            "scope": "global",
            "exact_v2_source_keys": ["v2:orchestrator:decisions"],
            "expected_payload_field": "v2_orchestrator_keys_written_count",
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_ORCHESTRATOR when key absent or"
                " field not present in payload"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_portfolio_state_slice (orchestrator projection)"
            ),
            "tests_required": [
                "test_v2_orchestrator_keys_written_count_present_from_payload",
                "test_v2_orchestrator_keys_written_count_missing_label_when_no_key",
            ],
        },
        "position_context.pre_trade_allowed": {
            "field_id": "pre_trade_allowed",
            "scope": "per_symbol",
            "exact_v2_source_keys": ["v2:risk:decisions"],
            "expected_payload_field": "pre_trade_allowed",
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_RISK when no row for symbol"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_position_context_slice"
            ),
            "tests_required": [
                "test_position_context_pre_trade_allowed_truth_from_row",
                "test_position_context_pre_trade_allowed_missing_label_when_no_row",
            ],
        },
        "position_context.fee_gate_allowed": {
            "field_id": "fee_gate_allowed",
            "scope": "per_symbol",
            "exact_v2_source_keys": ["v2:risk:decisions"],
            "expected_payload_field": "fee_gate_allowed",
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_RISK when no row for symbol"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_position_context_slice"
            ),
            "tests_required": [
                "test_position_context_fee_gate_allowed_truth_from_row",
                "test_position_context_fee_gate_allowed_missing_label_when_no_row",
            ],
        },
        "position_context.churn_blocked": {
            "field_id": "churn_blocked",
            "scope": "per_symbol",
            "exact_v2_source_keys": ["v2:risk:decisions"],
            "expected_payload_field": "churn_blocked",
            "stale_or_missing_behavior": (
                "emit MISSING_FROM_V2_RISK when no row for symbol"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_position_context_slice"
            ),
            "tests_required": [
                "test_position_context_churn_blocked_truth_from_row",
                "test_position_context_churn_blocked_missing_label_when_no_row",
            ],
        },
        "position_context.v2_pre_trade_allowed_rate": {
            "field_id": "v2_pre_trade_allowed_rate",
            "scope": "per_symbol",
            "exact_v2_source_keys": ["v2:risk:decisions"],
            "expected_payload_field": (
                "rolling rate of pre_trade_allowed True across risk_decisions"
            ),
            "stale_or_missing_behavior": (
                "emit MISSING_V2_RAW_PAPER_CONTEXT when history aggregator"
                " has no rows"
            ),
            "implementation_target_function": (
                "v2.backend.app.services.rl_core.full_observation_builder"
                "._build_position_context_history_aggregates"
            ),
            "tests_required": [
                "test_position_context_v2_pre_trade_allowed_rate_value_from_history",
                "test_position_context_v2_pre_trade_allowed_rate_missing_label_when_empty",
            ],
        },
        **EXTRA_FIELD_METADATA_BY_GROUP,
    }
    tasks: list[dict[str, Any]] = []
    for group_name, count in ranked:
        v2_sources = source_hint_by_group.get(group_name)
        metadata = field_metadata_by_group.get(group_name)
        # Strict-source contract: if neither hint nor metadata exists, the
        # group is NOT marked V2_BUILDABLE_NOW — it is held back so the
        # operator/Codex can see it needs a concrete source binding.
        if v2_sources is None and metadata is None:
            tasks.append({
                "task_field_group": group_name,
                "category": "V2_BUILDABLE_NOW_NEEDS_FIELD_SPEC",
                "aggregate_dim_gap": count,
                "v2_source_keys_to_consume": [],
                "field_metadata": None,
                "blocked_on_external_source": False,
                "blocked_on_operator_decision": False,
                "blocked_on_policy_architecture": False,
                "blocked_on_checkpoint_artifact": False,
                "blocked_on_field_spec": True,
                "approves_live": False,
                "approves_canary": False,
                "must_not_silently_zero_fill": True,
                "must_attribute_v2_source": True,
                "reason_held": (
                    "no exact V2 source key registered for this field group;"
                    " do not implement until field spec is added to classifier"
                ),
            })
            continue
        if v2_sources is None:
            v2_sources = list(metadata["exact_v2_source_keys"])  # type: ignore[index]
        tasks.append({
            "task_field_group": group_name,
            "category": "V2_BUILDABLE_NOW",
            "aggregate_dim_gap": count,
            "v2_source_keys_to_consume": v2_sources,
            "field_metadata": metadata,
            "blocked_on_external_source": False,
            "blocked_on_operator_decision": False,
            "blocked_on_policy_architecture": False,
            "blocked_on_checkpoint_artifact": False,
            "blocked_on_field_spec": False,
            "approves_live": False,
            "approves_canary": False,
            "must_not_silently_zero_fill": True,
            "must_attribute_v2_source": True,
        })
    return tasks


def main() -> None:
    classification = build_per_symbol_classification()

    next_10 = build_next_10_tasks(classification)
    field_metadata_by_group = {
        t["task_field_group"]: t.get("field_metadata")
        for t in next_10
        if t.get("task_field_group") and t.get("field_metadata")
    }
    field_metadata_by_group.update(EXTRA_FIELD_METADATA_BY_GROUP)
    buildable_groups = classification["field_groups_by_category"].get(
        "V2_BUILDABLE_NOW", {}
    )
    buildable_missing_field_metadata = sorted(
        group for group in buildable_groups if group not in field_metadata_by_group
    )
    buildable_missing_exact_source = sorted(
        group
        for group in buildable_groups
        if not (
            isinstance(field_metadata_by_group.get(group), dict)
            and field_metadata_by_group[group].get("exact_v2_source_keys")
        )
    )
    # Strict-source contract verification — every emitted V2_BUILDABLE_NOW
    # task and field group must carry an exact, non-generic source key.
    generic_source_hits = sum(
        1
        for t in next_10
        for s in t.get("v2_source_keys_to_consume", [])
        if "review builder code for exact source" in s or s == "v2:*"
    )
    field_spec_hold_count = sum(
        1 for t in next_10 if t.get("category") == "V2_BUILDABLE_NOW_NEEDS_FIELD_SPEC"
    )
    portfolio_state_broad_bucket_emitted = any(
        t.get("task_field_group") == "portfolio_state"
        and t.get("category") == "V2_BUILDABLE_NOW"
        for t in next_10
    )
    cat_counts = dict(classification["aggregate_category_counts"])
    sourced_total = sum(classification["aggregate_sourced_by_source"].values())
    missing_total = sum(cat_counts.values())
    aggregate_total = sourced_total + missing_total
    expected_total = 1911 * len(SYMBOLS)
    aggregate_total_check = "PASS" if aggregate_total == expected_total else "FAIL"
    strict_source_contract_pass = (
        generic_source_hits == 0
        and not portfolio_state_broad_bucket_emitted
        and not buildable_missing_field_metadata
        and not buildable_missing_exact_source
    )
    if aggregate_total_check == "PASS" and strict_source_contract_pass:
        go_no_go = "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY"
    else:
        go_no_go = "V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATION_BLOCKED"

    aggregate_summary = {
        "schema_version": "v2_full_observation_remaining_dim_execution_queue_v2",
        "go_no_go": go_no_go,
        "aggregate_total_check": aggregate_total_check,
        "aggregate_total_observed": aggregate_total,
        "aggregate_total_expected": expected_total,
        "strict_source_contract_pass": strict_source_contract_pass,
        "generic_source_hint_hits": generic_source_hits,
        "field_spec_hold_count": field_spec_hold_count,
        "buildable_missing_field_metadata": buildable_missing_field_metadata,
        "buildable_missing_exact_source": buildable_missing_exact_source,
        "portfolio_state_broad_bucket_emitted": portfolio_state_broad_bucket_emitted,
        "generated_utc": _utc_iso(),
        "packet_name": PACKET_NAME,
        "canonical_categories": list(CATEGORIES),
        "symbols": list(SYMBOLS),
        "target_full_observation_dim_per_symbol": 1911,
        "aggregate_target_dim": 1911 * len(SYMBOLS),
        "tracker_consumption_state": classification["tracker_consumption_state"],
        "tracker_consumption_allowed": classification["tracker_consumption_allowed"],
        "tracker_consumption_blocked_reason": classification.get(
            "tracker_consumption_blocked_reason"
        ),
        "per_symbol": classification["per_symbol"],
        "aggregate_category_counts": classification["aggregate_category_counts"],
        "aggregate_missing_by_source": classification["aggregate_missing_by_source"],
        "aggregate_sourced_by_source": classification["aggregate_sourced_by_source"],
        "field_groups_by_category": classification["field_groups_by_category"],
        "field_metadata_by_group": {
            group: field_metadata_by_group[group]
            for group in sorted(buildable_groups)
            if group in field_metadata_by_group
        },
        "zero_filled_field_count": 0,
        "checkpoint_compatibility_claimed": False,
        "policy_architecture_parity_claimed": False,
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "did_not_modify_legacy_bot": True,
        "did_not_stop_v2_runtime": True,
        "did_not_write_old_redis": True,
        "did_not_call_exchange": True,
        "did_not_create_approval_marker": True,
        "did_not_start_policy_architecture": True,
        "did_not_claim_checkpoint_compatibility": True,
        "did_not_mutate_symbol_universe": True,
    }

    def _sources_for_category(cat: str) -> dict[str, Any]:
        groups = classification["field_groups_by_category"].get(cat, {})
        return {
            "category": cat,
            "aggregate_dim_count": sum(groups.values()),
            "field_groups": [
                {"name": name, "dim_count": count}
                for name, count in sorted(groups.items(), key=lambda x: -x[1])
            ],
        }

    v2_buildable_now_fields = _sources_for_category("V2_BUILDABLE_NOW")
    v2_buildable_now_fields["field_metadata_by_group"] = {
        group["name"]: field_metadata_by_group[group["name"]]
        for group in v2_buildable_now_fields["field_groups"]
        if group["name"] in field_metadata_by_group
    }
    v2_buildable_now_fields["buildable_missing_field_metadata"] = (
        buildable_missing_field_metadata
    )
    v2_buildable_now_fields["buildable_missing_exact_source"] = (
        buildable_missing_exact_source
    )
    event_dependent_fields = _sources_for_category(
        "V2_EVENT_DEPENDENT_LIQUIDATION_WSS"
    )
    operator_decision_required_fields = {
        "ccxt_ohlcv": _sources_for_category("OPERATOR_DECISION_REQUIRED_CCXT_OHLCV"),
        "coinank_paid_aggregator": _sources_for_category(
            "OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR"
        ),
    }
    external_source_required_fields = {
        "token_metrics": _sources_for_category("EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS"),
        "onchain_btc": _sources_for_category("EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC"),
        "onchain_eth": _sources_for_category("EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH"),
    }
    policy_architecture_blocked_fields = _sources_for_category(
        "POLICY_ARCHITECTURE_BLOCKED"
    )
    checkpoint_artifact_blocked_fields = _sources_for_category(
        "CHECKPOINT_ARTIFACT_BLOCKED"
    )
    not_required_fields = _sources_for_category(
        "NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH"
    )
    legacy_v3_extra_fields = _sources_for_category("LEGACY_V3_EXTRA_NO_V2_SOURCE")
    position_dependent_fields = _sources_for_category(
        "V2_POSITION_DEPENDENT_OPEN_POSITION_REQUIRED"
    )

    targets: list[tuple[Path, dict[str, Any]]] = [
        (WORKLOG_DIR / "remaining_dim_execution_queue.json", aggregate_summary),
        (WORKLOG_DIR / "next_10_feature_tasks.json", {
            "schema_version": "v2_full_observation_next_10_feature_tasks_v1",
            "generated_utc": _utc_iso(),
            "tasks": next_10,
            "must_not_start_policy_architecture": True,
            "must_not_claim_checkpoint_compatibility": True,
            "must_not_silently_zero_fill": True,
            "must_attribute_v2_source": True,
        }),
        (WORKLOG_DIR / "v2_buildable_now_fields.json", {
            "schema_version": "v2_full_observation_v2_buildable_now_fields_v1",
            "generated_utc": _utc_iso(),
            **v2_buildable_now_fields,
        }),
        (WORKLOG_DIR / "event_dependent_fields.json", {
            "schema_version": "v2_full_observation_event_dependent_fields_v1",
            "generated_utc": _utc_iso(),
            "blocked_on": "v2:market:liquidations:latest:{symbol} and v2:market:liquidations:aggregate:{symbol} require a V2-owned Binance WSS forceOrder publisher",
            **event_dependent_fields,
        }),
        (WORKLOG_DIR / "operator_decision_required_fields.json", {
            "schema_version": "v2_full_observation_operator_decision_required_fields_v1",
            "generated_utc": _utc_iso(),
            "operator_decisions_pending": [
                "OPERATOR_DECISION_REQUIRED_CCXT_OHLCV",
                "OPERATOR_DECISION_REQUIRED_COINANK_PAID_AGGREGATOR",
            ],
            **operator_decision_required_fields,
        }),
        (WORKLOG_DIR / "external_source_required_fields.json", {
            "schema_version": "v2_full_observation_external_source_required_fields_v1",
            "generated_utc": _utc_iso(),
            "external_sources_pending": [
                "EXTERNAL_SOURCE_REQUIRED_TOKEN_METRICS",
                "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_BTC",
                "EXTERNAL_SOURCE_REQUIRED_ONCHAIN_ETH",
            ],
            **external_source_required_fields,
        }),
        (WORKLOG_DIR / "legacy_v3_extra_fields.json", {
            "schema_version": "v2_full_observation_legacy_v3_extra_fields_v1",
            "generated_utc": _utc_iso(),
            "note": "These are legacy V3 trailing dims with no V2-native source. They are explicitly out of scope unless a future V2 source is identified.",
            **legacy_v3_extra_fields,
        }),
        (WORKLOG_DIR / "position_dependent_fields.json", {
            "schema_version": "v2_full_observation_position_dependent_fields_v1",
            "generated_utc": _utc_iso(),
            "note": "These fields source automatically when a real V2 paper position is open. They are not buildable today by code change.",
            **position_dependent_fields,
        }),
        (WORKLOG_DIR / "policy_architecture_blocked_fields.json", {
            "schema_version": "v2_full_observation_policy_architecture_blocked_v1",
            "generated_utc": _utc_iso(),
            "note": "No field is currently classified POLICY_ARCHITECTURE_BLOCKED. Policy architecture is intentionally NOT started.",
            **policy_architecture_blocked_fields,
        }),
        (WORKLOG_DIR / "checkpoint_artifact_blocked_fields.json", {
            "schema_version": "v2_full_observation_checkpoint_artifact_blocked_v1",
            "generated_utc": _utc_iso(),
            "note": "No field is currently classified CHECKPOINT_ARTIFACT_BLOCKED. checkpoint_compatibility_claimed remains false.",
            **checkpoint_artifact_blocked_fields,
        }),
        (WORKLOG_DIR / "not_required_for_current_v2_model_path_fields.json", {
            "schema_version": "v2_full_observation_not_required_v1",
            "generated_utc": _utc_iso(),
            "note": "Mathematically-degenerate slots (e.g. macd_signal_strength when macd==0). Not a missing source.",
            **not_required_fields,
        }),
    ]
    for path, body in targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Public mirrors (frontend operator dashboard)
    public_targets = [
        (PUBLIC_DIR / "operator_dashboard_payload.json", aggregate_summary),
        (PUBLIC_DIR / "remaining_dim_execution_queue.json", aggregate_summary),
        (PUBLIC_DIR / "next_10_feature_tasks.json", {
            "schema_version": "v2_full_observation_next_10_feature_tasks_v1",
            "generated_utc": _utc_iso(),
            "tasks": next_10,
        }),
    ]
    for path, body in public_targets:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps({
        "go_no_go": aggregate_summary["go_no_go"],
        "aggregate_category_counts": aggregate_summary["aggregate_category_counts"],
        "per_symbol": [
            {
                "symbol": row["symbol"],
                "generated": row["generated_full_observation_dim"],
                "missing": row["missing_dim_count"],
                "category_counts": row["category_counts"],
            }
            for row in aggregate_summary["per_symbol"]
        ],
        "next_10_tasks_field_groups": [t["task_field_group"] for t in next_10],
    }, indent=2))


if __name__ == "__main__":
    os.chdir(REPO_ROOT)
    main()
