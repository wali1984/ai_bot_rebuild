"""Unit tests for V2 Website Rebuild Phase 1 — page + bridge contracts."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.website import page_contracts
from v2.backend.app.services.website.page_contracts import (
    Audience,
    ComponentStatus,
    DEFAULT_SAFETY_PINS,
    PAGES,
    PageContract,
    PlaceholderState,
    SourceType,
    build_contracts_status,
    frontend_registered_routes,
    page_by_id,
    page_to_dict,
    route_reconciliation_status,
    required_routes,
)
from v2.backend.app.services.website import redis_bridge_contracts as bridges
from v2.backend.app.services.website.redis_bridge_contracts import (
    ALLOWED_KEY_FAMILIES,
    BRIDGES,
    FORBIDDEN_KEY_HINTS,
    PREDICTION_KEY_CANDIDATE_ORDER,
    build_prediction_key_resolution_status,
    list_bridge_contracts,
    resolve_prediction_key,
    safe_bridge_read,
)


REQUIRED_PAGE_IDS = {
    "public-landing",
    "markets",
    "account-settings",
    "pro-chart",
    "public-status",
    "ai-brain",
    "trader",
    "history",
    "mission-control",
    "report-center",
    "risk-control",
    "config-admin",
    "paper-trading",
    "exchange-manager",
}


REQUIRED_ROUTES = {
    "/",  # router.tsx redirects "/" -> "/landing" (declared as alias on public-landing)
    "/landing",
    "/market",
    "/markets",
    "/account-settings",
    "/chart/:symbol?",
    "/status",
    "/ai-brain",
    "/trader",
    "/history",
    "/admin/mission-control",
    "/admin/report-center",
    "/admin/risk-control",
    "/admin/config-admin",
    "/admin/config",
    "/admin/paper-trading",
    "/admin/exchange-manager",
}


# ─────────────────────────────────────────────────────────────────────
# Page contracts
# ─────────────────────────────────────────────────────────────────────

def test_every_required_page_is_registered() -> None:
    have = {p.page_id for p in PAGES}
    assert REQUIRED_PAGE_IDS.issubset(have), REQUIRED_PAGE_IDS - have


def test_every_required_route_is_registered() -> None:
    assert set(required_routes()) == REQUIRED_ROUTES


def test_report_center_route_still_exists() -> None:
    assert page_by_id("report-center") is not None
    assert page_by_id("report-center").route == "/admin/report-center"  # type: ignore[union-attr]


def test_declared_phase_1_routes_are_registered_in_frontend() -> None:
    routes = frontend_registered_routes()
    missing = sorted(set(required_routes()) - set(routes))
    assert not missing


def test_route_reconciliation_status_is_clean() -> None:
    status = route_reconciliation_status()
    assert status["frontend_registered"] is True
    assert status["missing_frontend_routes"] == []
    assert "/admin/report-center" in status["frontend_routes"]


def test_route_aliases_are_registered_and_point_to_components() -> None:
    routes = frontend_registered_routes()
    for route in ("/", "/markets", "/admin/config"):
        assert route in routes, route
        assert routes[route], route


def test_page_contracts_expose_canonical_route_aliases_and_component_status() -> None:
    markets = page_by_id("markets")
    assert markets is not None
    d = page_to_dict(markets)
    assert d["canonical_route"] == "/market"
    assert "/markets" in d["aliases"]
    assert d["frontend_registered"] is True
    assert d["component_status"] in {status.value for status in ComponentStatus}
    assert "V2_NATIVE_PUBLIC_PAYLOAD" in d["source_labels"]


def test_every_page_carries_required_safety_pins() -> None:
    for p in PAGES:
        for s in DEFAULT_SAFETY_PINS:
            assert s in p.safety_pins, (p.page_id, s)


def test_paper_pages_require_active_trade_management_runtime_payload() -> None:
    expected = "/operator_runtime/v2_trade_management_paper/live/latest/v2_trade_management_paper_live_status.json"
    for page_id in ("trader", "history", "paper-trading"):
        page = page_by_id(page_id)
        assert page is not None
        assert expected in page.required_payloads
        assert "/v2_paper_online_runtime/latest/operator_dashboard_payload.json" not in page.required_payloads


def test_page_to_dict_carries_safety_quartet() -> None:
    for p in PAGES:
        d = page_to_dict(p)
        assert d["live_gate"] == "blocked_human_only"
        assert d["live_symbols"] == []
        assert d["approves_live"] is False
        assert d["approves_canary"] is False
        assert d["approves_legacy_shutdown"] is False
        assert d["approves_redis_trim"] is False


def test_missing_required_payload_yields_missing_payload_state() -> None:
    spec = PageContract(
        page_id="test-missing",
        route="/test-missing",
        audience=Audience.OPERATOR,
        plain_english_goal="test",
        required_payloads=("/this/does/not/exist.json",),
    )
    d = page_to_dict(spec)
    assert d["effective_placeholder_state"] == PlaceholderState.MISSING_PAYLOAD.value


def test_audience_counts_match_registry() -> None:
    status = build_contracts_status()
    assert status["audience_counts"]["PUBLIC"] >= 3
    assert status["audience_counts"]["OBSERVER"] >= 3
    assert status["audience_counts"]["OPERATOR"] >= 6


def test_no_page_declares_a_live_or_order_control() -> None:
    forbidden = ("live_button", "order_button", "shutdown_button", "adopt_symbol_button")
    for p in PAGES:
        text = " ".join((p.plain_english_goal, p.placeholder_state.value, p.source_type.value)).lower()
        for token in forbidden:
            assert token not in text, (p.page_id, token)


def test_phase_1_routes_match_actual_frontend_route_files() -> None:
    """Every route declared by a Phase-1 page contract must actually be
    registered by a frontend ``route.ts`` file. This test reads the
    repository's pages directory directly so the contract cannot drift
    from the website without a CI failure."""
    import os
    import re

    here = Path(__file__).resolve()
    repo_root = here.parents[6]
    pages_dir = repo_root / "v2" / "frontend" / "src" / "pages"
    assert pages_dir.exists(), pages_dir
    actual_routes: set[str] = set()
    actual_routes.add("/")  # router.tsx redirects "/" to "/landing"
    for route_file in pages_dir.glob("*/route.ts"):
        text = route_file.read_text(encoding="utf-8")
        m = re.search(r"path:\s*['\"]([^'\"]+)['\"]", text)
        if m:
            actual_routes.add(m.group(1))
    declared = set(required_routes())
    missing_in_frontend = declared - actual_routes
    assert not missing_in_frontend, (
        "Phase-1 contracts declare routes that are not registered "
        f"by any frontend route.ts file: {sorted(missing_in_frontend)}"
    )


def test_phase_1_status_flags_are_safe() -> None:
    status = build_contracts_status()
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["approves_canary"] is False
    assert status["approves_legacy_shutdown"] is False
    assert status["approves_redis_trim"] is False
    assert status["no_live_or_order_or_shutdown_or_adopt_symbol_controls_in_phase_1"] is True


# ─────────────────────────────────────────────────────────────────────
# Bridge contracts
# ─────────────────────────────────────────────────────────────────────

def test_bridge_ids_unique_and_describe_source_type() -> None:
    ids = [b.bridge_id for b in BRIDGES]
    assert len(ids) == len(set(ids))
    for b in BRIDGES:
        assert isinstance(b.source_type, SourceType), b.bridge_id


def test_bridge_safe_read_refuses_non_allowlisted_keys() -> None:
    assert safe_bridge_read("evil_key")["ok"] is False
    assert safe_bridge_read("")["ok"] is False
    # Forbidden secret-like tokens always refused.
    assert safe_bridge_read("v2:api_key=abc")["ok"] is False


def test_bridge_safe_read_accepts_known_v2_native_keys() -> None:
    # The bridge layer is allowed to call Redis for these patterns;
    # we don't assert success here (Redis may not be reachable in CI),
    # only that the gate accepts the key shape.
    for k in (
        "v2:paper:positions",
        "v2:risk:decisions",
        "v2:market:prices:BTCUSDT",
        "v2:dashboards:binance_top10:winners",
    ):
        # Check the allowlist patterns directly so we don't depend on
        # a running Redis.
        allowed_any = any(p.match(k) for p in ALLOWED_KEY_FAMILIES)
        assert allowed_any, k


def test_bridge_legacy_keys_are_clearly_labelled_non_v2_native() -> None:
    legacy_bridges = [b for b in BRIDGES if not b.is_v2_native]
    assert legacy_bridges, "at least one legacy bridge expected"
    for b in legacy_bridges:
        assert b.source_type in (
            SourceType.V2_BRIDGE_FROM_LEGACY_REDIS,
            SourceType.LEGACY_REFERENCE_ONLY,
            SourceType.PLACEHOLDER_NOT_READY,
        ), b.bridge_id


def test_bridge_v2_native_keys_are_labelled_v2_native() -> None:
    v2_native = [b for b in BRIDGES if b.is_v2_native]
    assert v2_native
    for b in v2_native:
        assert b.source_type == SourceType.V2_NATIVE_PUBLIC_PAYLOAD, b.bridge_id


def test_bridge_status_payload_safety_pins() -> None:
    payload = list_bridge_contracts()
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["frontend_must_not_read_redis_directly"] is True


# ─────────────────────────────────────────────────────────────────────
# Prediction key resolver
# ─────────────────────────────────────────────────────────────────────

def _stub_reader_factory(present_keys: dict[str, Any]):
    def _reader(key: str) -> dict[str, Any]:
        if key in present_keys:
            return {"ok": True, "value": present_keys[key], "reason": "stub", "key": key}
        return {"ok": True, "value": None, "reason": "not_present", "key": key}

    return _reader


def test_resolver_prefers_v2_native_when_available() -> None:
    reader = _stub_reader_factory({
        "v2:prediction:BTCUSDT:1m": {"confidence": 0.7, "direction": "LONG"},
        "prediction:BTCUSDT:5m": {"confidence": 0.4, "direction": "HOLD"},
    })
    res = resolve_prediction_key("BTCUSDT", redis_reader=reader)
    assert res["chosen_prediction_key"] == "v2:prediction:BTCUSDT:1m"
    assert res["source_type"] == "V2_NATIVE_PUBLIC_PAYLOAD"
    assert res["is_v2_native"] is True
    assert res["direction"] == "LONG"
    assert res["confidence"] == 0.7


def test_resolver_falls_back_to_multi_when_v2_missing() -> None:
    reader = _stub_reader_factory({
        "prediction:BTCUSDT:multi": {"confidence": 0.55, "direction": "LONG"},
        "prediction:BTCUSDT:5m": {"confidence": 0.5, "direction": "HOLD"},
    })
    res = resolve_prediction_key("BTCUSDT", redis_reader=reader)
    assert res["chosen_prediction_key"] == "prediction:BTCUSDT:multi"
    assert res["source_type"] == "V2_BRIDGE_FROM_LEGACY_REDIS"
    assert res["is_v2_native"] is False


def test_resolver_falls_back_to_5m_when_multi_missing() -> None:
    reader = _stub_reader_factory({
        "prediction:BTCUSDT:5m": {"confidence": 0.6, "direction": "SHORT"},
    })
    res = resolve_prediction_key("BTCUSDT", redis_reader=reader)
    assert res["chosen_prediction_key"] == "prediction:BTCUSDT:5m"
    assert res["source_type"] == "V2_BRIDGE_FROM_LEGACY_REDIS"
    assert res["is_v2_native"] is False
    assert res["direction"] == "SHORT"


def test_resolver_falls_back_to_1m_when_others_missing() -> None:
    reader = _stub_reader_factory({
        "prediction:BTCUSDT:1m": {"confidence": 0.66, "direction": "HOLD"},
    })
    res = resolve_prediction_key("BTCUSDT", redis_reader=reader)
    assert res["chosen_prediction_key"] == "prediction:BTCUSDT:1m"
    assert res["source_type"] == "V2_BRIDGE_FROM_LEGACY_REDIS"


def test_resolver_emits_explicit_missing_reason_when_no_candidate() -> None:
    reader = _stub_reader_factory({})
    res = resolve_prediction_key("BTCUSDT", redis_reader=reader)
    assert res["chosen_prediction_key"] is None
    assert res["source_type"] is None
    assert res["missing_reason"] == "no_prediction_key_present_in_any_candidate"


def test_resolver_candidate_order_matches_contract() -> None:
    order = [t for (t, _st) in PREDICTION_KEY_CANDIDATE_ORDER]
    assert order == [
        "v2:prediction:{symbol}:1m",
        "prediction:{symbol}:multi",
        "prediction:{symbol}:5m",
        "prediction:{symbol}:1m",
    ]


def test_build_prediction_key_resolution_status_safety_pins() -> None:
    # Force the resolver to "miss" by injecting a stub reader through the
    # public parameter; this avoids depending on a running Redis.
    stub = lambda key: {"ok": True, "value": None, "reason": "stub_miss", "key": key}
    payload = build_prediction_key_resolution_status(
        symbols=("BTCUSDT",), redis_reader=stub
    )
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["per_symbol"][0]["missing_reason"] == "no_prediction_key_present_in_any_candidate"
