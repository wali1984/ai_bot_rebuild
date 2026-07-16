"""V2 Website Rebuild — Phase 1 page contracts.

Every page the website is allowed to render in Phase 1 is declared here
as a pure data contract: route, audience, plain-English goal, required
and optional public payloads, optional Redis bridge keys, source type,
freshness window, placeholder state, and the safety pins the page
must surface.

The contracts are read-only data. They never call Redis, the exchange,
or any provider. They never expose raw API keys. Every contract carries
the live/canary/shutdown blocked safety pins; no contract authorizes
live trading, canary, shutdown, Symbol Universe adoption, or external
feed adoption.
"""
from __future__ import annotations

import enum
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[5]
PUBLIC_ROOT = REPO_ROOT / "v2" / "frontend" / "public"


class Audience(str, enum.Enum):
    PUBLIC = "PUBLIC"
    OBSERVER = "OBSERVER"
    OPERATOR = "OPERATOR"


class SourceType(str, enum.Enum):
    V2_NATIVE_PUBLIC_PAYLOAD = "V2_NATIVE_PUBLIC_PAYLOAD"
    V2_BRIDGE_FROM_LEGACY_REDIS = "V2_BRIDGE_FROM_LEGACY_REDIS"
    LEGACY_REFERENCE_ONLY = "LEGACY_REFERENCE_ONLY"
    PLACEHOLDER_NOT_READY = "PLACEHOLDER_NOT_READY"


class PlaceholderState(str, enum.Enum):
    OK = "OK"
    MISSING_PAYLOAD = "MISSING_PAYLOAD"
    STALE = "STALE"
    KEY_PRESENT_NO_CLIENT_YET = "KEY_PRESENT_NO_CLIENT_YET"
    V2_NATIVE_NOT_READY = "V2_NATIVE_NOT_READY"
    LEGACY_BRIDGE_SOURCE = "LEGACY_BRIDGE_SOURCE"
    OPERATOR_DECISION_REQUIRED = "OPERATOR_DECISION_REQUIRED"
    FEATURE_NOT_IMPLEMENTED = "FEATURE_NOT_IMPLEMENTED"
    DISPLAY_ONLY = "DISPLAY_ONLY"


class ComponentStatus(str, enum.Enum):
    IMPLEMENTED = "IMPLEMENTED"
    ALIAS_TO_EXISTING_PAGE = "ALIAS_TO_EXISTING_PAGE"
    PLACEHOLDER_WITH_CONTRACT = "PLACEHOLDER_WITH_CONTRACT"


DEFAULT_SAFETY_PINS: tuple[str, ...] = (
    "Live trading is blocked.",
    "Legacy shutdown is blocked.",
    "Recovery requires proof of edge before scaling.",
    "No fake readiness.",
    "Candidate symbols are not adopted automatically.",
)


@dataclass(frozen=True)
class PageContract:
    page_id: str
    route: str
    audience: Audience
    plain_english_goal: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    required_payloads: tuple[str, ...] = field(default_factory=tuple)
    optional_payloads: tuple[str, ...] = field(default_factory=tuple)
    redis_bridge_keys: tuple[str, ...] = field(default_factory=tuple)
    source_type: SourceType = SourceType.V2_NATIVE_PUBLIC_PAYLOAD
    source_labels: tuple[str, ...] = field(default_factory=tuple)
    component_status: ComponentStatus = ComponentStatus.IMPLEMENTED
    freshness_window_seconds: int = 5 * 60
    placeholder_state: PlaceholderState = PlaceholderState.OK
    safety_pins: tuple[str, ...] = field(default_factory=lambda: DEFAULT_SAFETY_PINS)


