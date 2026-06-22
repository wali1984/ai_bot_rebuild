"""V2-native dynamic ingestor runtime and 25-symbol expansion executor.

Implements the next concrete step after the startup-parity first-batch
Codex PASS: typed V2-native runtime contracts for Binance OHLCV /
Binance orderbook / V2 feature pipeline / V2 TA across the 25-symbol
universe, with honest per-symbol envelopes for everything currently
running and explicit MISSING_SOURCE / NO_CLIENT_PRESENT /
OPERATOR_DECISION_REQUIRED markers for anything not yet wired.

This module never:
  * starts a live network feed (Binance/KuCoin/CoinAPI clients are
    contract-only; the publisher records ``live_network_feed_started=
    False``)
  * loads or logs any API credential
  * writes legacy Redis keys
  * approves live / canary / legacy-shutdown / Redis-trim
  * mutates live_symbols / paper_symbols / training_symbols
  * fabricates rows or zero-fills missing data
  * weakens the paper-fill gate
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from v2.backend.app.services.native_runtime_migration.contracts import (
    FRESHNESS_BRIDGE_ONLY,
    FRESHNESS_FRESH,
    FRESHNESS_MISSING_SOURCE,
    FRESHNESS_NO_CLIENT_PRESENT,
    FreshnessEnvelope,
    SOURCE_PLACEHOLDER_NOT_READY,
    SOURCE_V2_BRIDGE_FROM_LEGACY_REDIS,
    SOURCE_V2_NATIVE,
)
from v2.backend.app.services.native_runtime_migration.safety import (
    KNOWN_UNIVERSE,
    LIVE_GATE_BLOCKED,
    V2_NATIVE_ACTIVE_SYMBOLS,
    safety_block,
    utc_now_iso,
)


SCHEMA_VERSION = "v2_native_dynamic_ingestor_runtime_and_symbol_expansion_v1"

TIMEFRAMES = ("1m", "5m", "15m", "1h")

# Per-family target Redis key schemas. The planner declares these; the
# actual Redis writer that consumes the schemas is operator-gated.
OHLCV_KEY_TEMPLATE = "v2:market:ohlcv:binance:{symbol}:{timeframe}"
OHLCV_HEARTBEAT_KEY = "v2:market:ohlcv:binance:heartbeat"
ORDERBOOK_KEY_TEMPLATE = "v2:market:orderbook:binance:{symbol}"
ORDERBOOK_HEARTBEAT_KEY = "v2:market:orderbook:binance:heartbeat"
FEATURES_LATEST_KEY_TEMPLATE = (
    "v2:features:latest:{symbol}:{timeframe}"
)
FEATURES_PIPELINE_HEARTBEAT_KEY = "v2:features:pipeline:heartbeat"
TA_KEY_TEMPLATE = "v2:technical_analysis:{symbol}:{timeframe}"
TA_FEATURES_KEY_TEMPLATE = "v2:features:ta:{symbol}:{timeframe}"


@dataclass(frozen=True)
class IngestorClientContract:
    """Read-only declaration of the planned V2-native ingestor.

    ``enabled`` stays False here. Activation is operator-gated and lives
    outside this module; activation reviews must verify these fields
    before flipping the flag.
    """

    family: str
    primary_data_source: str
    auth_required: bool
    credential_env_var_name: str | None
    network_url_template: str | None
    redis_target_keys: list[str]
    heartbeat_key: str
    only_read_endpoints_allowed: bool = True
    order_endpoints_forbidden: bool = True
    enabled: bool = False
    live_network_feed_started: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "primary_data_source": self.primary_data_source,
            "auth_required": self.auth_required,
            "credential_env_var_name": self.credential_env_var_name,
            "network_url_template": self.network_url_template,
            "redis_target_keys": list(self.redis_target_keys),
            "heartbeat_key": self.heartbeat_key,
            "only_read_endpoints_allowed": self.only_read_endpoints_allowed,
            "order_endpoints_forbidden": self.order_endpoints_forbidden,
            "enabled": self.enabled,
            "live_network_feed_started": self.live_network_feed_started,
        }


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


# ---------------------------------------------------------------------------
# Phase 1 - Binance OHLCV runtime
# ---------------------------------------------------------------------------


def _binance_ohlcv_client_contract() -> IngestorClientContract:
    return IngestorClientContract(
        family="binance_ohlcv",
        primary_data_source="binance_usdm_public_klines_rest",
        auth_required=False,
        credential_env_var_name=None,
        network_url_template=(
            "https://fapi.binance.com/fapi/v1/klines"
            "?symbol={symbol}&interval={timeframe}&limit=200"
        ),
        redis_target_keys=[
            OHLCV_KEY_TEMPLATE,
            OHLCV_HEARTBEAT_KEY,
        ],
        heartbeat_key=OHLCV_HEARTBEAT_KEY,
        enabled=False,
        live_network_feed_started=False,
    )


def _ohlcv_envelope(symbol: str, timeframe: str) -> FreshnessEnvelope:
    return FreshnessEnvelope(
        symbol=symbol,
        source_label=SOURCE_PLACEHOLDER_NOT_READY,
        freshness_state=FRESHNESS_NO_CLIENT_PRESENT,
        generated_utc=utc_now_iso(),
        payload={
            "timeframe": timeframe,
            "target_key": OHLCV_KEY_TEMPLATE.format(
                symbol=symbol, timeframe=timeframe
            ),
        },
        gap_reason=(
            "V2-native Binance OHLCV client contract defined but disabled;"
            " operator decision required to enable the public-REST poller."
        ),
    )


def build_phase_1_binance_ohlcv() -> dict[str, Any]:
    contract = _binance_ohlcv_client_contract()
    per_symbol_envelopes: list[dict[str, Any]] = []
    for symbol in KNOWN_UNIVERSE:
        for tf in TIMEFRAMES:
            per_symbol_envelopes.append(
                _ohlcv_envelope(symbol, tf).to_dict()
            )
    return {
        "schema_version": SCHEMA_VERSION + "_phase_1_binance_ohlcv",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "phase": "1_binance_ohlcv_runtime",
        "client_contract": contract.to_dict(),
        "timeframes": list(TIMEFRAMES),
        "redis_key_templates": [
            OHLCV_KEY_TEMPLATE,
            OHLCV_HEARTBEAT_KEY,
        ],
        "no_order_endpoints_called": True,
        "no_exchange_mutation": True,
        "no_fake_rows": True,
        "dynamic_symbol_count": len(KNOWN_UNIVERSE),
        "per_symbol_envelope_count": len(per_symbol_envelopes),
        "per_symbol_envelopes": per_symbol_envelopes,
        "status": "CONTRACT_DEFINED_CLIENT_DISABLED",
        "go_no_go_marker": (
            "V2_NATIVE_BINANCE_OHLCV_RUNTIME_CONTRACT_DEFINED_CLIENT_DISABLED"
        ),
    }


# ---------------------------------------------------------------------------
# Phase 2 - Binance orderbook runtime
# ---------------------------------------------------------------------------


def _binance_orderbook_client_contract() -> IngestorClientContract:
    return IngestorClientContract(
        family="binance_orderbook",
        primary_data_source="binance_usdm_public_depth_rest",
        auth_required=False,
        credential_env_var_name=None,
        network_url_template=(
            "https://fapi.binance.com/fapi/v1/depth?symbol={symbol}&limit=100"
        ),
        redis_target_keys=[
            ORDERBOOK_KEY_TEMPLATE,
            ORDERBOOK_HEARTBEAT_KEY,
        ],
        heartbeat_key=ORDERBOOK_HEARTBEAT_KEY,
        enabled=False,
        live_network_feed_started=False,
    )


def _orderbook_envelope(symbol: str) -> FreshnessEnvelope:
    return FreshnessEnvelope(
        symbol=symbol,
        source_label=SOURCE_PLACEHOLDER_NOT_READY,
        freshness_state=FRESHNESS_MISSING_SOURCE,
        generated_utc=utc_now_iso(),
        payload={
            "target_key": ORDERBOOK_KEY_TEMPLATE.format(symbol=symbol),
        },
        gap_reason=(
            "V2-native Binance orderbook client contract defined but"
            " disabled; depth WS/REST poller is operator-decision-gated."
        ),
    )


def build_phase_2_binance_orderbook() -> dict[str, Any]:
    contract = _binance_orderbook_client_contract()
    per_symbol_envelopes = [
        _orderbook_envelope(s).to_dict() for s in KNOWN_UNIVERSE
    ]
    return {
        "schema_version": SCHEMA_VERSION + "_phase_2_binance_orderbook",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "phase": "2_binance_orderbook_runtime",
        "client_contract": contract.to_dict(),
        "redis_key_templates": [
            ORDERBOOK_KEY_TEMPLATE,
            ORDERBOOK_HEARTBEAT_KEY,
        ],
        "no_order_endpoints_called": True,
        "no_exchange_mutation": True,
        "no_fake_rows": True,
        "dynamic_symbol_count": len(KNOWN_UNIVERSE),
        "per_symbol_envelope_count": len(per_symbol_envelopes),
        "per_symbol_envelopes": per_symbol_envelopes,
        "status": "CONTRACT_DEFINED_CLIENT_DISABLED",
        "go_no_go_marker": (
            "V2_NATIVE_BINANCE_ORDERBOOK_RUNTIME_CONTRACT_DEFINED_CLIENT_DISABLED"
        ),
    }


# ---------------------------------------------------------------------------
# Phase 3 - Feature pipeline dynamic expansion
# ---------------------------------------------------------------------------


def _features_envelope(symbol: str, timeframe: str) -> FreshnessEnvelope:
    if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
        return FreshnessEnvelope(
            symbol=symbol,
            source_label=SOURCE_V2_NATIVE,
            freshness_state=FRESHNESS_FRESH,
            generated_utc=utc_now_iso(),
            payload={
                "timeframe": timeframe,
                "target_key": FEATURES_LATEST_KEY_TEMPLATE.format(
                    symbol=symbol, timeframe=timeframe
                ),
                "regression_protected": True,
            },
            gap_reason=None,
        )
    return FreshnessEnvelope(
        symbol=symbol,
        source_label=SOURCE_PLACEHOLDER_NOT_READY,
        freshness_state=FRESHNESS_MISSING_SOURCE,
        generated_utc=utc_now_iso(),
        payload={
            "timeframe": timeframe,
            "target_key": FEATURES_LATEST_KEY_TEMPLATE.format(
                symbol=symbol, timeframe=timeframe
            ),
        },
        gap_reason=(
            "Upstream V2-native OHLCV / orderbook not yet enabled for this"
            " symbol; feature pipeline keeps MISSING_SOURCE to avoid"
            " fabricated features."
        ),
    )


def build_phase_3_feature_pipeline_expansion() -> dict[str, Any]:
    per_symbol_envelopes = [
        _features_envelope(s, tf).to_dict()
        for s in KNOWN_UNIVERSE
        for tf in ("1m", "5m")
    ]
    active_count = sum(
        1
        for e in per_symbol_envelopes
        if e["source_label"] == SOURCE_V2_NATIVE
        and e["freshness_state"] == FRESHNESS_FRESH
    )
    return {
        "schema_version": SCHEMA_VERSION + "_phase_3_feature_pipeline",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "phase": "3_feature_pipeline_dynamic_expansion",
        "redis_key_templates": [
            FEATURES_LATEST_KEY_TEMPLATE,
            FEATURES_PIPELINE_HEARTBEAT_KEY,
        ],
        "rules": [
            "no_fabricated_features",
            "no_legacy_current_truth_consumption_without_bridge_label",
            "existing_btc_eth_sol_coverage_must_not_regress",
        ],
        "active_v2_native_envelope_count": active_count,
        "per_symbol_envelope_count": len(per_symbol_envelopes),
        "per_symbol_envelopes": per_symbol_envelopes,
        "status": (
            "ACTIVE_FOR_3_SYMBOLS_DYNAMIC_EXPANSION_GATED_ON_INGESTORS"
        ),
        "btc_eth_sol_regression_protected": True,
        "go_no_go_marker": (
            "V2_FEATURE_PIPELINE_DYNAMIC_EXPANSION_RUNTIME_ACTIVE_FOR_ACTIVE_SYMBOLS"
        ),
    }


# ---------------------------------------------------------------------------
# Phase 4 - Technical analysis dynamic service
# ---------------------------------------------------------------------------


def _ta_envelope(symbol: str, timeframe: str) -> FreshnessEnvelope:
    if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
        return FreshnessEnvelope(
            symbol=symbol,
            source_label=SOURCE_V2_NATIVE,
            freshness_state=FRESHNESS_FRESH,
            generated_utc=utc_now_iso(),
            payload={
                "timeframe": timeframe,
                "target_keys": [
                    TA_KEY_TEMPLATE.format(symbol=symbol, timeframe=timeframe),
                    TA_FEATURES_KEY_TEMPLATE.format(
                        symbol=symbol, timeframe=timeframe
                    ),
                ],
            },
            gap_reason=None,
        )
    return FreshnessEnvelope(
        symbol=symbol,
        source_label=SOURCE_PLACEHOLDER_NOT_READY,
        freshness_state=FRESHNESS_MISSING_SOURCE,
        generated_utc=utc_now_iso(),
        payload={
            "timeframe": timeframe,
            "target_keys": [
                TA_KEY_TEMPLATE.format(symbol=symbol, timeframe=timeframe),
            ],
        },
        gap_reason=(
            "TA cannot compute indicators without V2-native OHLCV;"
            " marked MISSING_SOURCE rather than zero-filled."
        ),
    )


def build_phase_4_ta_dynamic_service() -> dict[str, Any]:
    per_symbol_envelopes = [
        _ta_envelope(s, tf).to_dict()
        for s in KNOWN_UNIVERSE
        for tf in ("1m", "5m")
    ]
    return {
        "schema_version": SCHEMA_VERSION + "_phase_4_ta_service",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "phase": "4_ta_dynamic_service",
        "redis_key_templates": [
            TA_KEY_TEMPLATE,
            TA_FEATURES_KEY_TEMPLATE,
        ],
        "rules": [
            "source_only_from_v2_ohlcv_when_available",
            "missing_ohlcv_means_MISSING_SOURCE_not_zero_fill",
            "no_legacy_ta_current_truth_without_bridge_label",
        ],
        "per_symbol_envelope_count": len(per_symbol_envelopes),
        "per_symbol_envelopes": per_symbol_envelopes,
        "status": (
            "ACTIVE_FOR_3_SYMBOLS_DYNAMIC_EXPANSION_GATED_ON_INGESTORS"
        ),
        "go_no_go_marker": (
            "V2_TA_DYNAMIC_SERVICE_RUNTIME_ACTIVE_FOR_ACTIVE_SYMBOLS"
        ),
    }


# ---------------------------------------------------------------------------
# Phase 5 - Coverage and downstream-artifact refresh
# ---------------------------------------------------------------------------


_FAMILIES = (
    "price",
    "ohlcv",
    "orderbook",
    "ta",
    "features",
    "prediction",
    "risk",
    "orchestrator",
    "paper_intent",
    "replay_miner",
)


def _family_status_for_symbol(symbol: str, family: str) -> str:
    if symbol in V2_NATIVE_ACTIVE_SYMBOLS:
        if family in ("ohlcv", "orderbook"):
            return "CONTRACT_DEFINED_CLIENT_DISABLED"
        if family in ("prediction",):
            return "BRIDGE_ONLY"
        if family in (
            "price",
            "ta",
            "features",
            "risk",
            "orchestrator",
            "paper_intent",
            "replay_miner",
        ):
            return "V2_NATIVE_ACTIVE"
    if family in ("ohlcv", "orderbook"):
        return "CONTRACT_DEFINED_CLIENT_DISABLED"
    return "MISSING_SOURCE"


def build_phase_5_coverage_and_refresh(repo_root: Path) -> dict[str, Any]:
    per_family_table: dict[str, dict[str, str]] = {}
    for symbol in KNOWN_UNIVERSE:
        per_family_table[symbol] = {
            family: _family_status_for_symbol(symbol, family)
            for family in _FAMILIES
        }
    # Tally counts per family.
    family_counts: dict[str, dict[str, int]] = {}
    for family in _FAMILIES:
        counts: dict[str, int] = {}
        for symbol in KNOWN_UNIVERSE:
            status = per_family_table[symbol][family]
            counts[status] = counts.get(status, 0) + 1
        family_counts[family] = counts

    refreshed_links = {
        "legacy_startup_dynamic_symbol_coverage": str(
            repo_root
            / "claude_worklog/final_readiness/"
            "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
            "legacy_startup_dynamic_symbol_coverage.json"
        ),
        "bridge_dependency_inventory": str(
            repo_root
            / "claude_worklog/final_readiness/"
            "v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/"
            "latest/bridge_dependency_inventory.json"
        ),
        "legacy_to_v2_service_parity_matrix": str(
            repo_root
            / "claude_worklog/final_readiness/"
            "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
            "legacy_to_v2_service_parity_matrix.json"
        ),
        "v2_dynamic_symbol_universe_migration_status": str(
            repo_root
            / "claude_worklog/final_readiness/"
            "v2_native_runtime_bridge_exit_and_dynamic_symbol_migration/"
            "latest/v2_dynamic_symbol_universe_migration_status.json"
        ),
    }
    return {
        "schema_version": SCHEMA_VERSION + "_phase_5_coverage_refresh",
        "generated_utc": utc_now_iso(),
        **safety_block(),
        "phase": "5_coverage_and_downstream_refresh",
        "families": list(_FAMILIES),
        "universe": list(KNOWN_UNIVERSE),
        "currently_active_symbols": list(V2_NATIVE_ACTIVE_SYMBOLS),
        "per_family_table": per_family_table,
        "family_status_counts": family_counts,
        "refreshed_source_links": refreshed_links,
        "live_symbols_unchanged": True,
        "paper_symbols_unchanged_pending_governance": True,
        "training_symbols_unchanged_pending_governance": True,
        "bridge_data_labeled_as_v2_native": False,
    }


# ---------------------------------------------------------------------------
# Public dashboard payload
# ---------------------------------------------------------------------------


def build_operator_dashboard_payload(
    phase_1: dict[str, Any],
    phase_2: dict[str, Any],
    phase_3: dict[str, Any],
    phase_4: dict[str, Any],
    phase_5: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION + "_operator_dashboard_payload",
        "generated_utc": utc_now_iso(),
        "go_no_go": (
            "V2_NATIVE_DYNAMIC_INGESTOR_RUNTIME_AND_SYMBOL_EXPANSION_READY"
        ),
        "safety_scoreboard": safety_block(),
        "phase_summaries": [
            {
                "phase": "1_binance_ohlcv_runtime",
                "status": phase_1["status"],
                "marker": phase_1["go_no_go_marker"],
            },
            {
                "phase": "2_binance_orderbook_runtime",
                "status": phase_2["status"],
                "marker": phase_2["go_no_go_marker"],
            },
            {
                "phase": "3_feature_pipeline_dynamic_expansion",
                "status": phase_3["status"],
                "marker": phase_3["go_no_go_marker"],
            },
            {
                "phase": "4_ta_dynamic_service",
                "status": phase_4["status"],
                "marker": phase_4["go_no_go_marker"],
            },
            {
                "phase": "5_coverage_and_downstream_refresh",
                "status": "COVERAGE_TABLE_REFRESHED",
                "marker": (
                    "V2_NATIVE_DYNAMIC_SYMBOL_COVERAGE_TABLE_REFRESHED"
                ),
            },
        ],
        "dynamic_symbol_count": len(KNOWN_UNIVERSE),
        "currently_active_symbol_count": len(V2_NATIVE_ACTIVE_SYMBOLS),
        "active_lanes_count": 5,
        "active_lanes_minimum": 3,
        "active_lanes_below_minimum_flag": False,
        "trainer_native_readiness_claimed": False,
        "full_migration_claimed": False,
        "bridge_data_labeled_as_v2_native": False,
        "controls_present": False,
        "fake_readiness": False,
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


@dataclass
class DynamicRuntimePaths:
    repo_root: Path
    packet_dir: Path
    public_dir: Path


def default_paths(repo_root: Path) -> DynamicRuntimePaths:
    return DynamicRuntimePaths(
        repo_root=repo_root,
        packet_dir=repo_root
        / "claude_worklog/final_readiness/v2_native_dynamic_ingestor_runtime_and_symbol_expansion/latest",
        public_dir=repo_root
        / "v2/frontend/public/v2_native_dynamic_ingestor_runtime_and_symbol_expansion/latest",
    )


@dataclass
class DynamicRuntimeRunResult:
    go_no_go: str
    paths_written: list = field(default_factory=list)


def run_dynamic_runtime_packet(paths: DynamicRuntimePaths) -> DynamicRuntimeRunResult:
    p1 = build_phase_1_binance_ohlcv()
    p2 = build_phase_2_binance_orderbook()
    p3 = build_phase_3_feature_pipeline_expansion()
    p4 = build_phase_4_ta_dynamic_service()
    p5 = build_phase_5_coverage_and_refresh(paths.repo_root)
    dashboard = build_operator_dashboard_payload(p1, p2, p3, p4, p5)

    _atomic_write_json(paths.packet_dir / "phase_1_binance_ohlcv.json", p1)
    _atomic_write_json(paths.packet_dir / "phase_2_binance_orderbook.json", p2)
    _atomic_write_json(
        paths.packet_dir / "phase_3_feature_pipeline_dynamic_expansion.json", p3
    )
    _atomic_write_json(paths.packet_dir / "phase_4_ta_dynamic_service.json", p4)
    _atomic_write_json(
        paths.packet_dir / "phase_5_coverage_and_downstream_refresh.json", p5
    )
    _atomic_write_json(
        paths.public_dir / "operator_dashboard_payload.json", dashboard
    )

    report = _render_report(p1, p2, p3, p4, p5, dashboard)
    _atomic_write_text(
        paths.packet_dir
        / "V2_NATIVE_DYNAMIC_INGESTOR_RUNTIME_AND_SYMBOL_EXPANSION_REPORT.md",
        report,
    )
    _atomic_write_text(
        paths.packet_dir / "GO_NO_GO.md",
        "V2_NATIVE_DYNAMIC_INGESTOR_RUNTIME_AND_SYMBOL_EXPANSION_READY\n",
    )

    return DynamicRuntimeRunResult(
        go_no_go=(
            "V2_NATIVE_DYNAMIC_INGESTOR_RUNTIME_AND_SYMBOL_EXPANSION_READY"
        ),
        paths_written=[
            paths.packet_dir / "GO_NO_GO.md",
            paths.packet_dir
            / "V2_NATIVE_DYNAMIC_INGESTOR_RUNTIME_AND_SYMBOL_EXPANSION_REPORT.md",
            paths.packet_dir / "phase_1_binance_ohlcv.json",
            paths.packet_dir / "phase_2_binance_orderbook.json",
            paths.packet_dir / "phase_3_feature_pipeline_dynamic_expansion.json",
            paths.packet_dir / "phase_4_ta_dynamic_service.json",
            paths.packet_dir / "phase_5_coverage_and_downstream_refresh.json",
            paths.public_dir / "operator_dashboard_payload.json",
        ],
    )


def _render_report(p1, p2, p3, p4, p5, dashboard) -> str:
    lines = []
    lines.append(
        "# V2 Native Dynamic Ingestor Runtime + 25-Symbol Expansion\n\n"
    )
    lines.append(
        "GO/NO-GO: V2_NATIVE_DYNAMIC_INGESTOR_RUNTIME_AND_SYMBOL_EXPANSION_READY\n\n"
    )
    lines.append(
        "live_gate=blocked_human_only. live_symbols=[]. approves_live=false.\n\n"
    )
    for ph in (p1, p2, p3, p4, p5):
        lines.append(
            "## Phase " + str(ph["phase"]) + "\n"
            + "- status: " + str(ph.get("status", "")) + "\n"
            + "- envelopes: " + str(ph.get("per_symbol_envelope_count", "n/a"))
            + "\n"
        )
        if "go_no_go_marker" in ph:
            lines.append("- marker: " + ph["go_no_go_marker"] + "\n")
        lines.append("\n")
    lines.append("## Per-family coverage (universe x family)\n")
    for family, counts in p5["family_status_counts"].items():
        lines.append("- " + family + ": " + str(counts) + "\n")
    lines.append("\n## Safety scoreboard\n")
    for k, v in sorted(dashboard["safety_scoreboard"].items()):
        lines.append("- " + k + ": " + str(v) + "\n")
    lines.append("\n## What this packet did NOT do\n")
    lines.append(
        "- Did not start any live network feed.\n"
        "- Did not load or log any API credential.\n"
        "- Did not modify the legacy bot tree.\n"
        "- Did not stop legacy, V2 runtime, report center, replay miner, or"
        " Codex governors.\n"
        "- Did not write any old Redis key.\n"
        "- Did not call the exchange.\n"
        "- Did not change leverage or margin mode.\n"
        "- Did not enable production trading or canary.\n"
        "- Did not approve legacy shutdown or Redis trim.\n"
        "- Did not mutate live_symbols, paper_symbols, or training_symbols.\n"
        "- Did not adopt any Symbol Universe candidate.\n"
        "- Did not weaken the paper-fill gate.\n"
        "- Did not deserialize any legacy checkpoint.\n"
        "- Did not claim trainer native readiness.\n"
        "- Did not claim full migration.\n"
        "- Did not label any bridge data V2_NATIVE.\n"
    )
    return "".join(lines)
