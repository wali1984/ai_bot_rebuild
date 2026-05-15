from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_controller():
    root = Path(__file__).resolve().parents[5]
    path = root / "claude_worklog/tools/codex_legacy_shutdown_readiness_takeover.py"
    spec = importlib.util.spec_from_file_location("codex_shutdown_takeover", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _base_evidence():
    return {
        "runtime_safety": {
            "final_approval_token": "absent",
            "redis_trim_approval": "absent",
            "live_gate": "blocked_human_only",
            "observed_live_gate_values": ["blocked_human_only"],
            "live_symbols": [],
            "old_redis_writes_absent": True,
            "exchange_actions_absent": True,
            "leverage_changes_absent": True,
            "margin_mode_changes_absent": True,
        },
        "git_corruption": (False, ""),
        "closure": {
            "copied_source_files_on_disk": 248,
            "binary_checkpoint_blobs_inventoried_only": 139,
            "full_runtime_manifest_valid": True,
            "genuine_unresolved_items": [],
        },
        "worker_porting": {"blockers": []},
        "risk_gateway_tests": {"missing_terms": []},
        "worker_parity_markers": {
            "v2_signal_publisher": {"pass_evidence_present": True},
            "v2_orchestrator_adapter": {"pass_evidence_present": True},
            "v2_market_ingestor_from_legacy_baseline": {"pass_evidence_present": True},
            "v2_coinank_and_liquidation_bridge_from_legacy_baseline": {"pass_evidence_present": True},
            "v2_feature_pipeline_ta_worker_from_legacy_baseline": {"pass_evidence_present": True},
            "v2_feature_pipeline_and_ta_worker_from_legacy_baseline": {"pass_evidence_present": True},
        },
        "trainer_bridge": {"blockers": []},
        "trainer_external_packages": {"missing": []},
        "paper_runtime": {
            "blockers": ["paper_realized_pnl_negative", "fills_flat_recent_window"],
        },
        "paper_shadow": {"blockers": []},
        "paper_edge": {"blockers": ["paper_shadow_profitability_proof_negative", "blocked_intents_present"]},
        "paper_post_filter": {
            "historical_negative_pnl_isolated": True,
            "post_filter_realized_pnl_delta_usdt": 0.0,
            "post_filter_safety_classification": "POST_FILTER_NO_UNSAFE_FILLS",
            "post_filter_simulated_fills": 0,
            "no_unsafe_fills": True,
            "positive_edge_proven": False,
        },
        "trade_permission": {
            "blockers": ["trade_permission_readonly_unknown"],
            "paper_only_operator_decision_required": True,
        },
        "symbol_universe": {"blockers": []},
        "public_freshness": {"stale_count": 0},
        "service_liveness": {"inactive_units": []},
    }


def test_post_filter_historical_pnl_is_live_only_while_edge_stays_blocking():
    controller = _load_controller()
    blockers = controller.collect_blockers(_base_evidence())
    pnl_blockers = [item for item in blockers if item["id"] == "PAPER_PNL_NEGATIVE_BLOCKS_CANARY"]
    edge_blockers = [item for item in blockers if item["id"] == "PAPER_EDGE_UNPROVEN"]

    assert pnl_blockers
    assert all(item["category"] == "P2_LIVE_ONLY_BLOCKED" for item in pnl_blockers)
    assert edge_blockers
    assert any(item["category"] == "P0_SHUTDOWN_BLOCKER" for item in edge_blockers)
    assert any("positive edge is not proven" in item["evidence"] for item in edge_blockers)


def test_trade_permission_unknown_requires_operator_decision_for_paper_only():
    controller = _load_controller()
    blockers = controller.collect_blockers(_base_evidence())
    trade = [item for item in blockers if item["id"] == "TRADE_PERMISSION_UNKNOWN_BLOCKS_CANARY"]

    assert len(trade) == 1
    assert trade[0]["category"] == "OPERATOR_DECISION_REQUIRED"
    assert "blocks live/canary" in trade[0]["evidence"]