# Public payloads we already write today (Phase-1 surface only).
P = "/"  # marker for "any" relative to PUBLIC_ROOT
RPT = "/v2_report_center/latest/operator_dashboard_payload.json"
RPT_IDX = "/v2_report_center/latest/report_index.json"
EXEC_CC = "/v2_executive_command_center/latest/operator_dashboard_payload.json"
EXEC_SCORE = "/v2_executive_command_center/latest/production_readiness_scorecard.json"
SELF_HEAL = "/v2_autonomous_full_rebuild_self_healing/latest/operator_dashboard_payload.json"
PAPER_RUNTIME = "/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json"
FULL_OBS = "/operator_runtime/v2_rl_core/latest/full_observation_builder_status.json"
REM_DIM = "/v2_full_observation_remaining_dim_execution_queue/latest/operator_dashboard_payload.json"
COMPARATOR = "/v2_legacy_v2_production_comparator/latest/operator_dashboard_payload.json"
TOP10 = "/dashboards/binance_top10/latest/operator_dashboard_payload.json"
ALTDATA_CAND = "/operator_runtime/v2_alt_data_candidate_publisher/latest/v2_alt_data_candidate_publisher_status.json"
ALTDATA_PROV = "/operator_runtime/v2_alt_data_provider_registry/latest/v2_alt_data_provider_registry_status.json"
LIQ_HB = "/operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json"
POS_HIST = "/operator_runtime/v2_position_history_persistent_tracker/latest/position_history_persistent_tracker_status.json"
LIVE_CANARY = "/v2_live_canary_safety/latest/operator_dashboard_payload.json"
CAPITAL_GATE = "/v2_executive_command_center/latest/capital_recovery_gate_model.json"  # mirrored where present
MODEL_PATH = "/v2_model_path_decision_and_native_edge_proof_gate/latest/operator_dashboard_payload.json"
EDGE_PROOF = "/v2_native_edge_proof/latest/operator_dashboard_payload.json"
LEGACY_OBS = "/operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json"
COIN_INTEL = "/v2_coinank_market_intelligence/latest/operator_dashboard_payload.json"
SOAK_PE = "/v2_runtime_soak_and_production_equivalence/latest/operator_dashboard_payload.json"


