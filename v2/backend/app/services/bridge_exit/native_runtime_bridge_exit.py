"""V2 native-runtime bridge-exit and dynamic-symbol migration planner.

Analysis-only. Emits a nine-phase packet that drives the V2 control
plane away from legacy bridge dependencies and toward V2-native
ingestors, trainer, and dynamic symbol coverage.

Hard rules enforced by every artifact in this packet:

* live_gate = blocked_human_only
* live_symbols = []
* approves_live / approves_canary / approves_legacy_shutdown /
  approves_redis_trim = false
* No mutation of paper / training / live symbol lists. Candidate
  rosters here are documentation of what *would* be onboarded once
  governance approves; nothing in this module flips a switch.
* No legacy mutation, no exchange call, no old Redis write.
* No paper-fill-gate weakening. The gate must keep failing closed.
* No checkpoint deserialization, no policy-architecture parity claim.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "v2_native_runtime_bridge_exit_and_dynamic_symbol_migration_v1"
LIVE_GATE_BLOCKED = "blocked_human_only"

# Universe documented by the operator. Listed here only as a static
# reference set so the planner can compute missing/candidate buckets.
# The planner DOES NOT publish, adopt, or activate any of these symbols.
KNOWN_UNIVERSE: tuple[str, ...] = (
    "1000BONKUSDT",
    "1000FLOKIUSDT",
    "1000PEPEUSDT",
    "1000SHIBUSDT",
    "ALICEUSDT",
    "ASTERUSDT",
    "AUCTIONUSDT",
    "AVNTUSDT",
    "BANKUSDT",
    "BARDUSDT",
    "BTCUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "FARTCOINUSDT",
    "HIGHUSDT",
    "LINKUSDT",
    "LTCUSDT",
    "PENGUUSDT",
    "PIPPINUSDT",
    "RAVEUSDT",
    "RIVERUSDT",
    "SOLUSDT",
    "UNIUSDT",
    "WIFUSDT",
    "XRPUSDT",
)

# Symbols V2 ingestors / replay miner / paper runtime cover today, per
# the latest miner status snapshot. Treated as ground truth for the
# diff against KNOWN_UNIVERSE.
V2_NATIVE_ACTIVE_SYMBOLS: tuple[str, ...] = ("BTCUSDT", "ETHUSDT", "SOLUSDT")


# Canonical lane classifications. Treated as strings only; no flag
# anywhere maps these to live/paper authorization.
LANE_NATIVE = "V2_NATIVE"
LANE_BRIDGE = "V2_BRIDGE_FROM_LEGACY_REDIS"
LANE_LEGACY_REF = "LEGACY_REFERENCE_ONLY"
LANE_PLACEHOLDER = "PLACEHOLDER_NOT_READY"
LANE_OPERATOR = "OPERATOR_DECISION_REQUIRED"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


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


_SAFETY_PINS = {
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
    "did_not_stop_continuous_remediation": True,
    "did_not_stop_codex_governors": True,
    "did_not_write_old_redis_keys": True,
    "did_not_call_exchange_mutation": True,
    "did_not_change_leverage_or_margin_mode": True,
    "did_not_create_paper_only_shutdown_acceptance_file": True,
    "did_not_weaken_paper_fill_gate": True,
    "did_not_claim_policy_architecture_parity": True,
    "did_not_deserialize_legacy_checkpoint": True,
    "did_not_mutate_live_symbols_paper_symbols_or_training_symbols": True,
    "did_not_adopt_any_symbol_universe_candidate": True,
}


def _safety_block() -> dict[str, Any]:
    """Return the standard safety pin block.

    Always callable inside any builder so every emitted artifact carries
    the same explicit set of negative claims.
    """
    return dict(_SAFETY_PINS)


# ---------------------------------------------------------------------------
# Phase 1 - Bridge dependency inventory
# ---------------------------------------------------------------------------


_LANE_INVENTORY: list[dict[str, Any]] = [
    {
        "lane_id": "market_prices",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": ["v2:market:prices:{symbol}"],
        "v2_native_target_keys": ["v2:market:prices:{symbol}"],
        "bridge_worker": None,
        "freshness": "tick_level_when_market_ingestor_active",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "dynamic_universe_expansion_beyond_3_symbols",
        ],
        "next_migration_action": (
            "Expand v2 market ingestor symbol roster to KNOWN_UNIVERSE "
            "under existing Symbol Universe governance."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "ohlcv",
        "classification": LANE_PLACEHOLDER,
        "current_source_redis_keys": [],
        "v2_native_target_keys": [
            "v2:market:ohlcv:{exchange}:{symbol}:{timeframe}"
        ],
        "bridge_worker": None,
        "freshness": "MISSING_EVIDENCE",
        "symbol_coverage": [],
        "missing_components": [
            "binance_usdm_ohlcv_dynamic_symbol_ingestor",
            "kucoin_ohlcv_optional_ingestor",
        ],
        "next_migration_action": (
            "Implement v2_native_binance_ohlcv_dynamic_symbol_ingestor"
        ),
        "blocks_paper": True,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "orderbook",
        "classification": LANE_PLACEHOLDER,
        "current_source_redis_keys": [],
        "v2_native_target_keys": [
            "v2:market:orderbook:{exchange}:{symbol}"
        ],
        "bridge_worker": None,
        "freshness": "MISSING_EVIDENCE",
        "symbol_coverage": [],
        "missing_components": [
            "binance_usdm_orderbook_dynamic_symbol_ingestor",
            "kucoin_orderbook_optional_ingestor",
        ],
        "next_migration_action": (
            "Implement v2_native_binance_orderbook_dynamic_symbol_ingestor"
        ),
        "blocks_paper": True,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "liquidation",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": [
            "v2:market:liquidations:{symbol}",
            "v2:market:liquidations:latest:{symbol}",
            "v2:market:liquidations:aggregate:{symbol}",
            "v2:market:liquidations:heartbeat",
        ],
        "v2_native_target_keys": [
            "v2:market:liquidations:{symbol}",
            "v2:market:liquidations:latest:{symbol}",
            "v2:market:liquidations:aggregate:{symbol}",
        ],
        "bridge_worker": None,
        "freshness": "event_dependent",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "per_symbol_coverage_for_remaining_universe",
        ],
        "next_migration_action": (
            "Extend liquidation WSS daemon to KNOWN_UNIVERSE symbols once "
            "Symbol Universe governance approves."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "funding",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": ["v2:market:funding:{symbol}"],
        "v2_native_target_keys": ["v2:market:funding:{symbol}"],
        "bridge_worker": None,
        "freshness": "exchange_funding_cycle",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "dynamic_universe_expansion_beyond_3_symbols",
        ],
        "next_migration_action": (
            "Expand funding ingestor to remaining KNOWN_UNIVERSE symbols."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "open_interest",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": ["v2:market:open_interest:{symbol}"],
        "v2_native_target_keys": ["v2:market:open_interest:{symbol}"],
        "bridge_worker": None,
        "freshness": "exchange_oi_cycle",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "dynamic_universe_expansion_beyond_3_symbols",
        ],
        "next_migration_action": (
            "Expand OI ingestor to remaining KNOWN_UNIVERSE symbols."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "coinank",
        "classification": LANE_BRIDGE,
        "current_source_redis_keys": [
            "v2:altdata:coinank:funding_aggregate",
            "v2:altdata:coinank:long_short",
            "v2:altdata:coinank:liquidation_aggregate",
        ],
        "v2_native_target_keys": [
            "v2:altdata:coinank:funding_aggregate:{symbol}",
            "v2:altdata:coinank:long_short:{symbol}",
            "v2:altdata:coinank:liquidation_aggregate:{symbol}",
        ],
        "bridge_worker": "v2_coinank_bridge",
        "freshness": "bridge_dependent",
        "symbol_coverage": [],
        "missing_components": [
            "per_symbol_coinank_payload",
            "paid_aggregator_decision",
        ],
        "next_migration_action": (
            "Promote bridge to V2_NATIVE per-symbol payload; gated on "
            "operator decision for paid aggregator."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": True,
    },
    {
        "lane_id": "coinapi",
        "classification": LANE_OPERATOR,
        "current_source_redis_keys": [],
        "v2_native_target_keys": [
            "v2:market:coinapi:top_of_book:{symbol}"
        ],
        "bridge_worker": None,
        "freshness": "MISSING_EVIDENCE",
        "symbol_coverage": [],
        "missing_components": [
            "operator_decision_to_use_coinapi_secondary_top_of_book",
        ],
        "next_migration_action": (
            "Operator decides whether to enable a CoinAPI top-of-book "
            "secondary feed; planner takes no action until then."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": False,
    },
    {
        "lane_id": "kucoin",
        "classification": LANE_OPERATOR,
        "current_source_redis_keys": [],
        "v2_native_target_keys": [
            "v2:market:orderbook:kucoin:{symbol}",
            "v2:market:prices:kucoin:{symbol}",
        ],
        "bridge_worker": None,
        "freshness": "MISSING_EVIDENCE",
        "symbol_coverage": [],
        "missing_components": [
            "operator_decision_to_enable_kucoin_secondary_feed",
        ],
        "next_migration_action": (
            "Operator decides whether to enable KuCoin secondary "
            "orderbook/price feed."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": False,
    },
    {
        "lane_id": "ta_indicators",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": [
            "v2:features:ta:{symbol}:{timeframe}",
        ],
        "v2_native_target_keys": [
            "v2:features:ta:{symbol}:{timeframe}",
        ],
        "bridge_worker": None,
        "freshness": "per_market_cycle",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "dynamic_universe_expansion_beyond_3_symbols",
        ],
        "next_migration_action": (
            "Run TA pipeline against expanded symbol roster as ingestors "
            "land."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": True,
    },
    {
        "lane_id": "unified_features",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": [
            "v2:features:latest:{symbol}:{timeframe}",
        ],
        "v2_native_target_keys": [
            "v2:features:latest:{symbol}:{timeframe}",
        ],
        "bridge_worker": None,
        "freshness": "per_market_cycle",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "dynamic_universe_expansion_beyond_3_symbols",
            "missing_external_source_required_fields_remain_marked",
        ],
        "next_migration_action": (
            "Expand to KNOWN_UNIVERSE; missing external-source-required "
            "fields stay marked OPERATOR_DECISION_REQUIRED."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "trainer_predictions",
        "classification": LANE_BRIDGE,
        "current_source_redis_keys": [
            "v2:trainer:bridge:{symbol}",
            "v2:prediction:{symbol}:{timeframe}",
        ],
        "v2_native_target_keys": [
            "v2:prediction:{symbol}:{timeframe}",
            "v2:trainer:heartbeat",
        ],
        "bridge_worker": "v2_trainer_bridge",
        "freshness": "bridge_dependent",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "v2_native_training_loop",
            "v2_native_checkpoint_artifact",
            "trainer_source_eq_V2_NATIVE_flag",
            "expected_move_after_cost_head",
            "confidence_calibration_artifact",
        ],
        "next_migration_action": (
            "Drive v2_trainer_bridge_exit_plan; emit predictions with "
            "trainer_source=V2_NATIVE only after retirement conditions met."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "risk_decisions",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": ["v2:risk:decisions"],
        "v2_native_target_keys": ["v2:risk:decisions"],
        "bridge_worker": None,
        "freshness": "per_intent",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "dynamic_universe_expansion_beyond_3_symbols",
        ],
        "next_migration_action": (
            "Risk gateway scales with symbol roster automatically once "
            "intents are produced."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": False,
    },
    {
        "lane_id": "orchestrator_decisions",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": ["v2:orchestrator:decisions"],
        "v2_native_target_keys": ["v2:orchestrator:decisions"],
        "bridge_worker": None,
        "freshness": "per_cycle",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "dynamic_universe_expansion_beyond_3_symbols",
        ],
        "next_migration_action": (
            "Orchestrator already arbitrates across active symbols; new "
            "symbols flow in automatically as ingestors and predictions "
            "land."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": False,
    },
    {
        "lane_id": "paper_intents",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": [
            "v2:paper:intents",
            "v2:paper:intents_held_by_paper_fill_gate",
        ],
        "v2_native_target_keys": [
            "v2:paper:intents",
            "v2:paper:intents_held_by_paper_fill_gate",
        ],
        "bridge_worker": None,
        "freshness": "per_intent",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "paper_fill_gate_block_reason_record_for_every_block",
        ],
        "next_migration_action": (
            "Land paper_fill_gate_record_block_reason remediation; the "
            "gate must keep failing closed but emit observable reasons."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "paper_ledger",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": ["v2:paper:ledger"],
        "v2_native_target_keys": ["v2:paper:ledger"],
        "bridge_worker": None,
        "freshness": "per_paper_event",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "fill_provenance_for_all_paper_fills",
        ],
        "next_migration_action": (
            "Keep paper ledger append-only; extend provenance recording."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": True,
    },
    {
        "lane_id": "position_history",
        "classification": LANE_NATIVE,
        "current_source_redis_keys": [
            "v2:positions:history:{symbol}",
            "v2:positions:tracker:heartbeat",
        ],
        "v2_native_target_keys": [
            "v2:positions:history:{symbol}",
            "v2:positions:tracker:heartbeat",
        ],
        "bridge_worker": None,
        "freshness": "tracker_daemon",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "position_dependent_observation_fields_only_populated_when_position_open",
        ],
        "next_migration_action": (
            "Tracker daemon already running; expand symbol roster as "
            "paper trading opens positions on new symbols."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": False,
    },
    {
        "lane_id": "alt_data",
        "classification": LANE_BRIDGE,
        "current_source_redis_keys": [
            "v2:altdata:candidate_score:{symbol}",
        ],
        "v2_native_target_keys": [
            "v2:altdata:candidate_score:{symbol}",
            "v2:altdata:snapshot:{symbol}",
        ],
        "bridge_worker": "v2_alt_data_symbol_candidate_publisher",
        "freshness": "publisher_cycle",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "altdata_snapshot_attached_to_replay_bundle",
            "external_source_required_token_metrics_decision",
            "external_source_required_onchain_decision",
        ],
        "next_migration_action": (
            "Land altdata_snapshot_attached_to_replay_bundle remediation."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "symbol_universe",
        "classification": LANE_BRIDGE,
        "current_source_redis_keys": [
            "v2:altdata:symbol_universe:candidates",
        ],
        "v2_native_target_keys": [
            "v2:altdata:symbol_universe:candidates",
            "v2:altdata:symbol_universe:approved_paper",
            "v2:altdata:symbol_universe:approved_training",
        ],
        "bridge_worker": "v2_alt_data_symbol_universe_scoring",
        "freshness": "publisher_cycle",
        "symbol_coverage": list(KNOWN_UNIVERSE),
        "missing_components": [
            "operator_governance_approval_for_dynamic_paper_roster",
        ],
        "next_migration_action": (
            "Surface candidate roster to operator governance; planner "
            "does NOT auto-adopt."
        ),
        "blocks_paper": False,
        "blocks_shutdown": True,
        "blocks_live": True,
    },
    {
        "lane_id": "website_pages",
        "classification": LANE_BRIDGE,
        "current_source_redis_keys": [],
        "v2_native_target_keys": [],
        "bridge_worker": "v2_frontend_public_payload_mirror",
        "freshness": "payload_publisher_cycle",
        "symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "missing_components": [
            "enterprise_terminal_layout_phase_1",
            "bridge_vs_native_labeling_in_ui",
        ],
        "next_migration_action": (
            "Execute v2_enterprise_website_parallel_lane_plan phase 1."
        ),
        "blocks_paper": False,
        "blocks_shutdown": False,
        "blocks_live": False,
    },
]


def build_bridge_dependency_inventory() -> dict[str, Any]:
    classification_counts: dict[str, int] = {}
    for lane in _LANE_INVENTORY:
        cls = lane["classification"]
        classification_counts[cls] = classification_counts.get(cls, 0) + 1
    return {
        "schema_version": SCHEMA_VERSION + "_bridge_dependency_inventory",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "lane_total": len(_LANE_INVENTORY),
        "classification_counts": classification_counts,
        "lanes": _LANE_INVENTORY,
        "active_symbol_coverage": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "known_universe": list(KNOWN_UNIVERSE),
    }


# ---------------------------------------------------------------------------
# Phase 2 - Dynamic symbol universe migration status
# ---------------------------------------------------------------------------


_PER_SYMBOL_ONBOARDING_CHECKLIST = (
    "price",
    "ohlcv",
    "orderbook",
    "funding_oi",
    "liquidation",
    "features",
    "prediction",
    "risk",
    "orchestrator",
    "paper_intent",
    "replay_evidence",
    "frontend_visibility",
)


def _onboarding_status_for_symbol(symbol: str) -> dict[str, str]:
    """Per-symbol onboarding state. Native = already running on V2."""
    if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
        return {item: "V2_NATIVE" for item in _PER_SYMBOL_ONBOARDING_CHECKLIST}
    return {item: "PLACEHOLDER_NOT_READY" for item in _PER_SYMBOL_ONBOARDING_CHECKLIST}


def build_dynamic_symbol_universe_migration_status() -> dict[str, Any]:
    legacy_symbols = list(KNOWN_UNIVERSE)
    v2_native_symbols = list(V2_NATIVE_ACTIVE_SYMBOLS)
    bridge_only_symbols: list[str] = []
    missing_v2_symbols = [
        s for s in legacy_symbols if s not in v2_native_symbols
    ]
    training_candidate_symbols: list[str] = list(missing_v2_symbols)
    paper_candidate_symbols: list[str] = list(missing_v2_symbols)
    excluded_symbols: list[dict[str, str]] = []

    onboarding = {
        sym: _onboarding_status_for_symbol(sym) for sym in legacy_symbols
    }

    return {
        "schema_version": (
            SCHEMA_VERSION + "_dynamic_symbol_universe_migration_status"
        ),
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "legacy_symbols": legacy_symbols,
        "legacy_symbol_count": len(legacy_symbols),
        "v2_native_symbols": v2_native_symbols,
        "v2_native_symbol_count": len(v2_native_symbols),
        "bridge_only_symbols": bridge_only_symbols,
        "bridge_only_symbol_count": len(bridge_only_symbols),
        "missing_v2_symbols": missing_v2_symbols,
        "missing_v2_symbol_count": len(missing_v2_symbols),
        "training_candidate_symbols": training_candidate_symbols,
        "paper_candidate_symbols": paper_candidate_symbols,
        "excluded_symbols": excluded_symbols,
        "per_symbol_onboarding_checklist": list(
            _PER_SYMBOL_ONBOARDING_CHECKLIST
        ),
        "per_symbol_onboarding_status": onboarding,
        "live_symbols_unchanged": True,
        "paper_symbols_unchanged_pending_governance": True,
        "training_symbols_unchanged_pending_governance": True,
        "symbol_universe_governance_required_for_any_adoption": True,
    }


# ---------------------------------------------------------------------------
# Phase 3 - V2-native ingestor migration plan
# ---------------------------------------------------------------------------


_INGESTOR_FAMILIES: list[dict[str, Any]] = [
    {
        "family": "binance_price_and_ohlcv",
        "v2_native_target_keys": [
            "v2:market:prices:{symbol}",
            "v2:market:ohlcv:binance:{symbol}:{timeframe}",
        ],
        "status": "PARTIAL_NATIVE_PRICE_ONLY",
        "missing_pieces": [
            "ohlcv_per_timeframe",
            "dynamic_symbol_expansion",
        ],
        "next_task": "v2_native_binance_ohlcv_dynamic_symbol_ingestor",
    },
    {
        "family": "binance_orderbook",
        "v2_native_target_keys": [
            "v2:market:orderbook:binance:{symbol}",
        ],
        "status": "PLACEHOLDER_NOT_READY",
        "missing_pieces": [
            "binance_usdm_orderbook_websocket",
            "depth_ladder_persistence",
        ],
        "next_task": "v2_native_binance_orderbook_dynamic_symbol_ingestor",
    },
    {
        "family": "binance_liquidation_wss",
        "v2_native_target_keys": [
            "v2:market:liquidations:{symbol}",
            "v2:market:liquidations:latest:{symbol}",
            "v2:market:liquidations:aggregate:{symbol}",
            "v2:market:liquidations:heartbeat",
        ],
        "status": "V2_NATIVE_RUNNING_LIMITED_SYMBOLS",
        "missing_pieces": [
            "per_symbol_coverage_for_remaining_universe",
        ],
        "next_task": "v2_native_liquidation_wss_dynamic_symbol_expansion",
    },
    {
        "family": "kucoin_secondary_feed",
        "v2_native_target_keys": [
            "v2:market:orderbook:kucoin:{symbol}",
            "v2:market:prices:kucoin:{symbol}",
        ],
        "status": "OPERATOR_DECISION_REQUIRED",
        "missing_pieces": [
            "operator_decision_to_enable_kucoin_feed",
        ],
        "next_task": "v2_native_kucoin_secondary_feed_operator_decision_brief",
    },
    {
        "family": "coinapi_top_of_book",
        "v2_native_target_keys": [
            "v2:market:coinapi:top_of_book:{symbol}",
        ],
        "status": "OPERATOR_DECISION_REQUIRED",
        "missing_pieces": [
            "operator_decision_to_enable_coinapi_feed",
        ],
        "next_task": "v2_native_coinapi_top_of_book_operator_decision_brief",
    },
    {
        "family": "coinank_bridge_to_native",
        "v2_native_target_keys": [
            "v2:altdata:coinank:funding_aggregate:{symbol}",
            "v2:altdata:coinank:long_short:{symbol}",
            "v2:altdata:coinank:liquidation_aggregate:{symbol}",
        ],
        "status": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "missing_pieces": [
            "per_symbol_payload",
            "paid_aggregator_decision",
        ],
        "next_task": "v2_native_coinank_per_symbol_publisher_phase_1",
    },
    {
        "family": "ta_unified_features",
        "v2_native_target_keys": [
            "v2:features:ta:{symbol}:{timeframe}",
            "v2:features:latest:{symbol}:{timeframe}",
        ],
        "status": "V2_NATIVE_LIMITED_SYMBOLS",
        "missing_pieces": [
            "dynamic_symbol_expansion",
        ],
        "next_task": "v2_native_feature_pipeline_dynamic_symbol_expansion",
    },
    {
        "family": "trainer_prediction",
        "v2_native_target_keys": [
            "v2:prediction:{symbol}:{timeframe}",
            "v2:trainer:heartbeat",
        ],
        "status": "V2_BRIDGE_FROM_LEGACY_REDIS",
        "missing_pieces": [
            "v2_native_training_loop",
            "trainer_source_eq_V2_NATIVE_flag",
        ],
        "next_task": "v2_trainer_bridge_exit_prediction_publisher_contract",
    },
    {
        "family": "risk_orchestrator_paper",
        "v2_native_target_keys": [
            "v2:risk:decisions",
            "v2:orchestrator:decisions",
            "v2:paper:intents",
            "v2:paper:ledger",
        ],
        "status": "V2_NATIVE_LIMITED_SYMBOLS",
        "missing_pieces": [
            "dynamic_symbol_expansion_follows_ingestors_and_predictions",
            "paper_fill_gate_block_reason_recording",
        ],
        "next_task": "v2_paper_fill_gate_record_block_reason",
    },
]


def build_v2_native_ingestor_migration_plan() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_v2_native_ingestor_migration_plan",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "ingestor_families": _INGESTOR_FAMILIES,
        "v2_writes_only_v2_namespace": True,
        "legacy_redis_read_only_through_approved_bridge_contracts": True,
    }


def build_next_20_ingestor_tasks() -> dict[str, Any]:
    base_tasks: list[dict[str, Any]] = [
        {
            "task_id": "v2_native_binance_ohlcv_dynamic_symbol_ingestor",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/native_ingestors/binance_ohlcv*.py"
            ),
            "writes_only": ["v2:market:ohlcv:binance:{symbol}:{timeframe}"],
            "tests_required": True,
            "forbidden_actions": [
                "no_old_redis_writes",
                "no_exchange_mutation",
                "no_live_or_canary_approval",
                "no_legacy_mutation",
            ],
        },
        {
            "task_id": "v2_native_binance_orderbook_dynamic_symbol_ingestor",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/native_ingestors/binance_orderbook*.py"
            ),
            "writes_only": ["v2:market:orderbook:binance:{symbol}"],
            "tests_required": True,
            "forbidden_actions": [
                "no_old_redis_writes",
                "no_exchange_mutation",
                "no_live_or_canary_approval",
                "no_legacy_mutation",
            ],
        },
        {
            "task_id": "v2_native_feature_pipeline_dynamic_symbol_expansion",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/feature_pipeline_native/**"
            ),
            "writes_only": [
                "v2:features:ta:{symbol}:{timeframe}",
                "v2:features:latest:{symbol}:{timeframe}",
            ],
            "tests_required": True,
            "forbidden_actions": [
                "no_old_redis_writes",
                "no_fake_features",
                "no_live_or_canary_approval",
            ],
        },
        {
            "task_id": "v2_native_liquidation_wss_dynamic_symbol_expansion",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/native_ingestors/liquidations_wss.py"
            ),
            "writes_only": [
                "v2:market:liquidations:{symbol}",
                "v2:market:liquidations:latest:{symbol}",
                "v2:market:liquidations:aggregate:{symbol}",
                "v2:market:liquidations:heartbeat",
            ],
            "tests_required": True,
            "forbidden_actions": [
                "no_synthetic_liquidation_events",
                "no_live_or_canary_approval",
            ],
        },
        {
            "task_id": "v2_native_coinank_per_symbol_publisher_phase_1",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/coinank_bridge/**"
            ),
            "writes_only": [
                "v2:altdata:coinank:funding_aggregate:{symbol}",
                "v2:altdata:coinank:long_short:{symbol}",
                "v2:altdata:coinank:liquidation_aggregate:{symbol}",
            ],
            "tests_required": True,
            "forbidden_actions": [
                "no_paid_aggregator_adoption_without_operator_decision",
                "no_old_redis_writes",
            ],
        },
        {
            "task_id": "v2_native_kucoin_secondary_feed_operator_decision_brief",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "claude_worklog/operator_decisions/kucoin_secondary_feed.md"
            ),
            "writes_only": [],
            "tests_required": False,
            "forbidden_actions": [
                "no_kucoin_writes_until_operator_decision",
            ],
        },
        {
            "task_id": "v2_native_coinapi_top_of_book_operator_decision_brief",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "claude_worklog/operator_decisions/coinapi_top_of_book.md"
            ),
            "writes_only": [],
            "tests_required": False,
            "forbidden_actions": [
                "no_coinapi_writes_until_operator_decision",
            ],
        },
        {
            "task_id": "v2_native_trainer_dataset_builder_from_replay_and_features",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/trainer_bridge/**"
            ),
            "writes_only": [
                "v2:trainer:dataset:manifest",
            ],
            "tests_required": True,
            "forbidden_actions": [
                "no_checkpoint_compatibility_claim",
                "no_policy_architecture_parity_claim",
                "no_live_or_canary_approval",
            ],
        },
        {
            "task_id": "v2_trainer_bridge_exit_prediction_publisher_contract",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/trainer_bridge/**"
            ),
            "writes_only": [
                "v2:prediction:{symbol}:{timeframe}",
                "v2:trainer:heartbeat",
            ],
            "tests_required": True,
            "forbidden_actions": [
                "no_checkpoint_deserialization_in_control_plane",
                "no_live_or_canary_approval",
            ],
        },
        {
            "task_id": "v2_paper_fill_gate_record_block_reason",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/paper_mode/**"
            ),
            "writes_only": [
                "v2:paper:intents",
                "v2:paper:intents_held_by_paper_fill_gate",
            ],
            "tests_required": True,
            "forbidden_actions": [
                "no_paper_fill_gate_weakening",
                "no_live_or_canary_approval",
            ],
        },
        {
            "task_id": "v2_replay_miner_attach_altdata_snapshot_to_bundle",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/edge_proof/replay_miner.py"
            ),
            "writes_only": [
                "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl",
            ],
            "tests_required": True,
            "forbidden_actions": [
                "no_fake_altdata",
                "no_fabricated_future_outcomes",
            ],
        },
        {
            "task_id": "v2_replay_miner_attach_feature_snapshot_id_and_hash",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/edge_proof/replay_miner.py"
            ),
            "writes_only": [
                "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl",
            ],
            "tests_required": True,
            "forbidden_actions": [
                "no_fake_feature_hashes",
            ],
        },
        {
            "task_id": "v2_native_funding_dynamic_symbol_expansion",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/native_ingestors/**"
            ),
            "writes_only": ["v2:market:funding:{symbol}"],
            "tests_required": True,
            "forbidden_actions": ["no_old_redis_writes"],
        },
        {
            "task_id": "v2_native_open_interest_dynamic_symbol_expansion",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/native_ingestors/**"
            ),
            "writes_only": ["v2:market:open_interest:{symbol}"],
            "tests_required": True,
            "forbidden_actions": ["no_old_redis_writes"],
        },
        {
            "task_id": "v2_native_position_history_dynamic_symbol_expansion",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/position_history/**"
            ),
            "writes_only": ["v2:positions:history:{symbol}"],
            "tests_required": True,
            "forbidden_actions": ["no_old_redis_writes"],
        },
        {
            "task_id": "v2_native_symbol_universe_governance_review_brief",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "claude_worklog/operator_decisions/symbol_universe_governance.md"
            ),
            "writes_only": [],
            "tests_required": False,
            "forbidden_actions": [
                "no_adoption_of_candidates_in_planner",
            ],
        },
        {
            "task_id": "website_enterprise_terminal_layout_phase_1",
            "owner": "claude",
            "reviewer": "codex",
            "scope": "v2/frontend/src/pages/**",
            "writes_only": [],
            "tests_required": True,
            "forbidden_actions": [
                "no_trading_controls",
                "no_live_or_canary_buttons",
                "no_shutdown_buttons",
                "no_adopt_buttons",
            ],
        },
        {
            "task_id": "website_enterprise_bottom_dock_bridge_vs_native_labels",
            "owner": "claude",
            "reviewer": "codex",
            "scope": "v2/frontend/src/pages/**",
            "writes_only": [],
            "tests_required": True,
            "forbidden_actions": [
                "no_v2_native_claim_for_bridge_data",
            ],
        },
        {
            "task_id": "v2_replay_miner_record_latency_seconds_for_paper_gate",
            "owner": "claude",
            "reviewer": "codex",
            "scope": (
                "v2/backend/app/services/edge_proof/replay_miner.py"
            ),
            "writes_only": [
                "claude_worklog/final_readiness/v2_post_hoc_replay_outcome_miner/latest/replay_outcome_bundles.jsonl",
            ],
            "tests_required": True,
            "forbidden_actions": ["no_fake_latency_values"],
        },
        {
            "task_id": "v2_report_center_surface_bridge_exit_status_as_p0",
            "owner": "claude",
            "reviewer": "codex",
            "scope": "v2/backend/app/services/report_center/**",
            "writes_only": [],
            "tests_required": True,
            "forbidden_actions": [
                "no_fake_readiness",
                "no_silent_blocker_suppression",
            ],
        },
    ]
    return {
        "schema_version": SCHEMA_VERSION + "_next_20_ingestor_tasks",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "task_count": len(base_tasks),
        "tasks": base_tasks,
    }


# ---------------------------------------------------------------------------
# Phase 4 - V2 trainer bridge-exit plan
# ---------------------------------------------------------------------------


def build_v2_trainer_bridge_exit_plan() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_v2_trainer_bridge_exit_plan",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "current_bridge_dependencies": {
            "legacy_hybrid_trainer_process": (
                "owned by legacy bot tree; we read its outputs read-only "
                "via the approved bridge."
            ),
            "legacy_prediction_keys_consumed_via_bridge": [
                "legacy:prediction:* (read-only via bridge worker)",
            ],
            "v2_trainer_bridge_payloads": [
                "v2:trainer:bridge:{symbol}",
                "v2:trainer:heartbeat",
            ],
        },
        "v2_native_target": {
            "feature_snapshots": "v2:features:latest:{symbol}:{timeframe}",
            "full_observation_vectors": (
                "v2:features:full_observation:{symbol}:{timeframe}"
            ),
            "compact_observation_vectors": (
                "v2:features:compact_observation:{symbol}:{timeframe}"
            ),
            "v2_native_policy_artifact": "v2:trainer:policy:{model_version}",
            "v2_native_checkpoint_artifact": (
                "v2:trainer:checkpoint:{checkpoint_id}"
            ),
            "v2_trainer_heartbeat": "v2:trainer:heartbeat",
            "v2_prediction_keys": "v2:prediction:{symbol}:{timeframe}",
        },
        "required_implementation_lanes": [
            "v2_native_training_dataset_builder",
            "v2_native_baseline_model_evaluator",
            "v2_native_training_loop",
            "v2_native_model_registry",
            "v2_native_checkpoint_safety_loader",
            "v2_native_prediction_publisher",
            "v2_native_confidence_calibration",
            "v2_native_expected_move_after_cost_head",
            "v2_native_paper_fill_gate_integration",
        ],
        "bridge_retirement_conditions": [
            "v2_produces_prediction_for_every_active_paper_or_training_symbol",
            "v2_prediction_includes_feature_snapshot_id",
            "v2_prediction_includes_trainer_source_eq_V2_NATIVE",
            "v2_prediction_includes_expected_move_after_cost_bps",
            "v2_prediction_includes_confidence_calibrated",
            "v2_prediction_is_evaluated_by_replay_miner",
            "codex_pass_on_native_prediction_publisher",
        ],
        "operator_gates": [
            "checkpoint_artifact_decision",
            "policy_architecture_decision",
            "live_or_canary_decision",
            "legacy_shutdown_decision",
        ],
        "current_state_blockers": [
            "v2_native_training_loop_not_yet_built",
            "v2_native_checkpoint_artifact_not_yet_published",
            "trainer_source_field_not_yet_emitted",
        ],
        "no_checkpoint_compatibility_claim": True,
        "no_policy_architecture_parity_claim": True,
        "no_legacy_checkpoint_deserialization_in_control_plane": True,
    }


# ---------------------------------------------------------------------------
# Phase 5 - V2 paper trader dynamic-symbol plan
# ---------------------------------------------------------------------------


def _paper_capability_for_symbol(symbol: str) -> dict[str, Any]:
    if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
        return {
            "can_ingest": True,
            "can_feature": True,
            "can_predict": True,
            "can_risk_check": True,
            "can_orchestrate": True,
            "can_paper_intent": True,
            "can_replay_mine": True,
            "paper_enabled_candidate": False,
            "missing_reason": (
                "symbol is already ACTIVE on V2; planner does not flip "
                "any paper enable flag - that is operator governance."
            ),
        }
    return {
        "can_ingest": False,
        "can_feature": False,
        "can_predict": False,
        "can_risk_check": False,
        "can_orchestrate": False,
        "can_paper_intent": False,
        "can_replay_mine": False,
        "paper_enabled_candidate": False,
        "missing_reason": (
            "no V2-native price/ohlcv/orderbook/feature/prediction "
            "pipeline yet for this symbol; onboarding tasks are in the "
            "ingestor migration plan."
        ),
    }


def build_v2_dynamic_paper_trading_plan() -> dict[str, Any]:
    per_symbol = {sym: _paper_capability_for_symbol(sym) for sym in KNOWN_UNIVERSE}
    return {
        "schema_version": SCHEMA_VERSION + "_v2_dynamic_paper_trading_plan",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "rules": [
            "no_live_symbols",
            "no_live_orders",
            "paper_symbols_only_through_governance",
            "strict_paper_fill_gate_remains",
            "no_forced_trades",
        ],
        "per_symbol_capability_matrix": per_symbol,
        "currently_paper_enabled_symbols": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "planner_does_not_enable_any_new_paper_symbol": True,
    }


# ---------------------------------------------------------------------------
# Phase 6 - Enterprise website parallel lane
# ---------------------------------------------------------------------------


def build_v2_enterprise_website_parallel_lane_plan() -> dict[str, Any]:
    return {
        "schema_version": (
            SCHEMA_VERSION + "_v2_enterprise_website_parallel_lane_plan"
        ),
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "principles": [
            "use_current_redis_evidence_where_native_missing",
            "label_every_bridge_as_V2_BRIDGE_FROM_LEGACY_REDIS",
            "label_V2_NATIVE_only_when_truly_native",
            "label_PLACEHOLDER_NOT_READY_where_missing",
            "keep_report_center_visible",
            "no_trading_controls",
            "no_live_or_canary_or_shutdown_or_adopt_buttons",
        ],
        "enterprise_terminal_layout": {
            "top_status_rail": [
                "live_gate_blocked_human_only_chip",
                "v2_native_lane_count_chip",
                "bridge_lane_count_chip",
                "missing_symbols_chip",
                "trainer_bridge_exit_state_chip",
                "report_center_freshness_chip",
            ],
            "symbol_watchlist": {
                "data_source": (
                    "v2:market:prices:{symbol} for active; "
                    "PLACEHOLDER_NOT_READY for KNOWN_UNIVERSE non-active"
                ),
                "no_adopt_button": True,
            },
            "tradingview_workspace": {
                "data_source": (
                    "v2:market:ohlcv:binance:{symbol}:{timeframe} when "
                    "available; PLACEHOLDER_NOT_READY otherwise"
                ),
                "no_order_buttons": True,
            },
            "signals_risk_orchestrator_panel": {
                "data_source": [
                    "v2:prediction:{symbol}:{timeframe}",
                    "v2:risk:decisions",
                    "v2:orchestrator:decisions",
                    "v2:paper:intents",
                ],
                "labels": "BRIDGE or NATIVE per prediction trainer_source",
            },
            "bottom_dock_tabs": [
                {"id": "binance_orderbook", "label_classification": LANE_PLACEHOLDER},
                {"id": "kucoin_orderbook", "label_classification": LANE_OPERATOR},
                {"id": "coinapi_top_of_book", "label_classification": LANE_OPERATOR},
                {"id": "liquidation_tape", "label_classification": LANE_NATIVE},
                {"id": "coinank_funding_oi_ls_liq", "label_classification": LANE_BRIDGE},
                {"id": "ta_matrix", "label_classification": LANE_NATIVE},
                {"id": "toxicity_regime_unified_features", "label_classification": LANE_NATIVE},
                {"id": "audit_lineage_ledger", "label_classification": LANE_NATIVE},
                {"id": "system_health", "label_classification": LANE_NATIVE},
            ],
        },
        "phase_1_tasks": [
            "website_enterprise_terminal_layout_phase_1",
            "website_enterprise_bottom_dock_bridge_vs_native_labels",
        ],
        "does_not_replace_migration_work": True,
    }


# ---------------------------------------------------------------------------
# Phase 7 - Automation integration status
# ---------------------------------------------------------------------------


def build_automation_integration_status(
    *,
    bridge_inventory: dict[str, Any],
    symbol_status: dict[str, Any],
    next_tasks: dict[str, Any],
) -> dict[str, Any]:
    counts = bridge_inventory.get("classification_counts", {})
    bridge_dep_count = (
        counts.get(LANE_BRIDGE, 0)
        + counts.get(LANE_PLACEHOLDER, 0)
        + counts.get(LANE_OPERATOR, 0)
    )
    v2_native_lane_count = counts.get(LANE_NATIVE, 0)
    bridge_lane_count = counts.get(LANE_BRIDGE, 0)
    legacy_ref_lane_count = counts.get(LANE_LEGACY_REF, 0)

    tasks = next_tasks.get("tasks", [])
    next_ingestor_task = next(
        (t["task_id"] for t in tasks if "ingestor" in t["task_id"]),
        None,
    )
    next_trainer_task = next(
        (t["task_id"] for t in tasks if "trainer" in t["task_id"]),
        None,
    )
    next_symbol_task = next(
        (t["task_id"] for t in tasks if "symbol_universe" in t["task_id"]),
        None,
    )
    next_website_task = next(
        (t["task_id"] for t in tasks if t["task_id"].startswith("website_")),
        None,
    )

    return {
        "schema_version": SCHEMA_VERSION + "_automation_integration_status",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "bridge_dependency_count": bridge_dep_count,
        "v2_native_lane_count": v2_native_lane_count,
        "bridge_lane_count": bridge_lane_count,
        "legacy_reference_lane_count": legacy_ref_lane_count,
        "dynamic_symbols_total": symbol_status["legacy_symbol_count"],
        "v2_native_symbols_total": symbol_status["v2_native_symbol_count"],
        "missing_symbols_total": symbol_status["missing_v2_symbol_count"],
        "trainer_bridge_exit_state": "BRIDGE_ACTIVE_NATIVE_TRAINER_NOT_YET_RUNNING",
        "next_ingestor_task": next_ingestor_task,
        "next_trainer_task": next_trainer_task,
        "next_symbol_task": next_symbol_task,
        "next_website_task": next_website_task,
        "primary_p0_mission": (
            "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION"
        ),
        "does_not_install_scheduler_or_daemon": True,
    }


# ---------------------------------------------------------------------------
# Phase 8 - First-batch task dispatch
# ---------------------------------------------------------------------------


_FIRST_BATCH_TASK_IDS = (
    "v2_native_binance_ohlcv_dynamic_symbol_ingestor",
    "v2_native_binance_orderbook_dynamic_symbol_ingestor",
    "v2_native_feature_pipeline_dynamic_symbol_expansion",
    "v2_native_trainer_dataset_builder_from_replay_and_features",
    "v2_trainer_bridge_exit_prediction_publisher_contract",
    "website_enterprise_terminal_layout_phase_1",
)


def build_first_batch_task_dispatch_status(
    next_tasks: dict[str, Any],
) -> dict[str, Any]:
    by_id = {t["task_id"]: t for t in next_tasks.get("tasks", [])}
    dispatch = []
    for task_id in _FIRST_BATCH_TASK_IDS:
        task = by_id.get(task_id)
        if task is None:
            dispatch.append(
                {
                    "task_id": task_id,
                    "status": "MISSING_FROM_TASK_LIST",
                    "owner": None,
                    "reviewer": None,
                }
            )
            continue
        dispatch.append(
            {
                "task_id": task_id,
                "status": "QUEUED",
                "owner": task.get("owner"),
                "reviewer": task.get("reviewer"),
                "scope": task.get("scope"),
                "writes_only": task.get("writes_only"),
                "tests_required": task.get("tests_required"),
                "forbidden_actions": task.get("forbidden_actions"),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION + "_first_batch_task_dispatch_status",
        "generated_utc": _utc_now_iso(),
        **_safety_block(),
        "dispatched_count": sum(1 for d in dispatch if d["status"] == "QUEUED"),
        "missing_count": sum(
            1 for d in dispatch if d["status"] == "MISSING_FROM_TASK_LIST"
        ),
        "tasks": dispatch,
        "planner_does_not_run_tasks_only_queues_them": True,
    }


# ---------------------------------------------------------------------------
# Phase 9 - Public operator dashboard payload
# ---------------------------------------------------------------------------


def build_operator_dashboard_payload(
    *,
    bridge_inventory: dict[str, Any],
    symbol_status: dict[str, Any],
    trainer_plan: dict[str, Any],
    automation_status: dict[str, Any],
    first_batch: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": _utc_now_iso(),
        "go_no_go": (
            "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION_READY"
        ),
        "safety_scoreboard": _safety_block(),
        "summary": {
            "lane_total": bridge_inventory["lane_total"],
            "v2_native_lane_count": automation_status["v2_native_lane_count"],
            "bridge_lane_count": automation_status["bridge_lane_count"],
            "bridge_dependency_count": automation_status["bridge_dependency_count"],
            "dynamic_symbols_total": automation_status["dynamic_symbols_total"],
            "v2_native_symbols_total": automation_status["v2_native_symbols_total"],
            "missing_symbols_total": automation_status["missing_symbols_total"],
            "trainer_bridge_exit_state": automation_status[
                "trainer_bridge_exit_state"
            ],
        },
        "next_actions": {
            "next_ingestor_task": automation_status["next_ingestor_task"],
            "next_trainer_task": automation_status["next_trainer_task"],
            "next_symbol_task": automation_status["next_symbol_task"],
            "next_website_task": automation_status["next_website_task"],
        },
        "first_batch_queued": [t["task_id"] for t in first_batch["tasks"]],
        "trainer_bridge_retirement_conditions": trainer_plan[
            "bridge_retirement_conditions"
        ],
        "controls_present": False,
        "fake_readiness": False,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class BridgeExitPaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root: Path) -> BridgeExitPaths:
    return BridgeExitPaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest",
    )


@dataclass
class BridgeExitRunResult:
    go_no_go: str
    paths_written: list[Path] = field(default_factory=list)


def run_bridge_exit_packet(paths: BridgeExitPaths) -> BridgeExitRunResult:
    bridge_inventory = build_bridge_dependency_inventory()
    symbol_status = build_dynamic_symbol_universe_migration_status()
    ingestor_plan = build_v2_native_ingestor_migration_plan()
    next_tasks = build_next_20_ingestor_tasks()
    trainer_plan = build_v2_trainer_bridge_exit_plan()
    paper_plan = build_v2_dynamic_paper_trading_plan()
    website_plan = build_v2_enterprise_website_parallel_lane_plan()
    automation_status = build_automation_integration_status(
        bridge_inventory=bridge_inventory,
        symbol_status=symbol_status,
        next_tasks=next_tasks,
    )
    first_batch = build_first_batch_task_dispatch_status(next_tasks)
    dashboard = build_operator_dashboard_payload(
        bridge_inventory=bridge_inventory,
        symbol_status=symbol_status,
        trainer_plan=trainer_plan,
        automation_status=automation_status,
        first_batch=first_batch,
    )

    _atomic_write_json(
        paths.packet_dir / "bridge_dependency_inventory.json",
        bridge_inventory,
    )
    _atomic_write_json(
        paths.packet_dir / "v2_dynamic_symbol_universe_migration_status.json",
        symbol_status,
    )
    _atomic_write_json(
        paths.packet_dir / "v2_native_ingestor_migration_plan.json",
        ingestor_plan,
    )
    _atomic_write_json(
        paths.packet_dir / "next_20_ingestor_tasks.json", next_tasks
    )
    _atomic_write_json(
        paths.packet_dir / "v2_trainer_bridge_exit_plan.json", trainer_plan
    )
    _atomic_write_json(
        paths.packet_dir / "v2_dynamic_paper_trading_plan.json", paper_plan
    )
    _atomic_write_json(
        paths.packet_dir / "v2_enterprise_website_parallel_lane_plan.json",
        website_plan,
    )
    _atomic_write_json(
        paths.packet_dir / "automation_integration_status.json",
        automation_status,
    )
    _atomic_write_json(
        paths.packet_dir / "first_batch_task_dispatch_status.json", first_batch
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )

    report_md = _render_report(
        bridge_inventory=bridge_inventory,
        symbol_status=symbol_status,
        ingestor_plan=ingestor_plan,
        next_tasks=next_tasks,
        trainer_plan=trainer_plan,
        paper_plan=paper_plan,
        website_plan=website_plan,
        automation_status=automation_status,
        first_batch=first_batch,
        dashboard=dashboard,
    )
    _atomic_write_text(
        paths.packet_dir
        / "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION_REPORT.md",
        report_md,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION_READY\n",
    )

    return BridgeExitRunResult(
        go_no_go=(
            "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION_READY"
        ),
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION_REPORT.md",
            paths.packet_dir / "bridge_dependency_inventory.json",
            paths.packet_dir / "v2_dynamic_symbol_universe_migration_status.json",
            paths.packet_dir / "v2_native_ingestor_migration_plan.json",
            paths.packet_dir / "next_20_ingestor_tasks.json",
            paths.packet_dir / "v2_trainer_bridge_exit_plan.json",
            paths.packet_dir / "v2_dynamic_paper_trading_plan.json",
            paths.packet_dir
            / "v2_enterprise_website_parallel_lane_plan.json",
            paths.packet_dir / "automation_integration_status.json",
            paths.packet_dir / "first_batch_task_dispatch_status.json",
            paths.public_dir / "operator_dashboard_payload.json",
        ],
    )


def _render_report(
    *,
    bridge_inventory: dict[str, Any],
    symbol_status: dict[str, Any],
    ingestor_plan: dict[str, Any],
    next_tasks: dict[str, Any],
    trainer_plan: dict[str, Any],
    paper_plan: dict[str, Any],
    website_plan: dict[str, Any],
    automation_status: dict[str, Any],
    first_batch: dict[str, Any],
    dashboard: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append(
        "# V2 Native Runtime Bridge-Exit and Dynamic Symbol Migration\n\n"
    )
    lines.append(
        "GO/NO-GO: "
        "V2_NATIVE_RUNTIME_BRIDGE_EXIT_AND_DYNAMIC_SYMBOL_MIGRATION_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false. "
        "approves_canary=false. approves_legacy_shutdown=false. "
        "approves_redis_trim=false.\n\n"
    )

    lines.append("## Phase 1 - Bridge dependency inventory\n")
    counts = bridge_inventory["classification_counts"]
    for cls, n in sorted(counts.items()):
        lines.append(f"- {cls}: {n}\n")
    lines.append("\n")

    lines.append("## Phase 2 - Dynamic symbol universe\n")
    lines.append(f"- legacy_symbol_count: {symbol_status['legacy_symbol_count']}\n")
    lines.append(
        f"- v2_native_symbol_count: {symbol_status['v2_native_symbol_count']}\n"
    )
    lines.append(
        f"- missing_v2_symbol_count: {symbol_status['missing_v2_symbol_count']}\n"
    )
    lines.append(
        f"- training_candidate_count: {len(symbol_status['training_candidate_symbols'])}\n"
    )
    lines.append(
        f"- paper_candidate_count: {len(symbol_status['paper_candidate_symbols'])}\n"
    )
    lines.append(
        "- live_symbols_unchanged: True | paper/training symbols unchanged "
        "pending governance.\n\n"
    )

    lines.append("## Phase 3 - V2-native ingestor migration plan\n")
    for fam in ingestor_plan["ingestor_families"]:
        lines.append(
            f"- {fam['family']}: {fam['status']} -> next: {fam['next_task']}\n"
        )
    lines.append(f"\nNext-task queue size: {next_tasks['task_count']}\n\n")

    lines.append("## Phase 4 - Trainer bridge-exit plan\n")
    lines.append(
        f"- current bridge: legacy hybrid trainer (read-only) + "
        f"v2:trainer:bridge:*\n"
        f"- retirement conditions: "
        f"{len(trainer_plan['bridge_retirement_conditions'])} items\n"
        f"- operator gates: "
        f"{len(trainer_plan['operator_gates'])} items\n"
        f"- no_checkpoint_compatibility_claim: True | "
        f"no_policy_architecture_parity_claim: True\n\n"
    )

    lines.append("## Phase 5 - Dynamic paper trading plan\n")
    lines.append(
        f"- currently_paper_enabled_symbols: "
        f"{paper_plan['currently_paper_enabled_symbols']}\n"
        "- planner_does_not_enable_any_new_paper_symbol: True\n\n"
    )

    lines.append("## Phase 6 - Enterprise website parallel lane\n")
    layout = website_plan["enterprise_terminal_layout"]
    lines.append(
        f"- bottom_dock_tabs: {len(layout['bottom_dock_tabs'])} "
        f"(each labeled with classification)\n"
        f"- phase_1_tasks: {website_plan['phase_1_tasks']}\n"
        f"- does_not_replace_migration_work: "
        f"{website_plan['does_not_replace_migration_work']}\n\n"
    )

    lines.append("## Phase 7 - Automation integration\n")
    for k in (
        "bridge_dependency_count",
        "v2_native_lane_count",
        "bridge_lane_count",
        "dynamic_symbols_total",
        "v2_native_symbols_total",
        "missing_symbols_total",
        "trainer_bridge_exit_state",
        "next_ingestor_task",
        "next_trainer_task",
        "next_symbol_task",
        "next_website_task",
    ):
        lines.append(f"- {k}: {automation_status.get(k)}\n")
    lines.append("\n")

    lines.append("## Phase 8 - First-batch task dispatch\n")
    for t in first_batch["tasks"]:
        lines.append(f"- {t['task_id']} [{t['status']}]\n")
    lines.append("\n")

    lines.append("## Phase 9 - Public operator dashboard\n")
    lines.append(
        "- public_path: v2/frontend/public/v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/latest/"
        "operator_dashboard_payload.json\n"
    )
    lines.append(
        f"- controls_present: {dashboard['controls_present']} | "
        f"fake_readiness: {dashboard['fake_readiness']}\n\n"
    )

    lines.append("## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append(f"- {k}: {v}\n")
    lines.append("\n")

    lines.append("## What this packet did NOT do\n")
    lines.append(
        "- Did not modify /home/wali/Desktop/AI BOT.\n"
        "- Did not stop legacy or V2 runtime.\n"
        "- Did not stop the report center, replay miner, continuous "
        "remediation, or Codex governors.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not change leverage or margin mode.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not mutate live_symbols, paper_symbols, or training_symbols.\n"
        "- Did not adopt any Symbol Universe candidate.\n"
        "- Did not weaken the paper-fill gate.\n"
        "- Did not deserialize any legacy checkpoint into the control plane.\n"
        "- Did not claim policy-architecture parity.\n"
        "- Did not expose any raw API key.\n"
    )
    return "".join(lines)
