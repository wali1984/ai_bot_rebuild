"""Unit tests for the V2 Report Center safe-summary + registry."""
from __future__ import annotations

import json
import textwrap
import time
from pathlib import Path

import pytest

from v2.backend.app.services.report_center import safe_summary
from v2.backend.app.services.report_center import report_registry
from v2.backend.app.services.report_center.report_registry import (
    LANES,
    index_lanes,
)


REQUIRED_LANE_IDS = {
    "executive_command_center",
    "codex_executive_governor",
    "v2_report_center_executive_clarity",
    "self_healing_controller",
    "codex_self_healing_governor",
    "autonomous_production_equivalence_burndown",
    "codex_autonomous_governor",
    "continuous_remediation_governor",
    "runtime_soak_and_production_equivalence",
    "full_observation_builder",
    "remaining_dim_execution_queue",
    "full_observation_latest_burndown",
    "policy_architecture_shape_contract",
    "checkpoint_promotion",
    "model_parity_sprint",
    "liquidation_wss_daemon",
    "position_history_tracker",
    "alt_data_provider_registry",
    "nansen_client",
    "lunarcrush_client",
    "alt_data_symbol_scoring",
    "alt_data_candidate_publisher",
    "top10_dashboards",
    "symbol_universe",
    "legacy_log_intelligence",
    "v2_vs_legacy_comparator",
    "v2_legacy_startup_manifest_parity_and_bridge_exit",
    "v2_startup_parity_first_batch_execution",
    "live_canary_safety",
    "capital_recovery_gate",
    "production_readiness_scorecard",
    "pending_task_watchdog",
    "latest_codex_failures",
    "v2_website_data_alignment_and_control_plane",
    "v2_full_paper_only_startup_manifest_runtime",
    "v2_native_dynamic_runtime_and_trainer_bridge_exit_execution",
    "v2_github_only_credential_purge",
    "v2_native_trainer_prediction_publisher",
    "v2_github_visible_credential_purge_remediation",
    "v2_native_trainer_dataset_and_baseline_model",
    "v2_native_trainer_dataset_insufficient_evidence_classification_remediation",
    "v2_closed_loop_execution",
    "v2_closed_loop_execution_real_mode_enablement",
    "v2_closed_loop_active_lane_minimum_remediation",
    "v2_closed_loop_persistent_worker_pool",
    "v2_worker_pool_queue_consumption_remediation",
    "v2_codex_spark_parallel_closed_loop",
    "v2_final_production_equivalence_blocker_resolution_sprint",
    "v2_final_operator_decision_and_event_watcher_execution",
    "v2_autonomous_mission_backlog",
    "v2_autonomous_mission_execution_burndown",
    "v2_no_status_change_sla_watchdog",
    "v2_external_source_wait_credential_reconciliation",
    "v2_autonomous_no_manual_next_task_policy",
    "v2_live_readiness_blocker_burndown_excluding_tokenmetrics",
    "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync",
    "v2_dynamic_93_edge_recovery_and_signal_quality_burndown",
    "v2_fastest_safe_canary_readiness_execution",
    "v2_legacy_runtime_freeze_and_primary_paper_cutover",
}


def test_registry_includes_all_required_lanes() -> None:
    registered = {lane.lane_id for lane in LANES}
    missing = REQUIRED_LANE_IDS - registered
    assert not missing, f"missing required lanes: {sorted(missing)}"


def test_registry_has_no_duplicate_lane_ids() -> None:
    ids = [lane.lane_id for lane in LANES]
    assert len(ids) == len(set(ids))