PAGES: tuple[PageContract, ...] = (
    PageContract(
        page_id="public-landing",
        route="/landing",
        aliases=("/",),
        audience=Audience.PUBLIC,
        plain_english_goal=(
            "Show high-level system status and the five required safety strings;"
            " never imply live readiness."
        ),
        required_payloads=(RPT,),
        optional_payloads=(EXEC_CC, EXEC_SCORE, ALTDATA_PROV),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
    ),
    PageContract(
        page_id="markets",
        route="/market",
        aliases=("/markets",),
        audience=Audience.PUBLIC,
        plain_english_goal=(
            "Show the V2 top-10 dashboard plus liquidation WSS heartbeat;"
            " label CoinAnk/orderbook placeholders when no V2-native payload exists."
        ),
        required_payloads=(TOP10,),
        optional_payloads=(LIQ_HB, COIN_INTEL),
        redis_bridge_keys=(
            "v2:dashboards:binance_top10:*",
            "v2:market:liquidations:heartbeat",
            "v2:market:funding:{symbol}",
            "v2:market:open_interest:{symbol}",
            "v2:market:long_short:{symbol}",
            "v2:market:prices:{symbol}",
        ),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(
            SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,
            SourceType.V2_BRIDGE_FROM_LEGACY_REDIS.value,
        ),
        placeholder_state=PlaceholderState.OK,
    ),
    PageContract(
        page_id="account-settings",
        route="/account-settings",
        audience=Audience.OBSERVER,
        plain_english_goal=(
            "Show backend-authenticated trader profile, read-only exchange-account"
            " metadata, and trader-owned watchlist controls. Never accept private"
            " exchange values in the browser and never grant admin access."
        ),
        required_payloads=(),
        optional_payloads=(),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
        component_status=ComponentStatus.IMPLEMENTED,
        placeholder_state=PlaceholderState.OK,
    ),
    PageContract(
        page_id="pro-chart",
        route="/chart/:symbol?",
        audience=Audience.OBSERVER,
        plain_english_goal=(
            "Show read-only ProChart market data with source/freshness state,"
            " backend-authenticated watchlist favorites, and explicit stale or"
            " unavailable realtime stream status. Never show order controls."
        ),
        required_payloads=(),
        optional_payloads=(COIN_INTEL,),
        redis_bridge_keys=(
            "v2:market:prices:{symbol}",
            "v2:market:funding:{symbol}",
            "v2:market:open_interest:{symbol}",
        ),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(
            SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,
            SourceType.V2_BRIDGE_FROM_LEGACY_REDIS.value,
        ),
        component_status=ComponentStatus.IMPLEMENTED,
        placeholder_state=PlaceholderState.OK,
    ),
    PageContract(
        page_id="public-status",
        route="/status",
        audience=Audience.PUBLIC,
        plain_english_goal=(
            "Show the report center + executive command center + soak/PE status."
            " Render placeholders for any missing payload — never hide stale lanes."
        ),
        required_payloads=(RPT, EXEC_CC),
        optional_payloads=(SOAK_PE, SELF_HEAL),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
    ),
    PageContract(
        page_id="ai-brain",
        route="/ai-brain",
        audience=Audience.OBSERVER,
        plain_english_goal=(
            "Show the full-observation builder status, the model-path decision,"
            " the V2-vs-legacy comparator, and bridged trainer predictions."
            " Never claim policy-architecture parity or checkpoint compatibility."
        ),
        required_payloads=(FULL_OBS, MODEL_PATH),
        optional_payloads=(REM_DIM, COMPARATOR, EDGE_PROOF),
        redis_bridge_keys=(
            "v2:prediction:{symbol}:1m",
            "prediction:{symbol}:5m",
            "prediction:{symbol}:multi",
        ),
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        source_labels=(
            SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,
            SourceType.V2_BRIDGE_FROM_LEGACY_REDIS.value,
            SourceType.LEGACY_REFERENCE_ONLY.value,
        ),
        component_status=ComponentStatus.PLACEHOLDER_WITH_CONTRACT,
        placeholder_state=PlaceholderState.V2_NATIVE_NOT_READY,
    ),
    PageContract(
        page_id="trader",
        route="/trader",
        audience=Audience.OBSERVER,
        plain_english_goal=(
            "Show paper runtime status, paper positions, paper intents, held"
            " intents, and risk decisions. Live trading remains blocked."
        ),
        required_payloads=(PAPER_RUNTIME,),
        optional_payloads=(LIVE_CANARY,),
        redis_bridge_keys=(
            "v2:paper:positions",
            "v2:paper:intents",
            "v2:paper:intents_held_by_paper_fill_gate",
            "v2:paper:ledger",
            "v2:risk:decisions",
            "v2:orchestrator:decisions",
        ),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
        component_status=ComponentStatus.PLACEHOLDER_WITH_CONTRACT,
        placeholder_state=PlaceholderState.DISPLAY_ONLY,
    ),
    PageContract(
        page_id="history",
        route="/history",
        audience=Audience.OBSERVER,
        plain_english_goal=(
            "Show the V2 paper ledger and bridged signal history if available."
            " Replay/strategy backtests render as placeholders until V2-native."
        ),
        required_payloads=(PAPER_RUNTIME,),
        optional_payloads=(COMPARATOR,),
        redis_bridge_keys=(
            "v2:paper:ledger",
            "v2:paper:position_history:{symbol}",
            "signals:trading:primary",  # legacy bridge only
        ),
        source_type=SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
        source_labels=(
            SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,
            SourceType.V2_BRIDGE_FROM_LEGACY_REDIS.value,
            SourceType.LEGACY_REFERENCE_ONLY.value,
        ),
        component_status=ComponentStatus.PLACEHOLDER_WITH_CONTRACT,
        placeholder_state=PlaceholderState.LEGACY_BRIDGE_SOURCE,
    ),
    PageContract(
        page_id="mission-control",
        route="/admin/mission-control",
        audience=Audience.OPERATOR,
        plain_english_goal=(
            "Operator launching surface: report center, executive command center,"
            " blocker matrix, readiness scorecard, pending tasks. No live"
            " controls."
        ),
        required_payloads=(RPT, EXEC_CC),
        optional_payloads=(SELF_HEAL, EXEC_SCORE, MODEL_PATH),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
    ),
    PageContract(
        page_id="report-center",
        route="/admin/report-center",
        audience=Audience.OPERATOR,
        plain_english_goal=(
            "Realtime report center across every Claude/Codex/governor lane."
            " Stale lanes show as MISSING_PAYLOAD / stale=true; never hide."
        ),
        required_payloads=(RPT, RPT_IDX),
        optional_payloads=("/v2_report_center/latest/latest_codex_failures.json",),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
    ),
    PageContract(
        page_id="risk-control",
        route="/admin/risk-control",
        audience=Audience.OPERATOR,
        plain_english_goal=(
            "Show risk decisions, capital recovery gate model, and live/canary"
            " safety markers. Operator caps are OPERATOR_DECISION_REQUIRED;"
            " no cap-change controls in Phase 1."
        ),
        required_payloads=(EXEC_CC,),
        optional_payloads=(LIVE_CANARY, CAPITAL_GATE),
        redis_bridge_keys=("v2:risk:decisions",),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
        placeholder_state=PlaceholderState.OPERATOR_DECISION_REQUIRED,
    ),
    PageContract(
        page_id="config-admin",
        route="/admin/config-admin",
        aliases=("/admin/config",),
        audience=Audience.OPERATOR,
        plain_english_goal=(
            "Read-only config inventory in Phase 1. No mutation controls."
        ),
        required_payloads=(),
        optional_payloads=(EXEC_CC,),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
        placeholder_state=PlaceholderState.DISPLAY_ONLY,
    ),
    PageContract(
        page_id="paper-trading",
        route="/admin/paper-trading",
        audience=Audience.OPERATOR,
        plain_english_goal=(
            "Paper-only runtime view: paper PnL, paper fills, paper intents."
            " No live controls. Live trading is blocked."
        ),
        required_payloads=(PAPER_RUNTIME,),
        optional_payloads=(LIVE_CANARY,),
        redis_bridge_keys=(
            "v2:paper:positions",
            "v2:paper:intents",
            "v2:paper:intents_held_by_paper_fill_gate",
            "v2:paper:ledger",
        ),
        source_type=SourceType.V2_NATIVE_PUBLIC_PAYLOAD,
        source_labels=(SourceType.V2_NATIVE_PUBLIC_PAYLOAD.value,),
        placeholder_state=PlaceholderState.DISPLAY_ONLY,
    ),
    PageContract(
        page_id="exchange-manager",
        route="/admin/exchange-manager",
        audience=Audience.OPERATOR,
        plain_english_goal=(
            "Read-only exchange / API status. No connect / reconnect / mutation"
            " buttons in Phase 1. Live blocked."
        ),
        required_payloads=(),
        optional_payloads=(LIVE_CANARY, EXEC_CC),
        source_type=SourceType.PLACEHOLDER_NOT_READY,
        source_labels=(SourceType.PLACEHOLDER_NOT_READY.value,),
        placeholder_state=PlaceholderState.DISPLAY_ONLY,
    ),
)


_PAGE_IDS = {p.page_id for p in PAGES}
assert len(_PAGE_IDS) == len(PAGES), "duplicate page_id"
_ROUTES = [route for p in PAGES for route in (p.route, *p.aliases)]
assert len(set(_ROUTES)) == len(_ROUTES), "duplicate route or alias"


def _route_file_paths() -> Iterable[Path]:
    pages_root = REPO_ROOT / "v2" / "frontend" / "src" / "pages"
    if not pages_root.exists():
        return ()
    return pages_root.glob("*/route.ts")


def frontend_registered_routes() -> dict[str, str]:
    """Return actual frontend route paths and owning page folders.

    This intentionally reads only local TypeScript route metadata. The
    root route is registered in router.tsx as a redirect to /landing, so
    it is included as a router-level alias.
    MERGED_LEGACY_PATHS redirect sources are also included since they are
    registered router routes, just as redirects rather than page renderers.
    """
    routes: dict[str, str] = {}
    route_re = re.compile(r"path:\s*['\"]([^'\"]+)['\"]")
    # Strips optional param segments like /:symbol? and wildcard segments
    optional_re = re.compile(r"/:[^/]+\?$|/\*$")
    registry = REPO_ROOT / "v2" / "frontend" / "src" / "pages" / "registry.ts"
    registry_text = registry.read_text(encoding="utf-8") if registry.exists() else ""
    for route_file in _route_file_paths():
        text = route_file.read_text(encoding="utf-8")
        match = route_re.search(text)
        if not match:
            continue
        folder = route_file.parent.name
        # A route file alone is not enough; it must be imported by the
        # registry to actually render through the router. The registry has
        # used both barrel imports (from './folder') and per-file imports
        # (from './folder/route'); accept either form.
        registry_import_re = re.compile(
            rf"from\s+['\"]\./{re.escape(folder)}(?:/route)?['\"]"
        )
        if not registry_import_re.search(registry_text):
            continue
        raw_path = match.group(1)
        routes[raw_path] = folder
        # Also register the normalized base path (strip trailing optional params)
        base_path = optional_re.sub("", raw_path)
        if base_path and base_path != raw_path:
            routes.setdefault(base_path, folder)
    router = REPO_ROOT / "v2" / "frontend" / "src" / "router.tsx"
    if router.exists() and 'path: \'/\'' in router.read_text(encoding="utf-8"):
        routes["/"] = "router-root-redirect"
    # Include MERGED_LEGACY_PATHS redirect sources — these ARE registered routes
    nav_file = REPO_ROOT / "v2" / "frontend" / "src" / "pages" / "productNavigation.ts"
    if nav_file.exists():
        nav_text = nav_file.read_text(encoding="utf-8")
        # Parse the MERGED_LEGACY_PATHS block: find all '/path': '/target' entries
        legacy_key_re = re.compile(r"'(/[^']+)'\s*:\s*'(/[^']+)'")
        in_merged = False
        for line in nav_text.splitlines():
            if "MERGED_LEGACY_PATHS" in line and "=" in line:
                in_merged = True
            if in_merged:
                m = legacy_key_re.search(line)
                if m:
                    routes.setdefault(m.group(1), "merged-legacy-redirect")
                if line.strip().startswith("}") and ";" in line:
                    in_merged = False
    return routes