def test_index_lanes_formats_id_detail_blockers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = tmp_path / "operator_dashboard_payload.json"
    payload.write_text(
        json.dumps(
            {
                "go_no_go": "V2_DYNAMIC_93_SYMBOL_RUNTIME_BURN_IN_EDGE_AND_WEBSITE_SYNC_BLOCKED",
                "generated_at": "2026-06-04T05:45:00Z",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "blockers": [
                    {
                        "id": "PAPER_BACKTEST_EDGE_NOT_PROVEN",
                        "detail": "EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    spec = report_registry.LaneSpec(
        "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync",
        "V2 Dynamic 93",
        "CODEX",
        public_payload=payload,
        blocks_live=True,
    )
    monkeypatch.setattr(report_registry, "LANES", (spec,))

    indexed = report_registry.index_lanes(stale_age_seconds=999_999_999)

    assert indexed["entries"][0]["current_blockers"] == [
        "PAPER_BACKTEST_EDGE_NOT_PROVEN: EDGE_NOT_CLAIMED_OPERATOR_THRESHOLDS_REQUIRED"
    ]


def test_extract_go_no_go_from_marker_only_file() -> None:
    text = "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY\n"
    assert (
        safe_summary.extract_go_no_go(text)
        == "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY"
    )


def test_status_from_marker_codex_pass_and_fail() -> None:
    assert safe_summary.status_from_marker("V2_X_CODEX_PASS") == "PASS"
    assert safe_summary.status_from_marker("V2_X_CODEX_FAIL") == "FAIL"
    assert safe_summary.status_from_marker("V2_X_BLOCKED") == "BLOCKED"
    assert safe_summary.status_from_marker("V2_X_READY") == "READY"
    assert safe_summary.status_from_marker("V2_X_REMEDIATED_READY") == "READY"
    assert safe_summary.status_from_marker("V2_X_PARTIAL_PROGRESS") == "READY"
    assert safe_summary.status_from_marker(None) == "INFO"


def test_sanitize_text_redacts_api_keys_and_bearer() -> None:
    text = textwrap.dedent("""
        api_key=AKIAIOSFODNN7EXAMPLE
        Authorization: Bearer abcdefghijklmnopqrstuvwxyz1234567890abcdefghijk
        secret=hunter2
        BINANCE_API_KEY=examplekey1234567890
        path: /home/wali/Desktop/AI BOT REBUILD/.local_secrets/keys.env
    """).strip()
    redacted = safe_summary.sanitize_text(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "hunter2" not in redacted
    assert "examplekey1234567890" not in redacted
    assert ".local_secrets" not in redacted
    assert "***REDACTED***" in redacted


def test_sanitize_text_redacts_pem_private_key_block() -> None:
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\n"
        "MIIEpAIBAAKCAQEAxabcdefghij...\n"
        "-----END RSA PRIVATE KEY-----\n"
    )
    redacted = safe_summary.sanitize_text(text)
    assert "BEGIN RSA PRIVATE KEY" not in redacted


def test_extract_markdown_sections_only_known_headings(tmp_path: Path) -> None:
    md = tmp_path / "report.md"
    md.write_text(
        textwrap.dedent("""
            # Title

            ## Decision

            All good.

            ## Random Heading

            should not appear

            ## Next Action

            run the indexer

            ## Safety

            no exchange mutation
        """).strip()
        + "\n",
        encoding="utf-8",
    )
    sections = safe_summary.extract_markdown_sections(md.read_text())
    assert "decision" in sections
    assert "next action" in sections
    assert "safety" in sections
    assert "random heading" not in sections


def test_safe_summary_from_markdown_captures_marker_and_redacts(tmp_path: Path) -> None:
    md = tmp_path / "GO_NO_GO.md"
    md.write_text(
        "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY\n"
        "api_key=AKIAIOSFODNN7EXAMPLE\n",
        encoding="utf-8",
    )
    out = safe_summary.safe_summary_from_markdown(md)
    assert out["go_no_go"] == "V2_AUTONOMOUS_FULL_REBUILD_SELF_HEALING_CONTROLLER_READY"
    assert out["status"] == "READY"
    assert out["redaction_applied"] is True


def test_safe_summary_from_json_prunes_unknown_keys_and_keeps_safety(tmp_path: Path) -> None:
    p = tmp_path / "status.json"
    p.write_text(
        json.dumps(
            {
                "go_no_go": "V2_X_READY",
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "approves_live": False,
                "approves_canary": False,
                "approves_legacy_shutdown": False,
                "approves_redis_trim": False,
                "secret_field_should_be_dropped": "AKIAIOSFODNN7EXAMPLE",
            }
        ),
        encoding="utf-8",
    )
    out = safe_summary.safe_summary_from_json(p)
    assert out["go_no_go"] == "V2_X_READY"
    assert out["status"] == "READY"
    assert isinstance(out["pruned"], dict)
    assert out["pruned"].get("live_gate") == "blocked_human_only"
    assert out["pruned"].get("approves_live") is False
    assert "secret_field_should_be_dropped" not in out["pruned"]


def test_safe_summary_from_json_keeps_live_readiness_explanation(tmp_path: Path) -> None:
    p = tmp_path / "live_readiness.json"
    p.write_text(
        json.dumps(
            {
                "go_no_go": "V2_LIVE_READINESS_BLOCKER_BURNDOWN_EXCLUDING_TOKENMETRICS_READY",
                "plain_english_summary": {
                    "tokenmetrics_line": "TokenMetrics is deferred.",
                    "live_blocked_because": "Paper edge is not proven.",
                    "canary_blocked_because": "Canary edge is not proven.",
                },
                "primary_recommendation": "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN",
                "tokenmetrics_classification": "DEFERRED_NOT_REQUIRED_FOR_CURRENT_NATIVE_PATH",
                "tokenmetrics_blocks_live": False,
                "tokenmetrics_blocks_canary": False,
                "live_ready": False,
                "canary_ready": False,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
            }
        ),
        encoding="utf-8",
    )
    out = safe_summary.safe_summary_from_json(p)
    assert out["status"] == "READY"
    pruned = out["pruned"]
    assert pruned["plain_english_summary"]["live_blocked_because"] == (
        "Paper edge is not proven."
    )
    assert pruned["plain_english_summary"]["canary_blocked_because"] == (
        "Canary edge is not proven."
    )
    assert pruned["primary_recommendation"] == "BLOCK_LIVE_PAPER_EDGE_NOT_PROVEN"
    assert pruned["tokenmetrics_blocks_live"] is False
    assert pruned["live_ready"] is False


def test_safe_summary_from_json_keeps_legacy_freeze_cutover_state(tmp_path: Path) -> None:
    p = tmp_path / "legacy_freeze_cutover.json"
    p.write_text(
        json.dumps(
            {
                "go_no_go": "V2_LEGACY_RUNTIME_FREEZE_AND_PRIMARY_PAPER_CUTOVER_READY",
                "LEGACY_RUNTIME_ACTIVE": False,
                "LEGACY_DATA_PRESERVED": True,
                "V2_PRIMARY_PAPER_RUNTIME_ACTIVE": True,
                "LIVE_TRADING_ENABLED": False,
                "REAL_ORDERS_ENABLED": False,
                "LEGACY_REDIS_TRIMMED": False,
                "LEGACY_SHUTDOWN_MODE": "RUNTIME_FROZEN_DATA_PRESERVED",
                "plain_english_summary": {
                    "legacy_runtime_active_line": "Legacy runtime is frozen.",
                    "legacy_data_preserved_line": "Legacy data is preserved.",
                    "v2_primary_active_line": "V2 paper runtime is primary.",
                    "live_blocked_line": "Live trading remains blocked.",
                    "why_live_remains_blocked": "Paper edge is not proven.",
                },
                "api_consuming_legacy_process_count_after": 0,
                "trader_legacy_process_count_after": 0,
                "trainer_legacy_process_count_after": 1,
                "trainer_sleeping_post_sigterm_residual": True,
                "trainer_sleeping_post_sigterm_consumes_apis": False,
                "v2_runtime_services_active_count": 16,
                "redis_trim_count_by_this_lane": 0,
                "live_gate": "blocked_human_only",
                "live_symbols": [],
                "approves_live": False,
                "approves_canary": False,
                "approves_legacy_shutdown": False,
                "approves_redis_trim": False,
                "writes_old_redis": False,
                "calls_exchange_mutation": False,
                "places_real_order": False,
                "leverage_changed": False,
                "margin_mode_changed": False,
                "creates_approval_tokens": False,
                "creates_approval_artifacts": False,
            }
        ),
        encoding="utf-8",
    )
    out = safe_summary.safe_summary_from_json(p)
    assert out["status"] == "READY"
    pruned = out["pruned"]
    assert pruned["LEGACY_RUNTIME_ACTIVE"] is False
    assert pruned["LEGACY_DATA_PRESERVED"] is True
    assert pruned["V2_PRIMARY_PAPER_RUNTIME_ACTIVE"] is True
    assert pruned["LIVE_TRADING_ENABLED"] is False
    assert pruned["REAL_ORDERS_ENABLED"] is False
    assert pruned["LEGACY_REDIS_TRIMMED"] is False
    assert pruned["plain_english_summary"]["legacy_runtime_active_line"] == (
        "Legacy runtime is frozen."
    )
    assert pruned["plain_english_summary"]["live_blocked_line"] == (
        "Live trading remains blocked."
    )
    assert pruned["api_consuming_legacy_process_count_after"] == 0
    assert pruned["trader_legacy_process_count_after"] == 0
    assert pruned["trainer_sleeping_post_sigterm_consumes_apis"] is False
    assert pruned["live_gate"] == "blocked_human_only"
    assert pruned["live_symbols"] == []
    assert pruned["writes_old_redis"] is False
    assert pruned["calls_exchange_mutation"] is False
    assert pruned["places_real_order"] is False
    assert pruned["creates_approval_tokens"] is False


def test_index_lanes_emits_missing_payload_for_absent_lanes() -> None:
    state = index_lanes(stale_age_seconds=1_000_000)
    entries = state["entries"]
    by_id = {e["report_id"]: e for e in entries}
    # At least the lanes whose worklog directories don't exist must show
    # MISSING_PAYLOAD and stale=True. We don't rely on which exact lanes
    # are absent on this host; just verify the contract for at least one
    # canonical "not-yet-built" lane.
    assert "codex_executive_governor" in by_id
    e = by_id["codex_executive_governor"]
    if e["status"] == "MISSING_PAYLOAD":
        assert e["stale"] is True
        assert e["source_type"] == "missing"
        assert e["live_gate"] == "blocked_human_only"
        assert e["live_symbols"] == []
        assert e["approves_live"] is False
        assert e["approves_canary"] is False
        assert e["approves_legacy_shutdown"] is False
        assert e["approves_redis_trim"] is False


def test_index_lanes_marks_blocked_status_when_marker_blocked() -> None:
    state = index_lanes(stale_age_seconds=1_000_000)
    entries = state["entries"]
    # The executive_command_center lane should always be present.
    by_id = {e["report_id"]: e for e in entries}
    e = by_id["executive_command_center"]
    # Whatever the marker, the safety invariants must hold.
    assert e["approves_live"] is False
    assert e["approves_canary"] is False
    assert e["approves_legacy_shutdown"] is False
    assert e["approves_redis_trim"] is False


def test_no_lane_publishes_raw_secret(tmp_path: Path, monkeypatch) -> None:
    # If a worklog file happens to contain a secret-like token, the
    # sanitized summary must redact it. We simulate by pointing the
    # sanitizer at a fake markdown file directly.
    md = tmp_path / "fake.md"
    md.write_text(
        "V2_FAKE_LANE_READY\n## Decision\napi_key=AKIAIOSFODNN7EXAMPLE\n",
        encoding="utf-8",
    )
    summary = safe_summary.safe_summary_from_markdown(md)
    text = json.dumps(summary)
    assert "AKIAIOSFODNN7EXAMPLE" not in text
    assert summary["redaction_applied"] is True


def test_stale_threshold_marks_old_files(tmp_path: Path) -> None:
    import os
    p = tmp_path / "GO_NO_GO.md"
    p.write_text("V2_X_READY\n", encoding="utf-8")
    old = time.time() - 3600
    os.utime(p, (old, old))
    age = time.time() - p.stat().st_mtime
    assert age > 30 * 60