def route_reconciliation_status() -> dict[str, Any]:
    frontend_routes = frontend_registered_routes()
    declared = required_routes()
    missing = [route for route in declared if route not in frontend_routes]
    return {
        "frontend_registered": not missing,
        "declared_route_count": len(declared),
        "frontend_registered_route_count": len(frontend_routes),
        "missing_frontend_routes": missing,
        "declared_routes": declared,
        "frontend_routes": frontend_routes,
    }


def _file_age_seconds(path: Path) -> float | None:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None


def _resolve_public(rel: str) -> Path:
    return PUBLIC_ROOT / rel.lstrip("/")


def page_to_dict(contract: PageContract) -> dict[str, Any]:
    required = []
    for r in contract.required_payloads:
        p = _resolve_public(r)
        age = _file_age_seconds(p)
        required.append({
            "path": r,
            "exists": p.exists(),
            "age_seconds": age,
            "stale": (
                age is None
                or age > contract.freshness_window_seconds
            ),
        })
    optional = []
    for r in contract.optional_payloads:
        p = _resolve_public(r)
        age = _file_age_seconds(p)
        optional.append({
            "path": r,
            "exists": p.exists(),
            "age_seconds": age,
            "stale": (
                age is None
                or age > contract.freshness_window_seconds
            ),
        })
    # Effective placeholder state derived from runtime evidence.
    effective_state = contract.placeholder_state
    missing_required = any(not r["exists"] for r in required)
    stale_required = any(r["stale"] for r in required)
    if missing_required:
        effective_state = PlaceholderState.MISSING_PAYLOAD
    elif stale_required:
        effective_state = PlaceholderState.STALE
    frontend_routes = frontend_registered_routes()
    contract_routes = (contract.route, *contract.aliases)
    source_labels = list(dict.fromkeys((contract.source_type.value, *contract.source_labels)))
    return {
        "page_id": contract.page_id,
        "route": contract.route,
        "canonical_route": contract.route,
        "aliases": list(contract.aliases),
        "frontend_registered": all(route in frontend_routes for route in contract_routes),
        "frontend_registered_routes": {
            route: frontend_routes.get(route)
            for route in contract_routes
        },
        "component_status": contract.component_status.value,
        "audience": contract.audience.value,
        "plain_english_goal": contract.plain_english_goal,
        "required_payloads": required,
        "optional_payloads": optional,
        "redis_bridge_keys": list(contract.redis_bridge_keys),
        "source_type": contract.source_type.value,
        "source_labels": source_labels,
        "freshness_window_seconds": contract.freshness_window_seconds,
        "declared_placeholder_state": contract.placeholder_state.value,
        "effective_placeholder_state": effective_state.value,
        "safety_pins": list(contract.safety_pins),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
    }


def build_contracts_status() -> dict[str, Any]:
    pages = [page_to_dict(p) for p in PAGES]
    reconciliation = route_reconciliation_status()
    state_counts: dict[str, int] = {}
    for page in pages:
        state_counts[page["effective_placeholder_state"]] = (
            state_counts.get(page["effective_placeholder_state"], 0) + 1
        )
    return {
        "schema_version": "v2_website_rebuild_phase_1_page_contracts_v1",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "page_count": len(pages),
        "route_count": len(required_routes()),
        "pages": pages,
        "audience_counts": {
            audience.value: sum(1 for p in pages if p["audience"] == audience.value)
            for audience in Audience
        },
        "placeholder_state_counts": state_counts,
        "route_reconciliation": reconciliation,
        "safety_pins_required_on_every_operator_page": list(DEFAULT_SAFETY_PINS),
        "live_gate": "blocked_human_only",
        "live_symbols": [],
        "approves_live": False,
        "approves_canary": False,
        "approves_legacy_shutdown": False,
        "approves_redis_trim": False,
        "no_live_or_order_or_shutdown_or_adopt_symbol_controls_in_phase_1": True,
    }


def required_routes() -> list[str]:
    return [route for p in PAGES for route in (p.route, *p.aliases)]


def page_by_id(page_id: str) -> PageContract | None:
    for p in PAGES:
        if p.page_id == page_id:
            return p
    return None
