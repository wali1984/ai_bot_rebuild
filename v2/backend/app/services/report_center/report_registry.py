"""V2 Report Center — lane registry.

Declares the canonical set of report lanes the website must surface,
plus the safe source paths to scan for each. Lanes with no current
payload still appear in the registry — they show status
``MISSING_PAYLOAD`` and ``stale=true`` so the operator never sees a
hidden lane.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .safe_summary import (
    MARKER_TOKEN_RE,
    REDACTION_TOKEN,
    extract_go_no_go,
    sanitize_text,
    safe_summary_from_json,
    safe_summary_from_markdown,
    status_from_marker,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
WORKLOG_ROOT = REPO_ROOT / "claude_worklog" / "final_readiness"
PUBLIC_ROOT = REPO_ROOT / "v2" / "frontend" / "public"

STALE_AGE_SECONDS_DEFAULT = 30 * 60  # 30 min default freshness window


@dataclass(frozen=True)
class LaneSpec:
    """Declares one report lane."""
    lane_id: str
    title: str
    owner: str  # CLAUDE / CODEX / SYSTEM / FRONTEND
    worklog_dir: Path | None = None
    public_payload: Path | None = None
    extra_worklog_paths: tuple[Path, ...] = field(default_factory=tuple)
    extra_public_paths: tuple[Path, ...] = field(default_factory=tuple)
    blocks_live: bool = False
    blocks_shutdown: bool = False
    blocks_production_equivalence: bool = False
    blocks_recovery: bool = False
    # When True the lane is exposed on the public website. Lanes that
    # don't have a public payload (e.g. raw worklog only) stay
    # frontend-visible because the indexer publishes a sanitized
    # mirror under public/v2_report_center/latest/.
    frontend_visible: bool = True


def _w(dir_name: str) -> Path:
    return WORKLOG_ROOT / dir_name / "latest"


def _p(path: str) -> Path:
    return PUBLIC_ROOT / path.lstrip("/")


LANES: tuple[LaneSpec, ...] = (
    LaneSpec(
        "executive_command_center",
        "Executive Recovery + Production-Readiness Command Center",
        "SYSTEM",
        worklog_dir=_w("v2_executive_command_center"),
        public_payload=_p("v2_executive_command_center/latest/operator_dashboard_payload.json"),
        blocks_live=True, blocks_shutdown=True,
        blocks_production_equivalence=True, blocks_recovery=True,
    ),
    LaneSpec(
        "codex_executive_governor",
        "Codex Executive Governor",
        "CODEX",
        worklog_dir=_w("v2_executive_command_center") / "codex_governor",
        public_payload=_p("v2_executive_command_center/latest/codex_governor/codex_executive_governor_status.json"),
        blocks_live=True, blocks_shutdown=True,
        blocks_production_equivalence=True, blocks_recovery=True,
    ),
    LaneSpec(
        "v2_report_center_executive_clarity",
        "V2 Report Center Executive Clarity",
        "FRONTEND",
        worklog_dir=_w("v2_report_center_executive_clarity"),
        public_payload=_p("v2_report_center/latest/executive_status_payload.json"),
    ),
    LaneSpec(
        "current_v2_migration_audit",
        "Current V2 Migration Audit",
        "CODEX",
        worklog_dir=_w("current_v2_migration_audit"),
        public_payload=_p("current_v2_migration_audit/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_full_dynamic_rebuild_implementation",
        "V2 Full Dynamic Rebuild Implementation",
        "CLAUDE",
        worklog_dir=REPO_ROOT / "claude_worklog" / "v2_full_dynamic_rebuild" / "20260526T003358EST",
        public_payload=_p("v2_full_dynamic_rebuild_implementation/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_full_dynamic_rebuild_blocker_execution",
        "V2 Full Dynamic Rebuild Blocker Execution",
        "CLAUDE+CODEX",
        worklog_dir=REPO_ROOT
        / "claude_worklog"
        / "v2_full_dynamic_rebuild_blocker_execution"
        / "20260526T005752EST",
        public_payload=_p(
            "v2_full_dynamic_rebuild_blocker_execution/latest/operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_dynamic_symbol_remediation",
        "V2 Dynamic Symbol + Copied Component Runtime Remediation",
        "CLAUDE+CODEX",
        worklog_dir=REPO_ROOT
        / "claude_worklog"
        / "v2_dynamic_symbol_remediation"
        / "20260526T012145EST",
        public_payload=_p("v2_dynamic_symbol_remediation/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_full_copied_runtime_restart",
        "V2 Full Copied Runtime + Trading Platform Restart",
        "CLAUDE+CODEX",
        worklog_dir=REPO_ROOT
        / "claude_worklog"
        / "v2_full_copied_runtime_restart"
        / "20260526T014445EST",
        public_payload=_p("v2_full_copied_runtime_restart/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_full_copied_runtime_and_trading_platform_restart",
        "V2 Full Copied Runtime And Trading Platform Restart",
        "CLAUDE+CODEX",
        worklog_dir=REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_full_copied_runtime_and_trading_platform_restart"
        / "latest",
        public_payload=_p(
            "v2_full_copied_runtime_and_trading_platform_restart/latest/operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_copied_runtime_burn_in_and_paper_edge_improvement",
        "V2 Copied Runtime Burn-In And Paper Edge Improvement",
        "CLAUDE+CODEX+SPARK",
        worklog_dir=REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_copied_runtime_burn_in_and_paper_edge_improvement"
        / "latest",
        public_payload=_p(
            "v2_copied_runtime_burn_in_and_paper_edge_improvement/latest/operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_copied_runtime_burn_in_remediation_execution",
        "V2 Copied Runtime Burn-In Remediation Execution",
        "CLAUDE+CODEX",
        worklog_dir=REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_copied_runtime_burn_in_remediation_execution"
        / "latest",
        public_payload=_p(
            "v2_copied_runtime_burn_in_remediation_execution/latest/operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_liquidation_pipeline_and_paper_edge_recovery",
        "V2 Liquidation Pipeline and Paper-Edge Recovery",
        "CLAUDE",
        worklog_dir=REPO_ROOT
        / "claude_worklog"
        / "final_readiness"
        / "v2_liquidation_pipeline_and_paper_edge_recovery"
        / "latest",
        public_payload=_p(
            "v2_liquidation_pipeline_and_paper_edge_recovery/latest/operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "self_healing_controller",
        "Autonomous Full-Rebuild Self-Healing Controller",
        "CLAUDE",
        worklog_dir=_w("v2_autonomous_full_rebuild_self_healing"),
        public_payload=_p("v2_autonomous_full_rebuild_self_healing/latest/operator_dashboard_payload.json"),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "codex_self_healing_governor",
        "Codex Self-Healing Review + Takeover Governor",
        "CODEX",
        worklog_dir=_w("v2_autonomous_full_rebuild_self_healing") / "codex_governor",
        public_payload=_p("v2_autonomous_full_rebuild_self_healing/latest/codex_governor/codex_full_rebuild_self_healing_status.json"),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_24h_parallel_recovery_war_room",
        "24H Parallel Recovery War-Room",
        "CLAUDE",
        worklog_dir=_w("v2_24h_parallel_recovery_war_room"),
        public_payload=_p("v2_24h_parallel_recovery_war_room/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "codex_24h_parallel_recovery_war_room_governor",
        "Codex 24H Parallel Recovery War-Room Governor",
        "CODEX",
        worklog_dir=_w("v2_24h_parallel_recovery_war_room") / "codex_governor",
        public_payload=_p("v2_24h_parallel_recovery_war_room/latest/codex_governor/codex_24h_war_room_governor_status.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_high_throughput_ai_war_room_scheduler",
        "High-Throughput AI War-Room Scheduler",
        "SYSTEM",
        worklog_dir=_w("v2_high_throughput_ai_war_room_scheduler"),
        public_payload=_p("v2_high_throughput_ai_war_room_scheduler/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_legacy_startup_manifest_parity_and_bridge_exit",
        "Legacy Startup Manifest Parity + Bridge Exit",
        "CLAUDE",
        worklog_dir=_w("v2_legacy_startup_manifest_parity_and_bridge_exit"),
        public_payload=_p("v2_legacy_startup_manifest_parity_and_bridge_exit/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_legacy_production_service_parity_repair",
        "Legacy Production Service Parity Repair",
        "CODEX",
        worklog_dir=_w("v2_legacy_production_service_parity_repair"),
        public_payload=_p("v2_legacy_production_service_parity_repair/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_startup_parity_first_batch_execution",
        "Startup Parity First-Batch Execution",
        "CLAUDE",
        worklog_dir=_w("v2_startup_parity_first_batch_execution"),
        public_payload=_p("v2_startup_parity_first_batch_execution/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_post_reboot_gnome_terminal_startup",
        "Post-Reboot GNOME Terminal Startup State",
        "SYSTEM",
        public_payload=_p("v2_post_reboot_gnome_terminal_startup/latest/operator_dashboard_payload.json"),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "autonomous_production_equivalence_burndown",
        "Autonomous Production-Equivalence Burndown Controller",
        "CLAUDE",
        worklog_dir=_w("v2_autonomous_production_equivalence_burndown"),
        public_payload=_p("v2_autonomous_production_equivalence_burndown/latest/operator_dashboard_payload.json"),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "codex_autonomous_governor",
        "Codex Autonomous Production-Equivalence Review Governor",
        "CODEX",
        worklog_dir=_w("v2_autonomous_production_equivalence_burndown") / "codex_governor",
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "continuous_remediation_governor",
        "Continuous Remediation Governor",
        "CODEX",
        worklog_dir=_w("v2_runtime_soak_and_production_equivalence") / "continuous_remediation" / "codex_review",
        public_payload=_p("v2_runtime_soak_and_production_equivalence/latest/continuous_remediation_status.json"),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "runtime_soak_and_production_equivalence",
        "Runtime Soak + Production-Equivalence",
        "CLAUDE",
        worklog_dir=_w("v2_runtime_soak_and_production_equivalence"),
        public_payload=_p("v2_runtime_soak_and_production_equivalence/latest/operator_dashboard_payload.json"),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "full_observation_builder",
        "Full Observation Builder Status",
        "CLAUDE",
        worklog_dir=_w("v2_full_observation_builder"),
        public_payload=_p("operator_runtime/v2_rl_core/latest/full_observation_builder_status.json"),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "remaining_dim_execution_queue",
        "Remaining-Dim Execution Queue",
        "CLAUDE",
        worklog_dir=_w("v2_full_observation_remaining_dim_execution_queue"),
        public_payload=_p("v2_full_observation_remaining_dim_execution_queue/latest/operator_dashboard_payload.json"),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "full_observation_latest_burndown",
        "Full-Observation Latest Burndown",
        "CLAUDE",
        worklog_dir=_w("v2_full_observation_feature_family_burndown"),
        public_payload=_p("v2_full_observation_feature_family_burndown/latest/operator_dashboard_payload.json"),
    ),
    LaneSpec(
        "policy_architecture_shape_contract",
        "Policy Architecture Shape Contract",
        "CLAUDE",
        worklog_dir=_w("v2_policy_architecture_shape_contract"),
        public_payload=_p("v2_policy_architecture_shape_contract/latest/operator_dashboard_payload.json"),
        blocks_live=True, blocks_production_equivalence=True,
    ),
    LaneSpec(
        "checkpoint_promotion",
        "Checkpoint Promotion",
        "CLAUDE",
        worklog_dir=_w("v2_checkpoint_promotion"),
        public_payload=_p("v2_checkpoint_promotion/latest/operator_dashboard_payload.json"),
        blocks_live=True, blocks_production_equivalence=True,
    ),
    LaneSpec(
        "model_parity_sprint",
        "Model Parity Sprint",
        "CLAUDE",
        worklog_dir=_w("v2_model_parity_sprint"),
        public_payload=_p("v2_model_parity_sprint/latest/operator_dashboard_payload.json"),
        blocks_live=True, blocks_production_equivalence=True,
    ),
    LaneSpec(
        "liquidation_wss_daemon",
        "Liquidation WSS Daemon",
        "CLAUDE",
        public_payload=_p("operator_runtime/v2_liquidation_wss_client/latest/v2_liquidation_wss_client_status.json"),
    ),
    LaneSpec(
        "position_history_tracker",
        "Position History Tracker",
        "CLAUDE",
        public_payload=_p("operator_runtime/v2_position_history_persistent_tracker/latest/position_history_persistent_tracker_status.json"),
    ),
    LaneSpec(
        "alt_data_provider_registry",
        "Alt-Data Provider Registry",
        "CLAUDE",
        worklog_dir=_w("v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold"),
        public_payload=_p("v2_alt_data_provider_registry_rate_limit_and_dashboard_scaffold/latest/operator_dashboard_payload.json"),
    ),
    LaneSpec(
        "nansen_client",
        "Nansen Alt-Data Client (paper/shadow)",
        "CLAUDE",
        public_payload=_p("operator_runtime/v2_nansen_altdata_client/latest/v2_nansen_altdata_status.json"),
    ),
    LaneSpec(
        "lunarcrush_client",
        "LunarCrush Alt-Data Client (paper/shadow)",
        "CLAUDE",
        public_payload=_p("operator_runtime/v2_lunarcrush_altdata_client/latest/v2_lunarcrush_altdata_status.json"),
    ),
    LaneSpec(
        "alt_data_symbol_scoring",
        "Alt-Data Symbol-Universe Scoring",
        "CLAUDE",
        public_payload=_p("operator_runtime/v2_alt_data_symbol_universe_scoring/latest/alt_data_symbol_universe_scoring_status.json"),
    ),
    LaneSpec(
        "alt_data_candidate_publisher",
        "Alt-Data Candidate Publisher",
        "CLAUDE",
        worklog_dir=_w("v2_alt_data_symbol_candidate_publisher"),
        public_payload=_p("v2_alt_data_symbol_candidate_publisher/latest/operator_dashboard_payload.json"),
    ),
    LaneSpec(
        "top10_dashboards",
        "Top-10 Operator Dashboards",
        "CLAUDE",
        worklog_dir=_w("v2_top10_market_and_altdata_dashboard_rendering"),
        public_payload=_p("v2_top10_market_and_altdata_dashboard_rendering/latest/operator_dashboard_payload.json"),
    ),
    LaneSpec(
        "symbol_universe",
        "Symbol Universe (candidate-only)",
        "OPERATOR",
        public_payload=_p("operator_runtime/symbol_universe/latest/symbol_universe_status.json"),
        blocks_live=True,
    ),
    LaneSpec(
        "legacy_log_intelligence",
        "Legacy Log Intelligence Observer",
        "CLAUDE",
        public_payload=_p("operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json"),
    ),
    LaneSpec(
        "v2_vs_legacy_comparator",
        "V2-vs-Legacy Production-Equivalence Comparator",
        "CLAUDE",
        worklog_dir=_w("v2_production_replacement_runtime") / "codex_governor",
        public_payload=_p("operator_runtime/legacy_v2_production_comparator/latest/status.json"),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "live_canary_safety",
        "Live / Canary Safety",
        "OPERATOR",
        worklog_dir=_w("v2_live_canary_execution_adapter_operator_gated"),
        public_payload=_p("v2_live_canary_execution_adapter_operator_gated/latest/operator_dashboard_payload.json"),
        blocks_live=True,
    ),
    LaneSpec(
        "capital_recovery_gate",
        "Capital Recovery Gate Model",
        "OPERATOR",
        worklog_dir=_w("v2_executive_command_center"),
        extra_worklog_paths=(
            _w("v2_executive_command_center") / "capital_recovery_gate_model.json",
        ),
        blocks_live=True, blocks_recovery=True,
    ),
    LaneSpec(
        "production_readiness_scorecard",
        "Production Readiness Scorecard",
        "SYSTEM",
        worklog_dir=_w("v2_executive_command_center"),
        public_payload=_p("v2_executive_command_center/latest/production_readiness_scorecard.json"),
    ),
    LaneSpec(
        "pending_task_watchdog",
        "Pending-Task Watchdog",
        "CLAUDE",
        worklog_dir=_w("v2_autonomous_full_rebuild_self_healing"),
        public_payload=_p("v2_autonomous_full_rebuild_self_healing/latest/pending_task_watchdog_status.json"),
    ),
    LaneSpec(
        "latest_codex_failures",
        "Latest Codex Failures",
        "CODEX",
        worklog_dir=_w("v2_autonomous_full_rebuild_self_healing"),
        public_payload=_p("v2_autonomous_full_rebuild_self_healing/latest/latest_issues.json"),
    ),
    LaneSpec(
        "v2_website_data_alignment_and_control_plane",
        "V2 Website Data Alignment + Control Plane",
        "CLAUDE",
        worklog_dir=_w("v2_website_data_alignment_and_control_plane"),
        public_payload=_p(
            "v2_website_data_alignment_and_control_plane/latest/"
            "operator_dashboard_payload.json"
        ),
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_full_paper_only_startup_manifest_runtime",
        "V2 Full Paper-Only Startup Manifest Runtime",
        "CLAUDE",
        worklog_dir=_w("v2_full_paper_only_startup_manifest_runtime"),
        public_payload=_p(
            "v2_full_paper_only_startup_manifest_runtime/latest/"
            "operator_dashboard_payload.json"
        ),
        blocks_production_equivalence=True,
        blocks_shutdown=True,
    ),
    LaneSpec(
        "v2_native_dynamic_runtime_and_trainer_bridge_exit_execution",
        "V2 Native Dynamic Runtime + Trainer Bridge-Exit Execution",
        "CLAUDE",
        worklog_dir=_w("v2_native_dynamic_runtime_and_trainer_bridge_exit_execution"),
        public_payload=_p(
            "v2_native_dynamic_runtime_and_trainer_bridge_exit_execution/latest/"
            "operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_github_only_credential_purge",
        "V2 GitHub-Only Credential Purge",
        "CLAUDE",
        worklog_dir=_w("v2_github_only_credential_purge"),
        public_payload=_p(
            "v2_github_only_credential_purge/latest/operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=False,
        blocks_production_equivalence=False,
    ),
    LaneSpec(
        "v2_native_trainer_prediction_publisher",
        "V2 Native Trainer Bridge-Exit Prediction Publisher",
        "CLAUDE",
        worklog_dir=_w("v2_native_trainer_prediction_publisher"),
        public_payload=_p(
            "v2_native_trainer_prediction_publisher/latest/"
            "operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_github_visible_credential_purge_remediation",
        "V2 GitHub-Visible Credential Purge Remediation",
        "CLAUDE",
        worklog_dir=_w("v2_github_visible_credential_purge_remediation"),
        public_payload=_p(
            "v2_github_visible_credential_purge_remediation/latest/"
            "operator_dashboard_payload.json"
        ),
        blocks_live=True,
    ),
    LaneSpec(
        "v2_native_trainer_dataset_and_baseline_model",
        "V2 Native Trainer Dataset + Baseline Model (paper/shadow)",
        "CLAUDE",
        worklog_dir=_w("v2_native_trainer_dataset_and_baseline_model"),
        public_payload=_p(
            "v2_native_trainer_dataset_and_baseline_model/latest/"
            "operator_dashboard_payload.json"
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
    ),
    LaneSpec(
        "v2_native_trainer_dataset_insufficient_evidence_classification_remediation",
        "V2 Native Trainer Dataset — Insufficient-Evidence Classification Remediation",
        "CLAUDE",
        worklog_dir=_w(
            "v2_native_trainer_dataset_insufficient_evidence_classification_remediation"
        ),
        public_payload=_p(
            "v2_native_trainer_dataset_insufficient_evidence_classification_remediation/latest/"
            "operator_dashboard_payload.json"
        ),
        blocks_live=True,
    ),
    LaneSpec(
        "v2_closed_loop_execution",
        "V2 Closed-Loop Claude/Codex Execution Engine",
        "SYSTEM",
        worklog_dir=_w("v2_closed_loop_execution"),
        public_payload=_p(
            "v2_closed_loop_execution/latest/closed_loop_execution_status.json"
        ),
        extra_public_paths=(
            _p("v2_closed_loop_execution/latest/closed_loop_utilization_status.json"),
            _p("v2_closed_loop_execution/latest/task_lifecycle_status.json"),
            _p("v2_closed_loop_execution/latest/stale_completed_task_redispatch_status.json"),
            _p("v2_closed_loop_execution/latest/redispatch_suppression_status.json"),
            _p("v2_closed_loop_execution/latest/task_lifecycle_reconciliation_status.json"),
            _p("v2_closed_loop_execution/latest/GO_NO_GO.md"),
            _p("v2_closed_loop_execution/latest/operator_dashboard_payload.json"),
        ),
    ),
    LaneSpec(
        "v2_closed_loop_execution_real_mode_enablement",
        "V2 Closed-Loop Execution Engine — Real-Mode Enablement",
        "SYSTEM",
        worklog_dir=_w("v2_closed_loop_execution_real_mode_enablement"),
        public_payload=_p(
            "v2_closed_loop_execution_real_mode_enablement/latest/"
            "real_mode_enablement_status.json"
        ),
        extra_public_paths=(
            _p(
                "v2_closed_loop_execution_real_mode_enablement/latest/"
                "current_automatable_work_queue.json"
            ),
            _p(
                "v2_closed_loop_execution_real_mode_enablement/latest/"
                "historical_task_noise_summary.json"
            ),
            _p(
                "v2_closed_loop_execution_real_mode_enablement/latest/"
                "operator_dashboard_payload.json"
            ),
        ),
    ),
    LaneSpec(
        "v2_closed_loop_active_lane_minimum_remediation",
        "V2 Closed-Loop Active-Lane Minimum Remediation",
        "SYSTEM",
        worklog_dir=_w("v2_closed_loop_active_lane_minimum_remediation"),
        public_payload=_p(
            "v2_closed_loop_active_lane_minimum_remediation/latest/"
            "active_lane_minimum_remediation_status.json"
        ),
        extra_public_paths=(
            _p(
                "v2_closed_loop_active_lane_minimum_remediation/latest/"
                "active_lane_shortfall_root_cause.json"
            ),
            _p(
                "v2_closed_loop_active_lane_minimum_remediation/latest/"
                "operator_dashboard_payload.json"
            ),
        ),
    ),
    LaneSpec(
        "v2_worker_pool_queue_consumption_remediation",
        "V2 Worker Pool Queue-Consumption Remediation",
        "SYSTEM",
        worklog_dir=_w("v2_worker_pool_queue_consumption_remediation"),
        public_payload=_p(
            "v2_worker_pool_queue_consumption_remediation/latest/"
            "queue_consumption_remediation_status.json"
        ),
        extra_public_paths=(
            _p(
                "v2_worker_pool_queue_consumption_remediation/latest/"
                "queue_consumption_diagnosis.json"
            ),
            _p(
                "v2_worker_pool_queue_consumption_remediation/latest/"
                "worker_execution_proof.json"
            ),
            _p(
                "v2_worker_pool_queue_consumption_remediation/latest/"
                "operator_dashboard_payload.json"
            ),
        ),
    ),
    LaneSpec(
        "v2_closed_loop_persistent_worker_pool",
        "V2 Closed-Loop Persistent Worker Pool",
        "SYSTEM",
        worklog_dir=_w("v2_closed_loop_persistent_worker_pool"),
        public_payload=_p(
            "v2_closed_loop_persistent_worker_pool/latest/"
            "persistent_worker_pool_enablement_status.json"
        ),
        extra_public_paths=(
            _p(
                "v2_closed_loop_persistent_worker_pool/latest/"
                "worker_pool_status.json"
            ),
            _p(
                "v2_closed_loop_persistent_worker_pool/latest/"
                "persistent_worker_pool_utilization.json"
            ),
            _p(
                "v2_closed_loop_persistent_worker_pool/latest/"
                "operator_dashboard_payload.json"
            ),
        ),
    ),
    LaneSpec(
        "v2_codex_spark_parallel_closed_loop",
        "V2 Codex Spark Parallel Closed-Loop Runtime",
        "SYSTEM",
        worklog_dir=_w("v2_codex_spark_parallel_closed_loop"),
        public_payload=_p(
            "v2_codex_spark_parallel_closed_loop/latest/executive_payload_spark_status.json"
        ),
        extra_public_paths=(
            _p(
                "v2_codex_spark_parallel_closed_loop/latest/"
                "operator_payload_spark_status.json"
            ),
            _p(
                "v2_codex_spark_parallel_closed_loop/latest/"
                "public/operator_dashboard_payload.json"
            ),
            _p("v2_codex_spark_parallel_closed_loop/latest/GO_NO_GO.md"),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_final_production_equivalence_blocker_resolution_sprint",
        "V2 Final Production Equivalence Blocker Resolution Sprint",
        "SYSTEM",
        worklog_dir=_w("v2_final_production_equivalence_blocker_resolution_sprint"),
        public_payload=_p(
            "v2_final_production_equivalence_blocker_resolution_sprint/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_final_production_equivalence_blocker_resolution_sprint/latest/"
                "exact_remaining_blocker_list.json"
            ),
            _p(
                "v2_final_production_equivalence_blocker_resolution_sprint/latest/"
                "final_operator_decision_packet.json"
            ),
            _p(
                "v2_final_production_equivalence_blocker_resolution_sprint/latest/"
                "event_dependent_watchers_status.json"
            ),
            _p(
                "v2_final_production_equivalence_blocker_resolution_sprint/latest/"
                "final_production_equivalence_recommendation.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_final_operator_decision_and_event_watcher_execution",
        "V2 Final Operator Decision and Event Watcher Execution",
        "SYSTEM",
        worklog_dir=_w("v2_final_operator_decision_and_event_watcher_execution"),
        public_payload=_p(
            "v2_final_operator_decision_and_event_watcher_execution/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_final_operator_decision_and_event_watcher_execution/latest/"
                "final_operator_decision_center.json"
            ),
            _p(
                "v2_final_operator_decision_and_event_watcher_execution/latest/"
                "external_source_decision_execution_status.json"
            ),
            _p(
                "v2_final_operator_decision_and_event_watcher_execution/latest/"
                "event_dependent_watcher_runtime_status.json"
            ),
            _p(
                "v2_final_operator_decision_and_event_watcher_execution/latest/"
                "final_shutdown_recommendation.json"
            ),
            _p(
                "v2_final_operator_decision_and_event_watcher_execution/latest/"
                "automation_cycle_status.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_autonomous_mission_backlog",
        "V2 Autonomous Mission Backlog Autoseed + Dispatch",
        "SYSTEM",
        worklog_dir=_w("v2_autonomous_mission_backlog"),
        public_payload=_p(
            "v2_autonomous_mission_backlog/latest/"
            "autonomous_mission_backlog_status.json"
        ),
        extra_public_paths=(
            _p(
                "v2_autonomous_mission_backlog/latest/"
                "mission_blocker_inventory.json"
            ),
            _p(
                "v2_autonomous_mission_backlog/latest/"
                "generated_task_batch.json"
            ),
            _p(
                "v2_autonomous_mission_backlog/latest/"
                "operator_dashboard_payload.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_autonomous_mission_execution_burndown",
        "V2 Autonomous Mission Execution Burndown",
        "SYSTEM",
        worklog_dir=_w("v2_autonomous_mission_execution_burndown"),
        public_payload=_p(
            "v2_autonomous_mission_execution_burndown/latest/"
            "mission_execution_burndown_status.json"
        ),
        extra_public_paths=(
            _p(
                "v2_autonomous_mission_execution_burndown/latest/"
                "blocker_burndown_matrix.json"
            ),
            _p(
                "v2_autonomous_mission_execution_burndown/latest/"
                "task_completion_last_hour.json"
            ),
            _p(
                "v2_autonomous_mission_execution_burndown/latest/"
                "remediation_flow_status.json"
            ),
            _p(
                "v2_autonomous_mission_execution_burndown/latest/"
                "operator_dashboard_payload.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_autonomous_no_manual_next_task_policy",
        "V2 Autonomous No-Manual Next-Task Policy",
        "SYSTEM",
        worklog_dir=_w("v2_autonomous_no_manual_next_task_policy"),
        public_payload=_p(
            "v2_autonomous_no_manual_next_task_policy/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_autonomous_no_manual_next_task_policy/latest/"
                "autonomous_no_manual_next_task_policy_status.json"
            ),
            _p(
                "v2_autonomous_no_manual_next_task_policy/latest/"
                "report_center_next_action_classification.json"
            ),
            _p(
                "v2_autonomous_no_manual_next_task_policy/latest/"
                "automatic_task_seed_status.json"
            ),
            _p(
                "v2_autonomous_no_manual_next_task_policy/latest/"
                "worker_execution_policy_status.json"
            ),
            _p(
                "v2_autonomous_no_manual_next_task_policy/latest/"
                "operator_only_action_status.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_no_status_change_sla_watchdog",
        "V2 No Status Change SLA Watchdog",
        "SYSTEM",
        worklog_dir=_w("v2_no_status_change_sla_watchdog"),
        public_payload=_p(
            "v2_no_status_change_sla_watchdog/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_no_status_change_sla_watchdog/latest/"
                "no_status_change_sla_status.json"
            ),
            _p(
                "v2_no_status_change_sla_watchdog/latest/"
                "no_change_root_cause.json"
            ),
            _p(
                "v2_no_status_change_sla_watchdog/latest/"
                "no_change_action_plan.json"
            ),
            _p(
                "v2_no_status_change_sla_watchdog/latest/"
                "stale_pipeline_remediation_status.json"
            ),
            _p(
                "v2_no_status_change_sla_watchdog/latest/"
                "executive_no_change_explanation.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_external_source_wait_credential_reconciliation",
        "V2 External Source Wait Credential Reconciliation",
        "SYSTEM",
        worklog_dir=_w("v2_external_source_wait_credential_reconciliation"),
        public_payload=_p(
            "v2_external_source_wait_credential_reconciliation/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_external_source_wait_credential_reconciliation/latest/"
                "external_source_alias_reconciliation_status.json"
            ),
            _p(
                "v2_external_source_wait_credential_reconciliation/latest/"
                "credential_name_presence_by_source.json"
            ),
            _p(
                "v2_external_source_wait_credential_reconciliation/latest/"
                "provider_client_gap_status.json"
            ),
            _p(
                "v2_external_source_wait_credential_reconciliation/latest/"
                "safe_external_source_task_seed_status.json"
            ),
            _p(
                "v2_external_source_wait_credential_reconciliation/latest/"
                "full_observation_external_source_impact_matrix.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_live_readiness_blocker_burndown_excluding_tokenmetrics",
        "V2 Live-Readiness Blocker Burndown (TokenMetrics Excluded)",
        "SYSTEM",
        worklog_dir=_w("v2_live_readiness_blocker_burndown_excluding_tokenmetrics"),
        public_payload=_p(
            "v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/"
                "tokenmetrics_deferral_status.json"
            ),
            _p(
                "v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/"
                "live_readiness_blocker_matrix.json"
            ),
            _p(
                "v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/"
                "paper_edge_live_readiness_status.json"
            ),
            _p(
                "v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/"
                "risk_cap_operator_threshold_proposal.json"
            ),
            _p(
                "v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/"
                "canary_dry_run_safety_status.json"
            ),
            _p(
                "v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/"
                "exchange_permission_no_order_probe_plan.json"
            ),
            _p(
                "v2_live_readiness_blocker_burndown_excluding_tokenmetrics/latest/"
                "live_readiness_recommendation.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=False,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync",
        "V2 Dynamic 93-Symbol Burn-In, Edge, and Website Sync",
        "CODEX",
        worklog_dir=_w("v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync"),
        public_payload=_p(
            "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/"
                "v2_dynamic_93_symbol_runtime_burn_in_status.json"
            ),
            _p(
                "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/"
                "v2_dynamic_93_trainer_quality_status.json"
            ),
            _p(
                "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/"
                "v2_dynamic_93_edge_recompute_status.json"
            ),
            _p(
                "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/"
                "v2_dynamic_provider_contribution_status.json"
            ),
            _p(
                "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/"
                "v2_dynamic_website_sync_status.json"
            ),
            _p(
                "v2_dynamic_93_symbol_runtime_burn_in_edge_and_website_sync/latest/"
                "v2_dynamic_live_readiness_recompute_status.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=False,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_dynamic_93_edge_recovery_and_signal_quality_burndown",
        "V2 Dynamic 93 Edge Recovery And Signal Quality Burndown",
        "CODEX",
        worklog_dir=_w("v2_dynamic_93_edge_recovery_and_signal_quality_burndown"),
        public_payload=_p(
            "v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/"
                "v2_dynamic_93_by_symbol_edge_attribution.json"
            ),
            _p(
                "v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/"
                "v2_public_intel_signal_contribution_status.json"
            ),
            _p(
                "v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/"
                "v2_trainer_confidence_calibration_status.json"
            ),
            _p(
                "v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/"
                "v2_risk_paper_decision_quality_status.json"
            ),
            _p(
                "v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/"
                "v2_strategy_fallback_edge_comparison_status.json"
            ),
            _p(
                "v2_dynamic_93_edge_recovery_and_signal_quality_burndown/latest/"
                "v2_dynamic_93_edge_recompute_after_quality_fixes.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=False,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_fastest_safe_canary_readiness_execution",
        "V2 Fastest-Safe Canary-Readiness Execution",
        "SYSTEM",
        worklog_dir=_w("v2_fastest_safe_canary_readiness_execution"),
        public_payload=_p(
            "v2_fastest_safe_canary_readiness_execution/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_fastest_safe_canary_readiness_execution/latest/"
                "v2_fast_canary_threshold_selection_packet.json"
            ),
            _p(
                "v2_fastest_safe_canary_readiness_execution/latest/"
                "v2_fast_canary_risk_cap_selection_packet.json"
            ),
            _p(
                "v2_fastest_safe_canary_readiness_execution/latest/"
                "v2_fast_canary_paper_edge_evaluation.json"
            ),
            _p(
                "v2_fastest_safe_canary_readiness_execution/latest/"
                "v2_read_only_permission_probe_approval_packet.json"
            ),
            _p(
                "v2_fastest_safe_canary_readiness_execution/latest/"
                "v2_canary_dry_run_safety_refresh.json"
            ),
            _p(
                "v2_fastest_safe_canary_readiness_execution/latest/"
                "v2_fast_canary_recommendation.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=False,
        blocks_production_equivalence=True,
        blocks_recovery=True,
    ),
    LaneSpec(
        "v2_legacy_runtime_freeze_and_primary_paper_cutover",
        "V2 Legacy Runtime Freeze + Primary Paper Cutover",
        "SYSTEM",
        worklog_dir=_w("v2_legacy_runtime_freeze_and_primary_paper_cutover"),
        public_payload=_p(
            "v2_legacy_runtime_freeze_and_primary_paper_cutover/latest/"
            "operator_dashboard_payload.json"
        ),
        extra_public_paths=(
            _p(
                "v2_legacy_runtime_freeze_and_primary_paper_cutover/latest/"
                "legacy_runtime_freeze_precheck.json"
            ),
            _p(
                "v2_legacy_runtime_freeze_and_primary_paper_cutover/latest/"
                "legacy_reference_preservation_status.json"
            ),
            _p(
                "v2_legacy_runtime_freeze_and_primary_paper_cutover/latest/"
                "legacy_runtime_freeze_stop_status.json"
            ),
            _p(
                "v2_legacy_runtime_freeze_and_primary_paper_cutover/latest/"
                "legacy_autorestart_disable_status.json"
            ),
            _p(
                "v2_legacy_runtime_freeze_and_primary_paper_cutover/latest/"
                "v2_primary_paper_runtime_cutover_status.json"
            ),
            _p(
                "v2_legacy_runtime_freeze_and_primary_paper_cutover/latest/"
                "post_cutover_redis_write_boundary_status.json"
            ),
            _p(
                "v2_legacy_runtime_freeze_and_primary_paper_cutover/latest/"
                "api_rate_limit_relief_status.json"
            ),
        ),
        blocks_live=True,
        blocks_shutdown=True,
        blocks_production_equivalence=True,
        blocks_recovery=False,
    ),
)

assert len({l.lane_id for l in LANES}) == len(LANES), "duplicate lane_id"


def _payload_age_seconds(path: Path | None) -> float | None:
    if path is None or not path.exists():
        return None
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:  # noqa: BLE001
        return None


def _pick_best_artifact(spec: LaneSpec) -> tuple[Path | None, str]:
    """Pick the most-relevant artifact for a lane to summarize.

    Order:
      1. Lane's `public_payload` (sanitized json/markdown).
      2. Worklog `GO_NO_GO.md` under `worklog_dir`.
      3. First markdown file under `worklog_dir`.
      4. First json file under `worklog_dir`.
      5. Any `extra_worklog_paths` / `extra_public_paths`.
    """
    if spec.public_payload and spec.public_payload.exists():
        return spec.public_payload, "public_payload"
    if spec.worklog_dir and spec.worklog_dir.exists():
        gng = spec.worklog_dir / "GO_NO_GO.md"
        if gng.exists():
            return gng, "markdown_summary"
        # Prefer any *REPORT.md
        for f in sorted(spec.worklog_dir.glob("*REPORT*.md")):
            return f, "markdown_summary"
        for f in sorted(spec.worklog_dir.glob("*.md")):
            return f, "markdown_summary"
        for f in sorted(spec.worklog_dir.glob("*.json")):
            return f, "worklog_json"
    for p in spec.extra_worklog_paths:
        if p.exists():
            return p, "worklog_json" if p.suffix == ".json" else "markdown_summary"
    for p in spec.extra_public_paths:
        if p.exists():
            return p, "public_payload"
    return None, "missing"


def _summarize(path: Path) -> dict[str, Any]:
    if path.suffix == ".md":
        return safe_summary_from_markdown(path)
    if path.suffix == ".json":
        return safe_summary_from_json(path)
    # Unknown extension — treat as markdown for sanitization purposes.
    return safe_summary_from_markdown(path)


def _public_relative(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        rel = path.relative_to(PUBLIC_ROOT)
        # Frontend assets serve from `/public`, so prefix with `/`.
        return "/" + str(rel).replace("\\", "/")
    except ValueError:
        return None


def _worklog_relative(path: Path | None) -> str | None:
    if path is None:
        return None
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return None


def index_lanes(
    *,
    stale_age_seconds: int = STALE_AGE_SECONDS_DEFAULT,
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for spec in LANES:
        artifact, source_type = _pick_best_artifact(spec)
        age = _payload_age_seconds(artifact)
        stale = (age is None) or (age > stale_age_seconds)
        status = "MISSING_PAYLOAD"
        go_no_go: str | None = None
        codex_passed: bool | None = None
        current_blockers: list[str] = []
        next_action: str | None = None
        live_gate = None
        live_symbols = None
        approves_live = False
        approves_canary = False
        approves_legacy_shutdown = False
        approves_redis_trim = False
        sanitized_summary: dict[str, Any] | None = None

        if artifact is not None:
            sanitized_summary = _summarize(artifact)
            go_no_go = sanitized_summary.get("go_no_go") if isinstance(sanitized_summary, dict) else None
            status = sanitized_summary.get("status", status)
            # codex pass detection
            if isinstance(go_no_go, str):
                upper = go_no_go.upper()
                if upper.endswith("_CODEX_PASS"):
                    codex_passed = True
                elif upper.endswith("_CODEX_FAIL"):
                    codex_passed = False
                else:
                    codex_passed = None
            # Pull safety fields out of pruned json if present.
            pruned = sanitized_summary.get("pruned") if isinstance(sanitized_summary, dict) else None
            if isinstance(pruned, dict):
                live_gate = pruned.get("live_gate")
                live_symbols = pruned.get("live_symbols")
                approves_live = bool(pruned.get("approves_live"))
                approves_canary = bool(pruned.get("approves_canary"))
                approves_legacy_shutdown = bool(pruned.get("approves_legacy_shutdown"))
                approves_redis_trim = bool(pruned.get("approves_redis_trim"))
                next_action = pruned.get("next_action")
                blockers = pruned.get("blockers")
                if isinstance(blockers, list):
                    for b in blockers[:8]:
                        if isinstance(b, dict):
                            label = (
                                b.get("blocker_id")
                                or b.get("category")
                                or b.get("id")
                                or "blocker"
                            )
                            detail = (
                                b.get("current_state")
                                or b.get("next_action")
                                or b.get("detail")
                                or ""
                            )
                            current_blockers.append(
                                f"{label}: {detail}"
                            )
                        else:
                            current_blockers.append(str(b)[:280])
            sections = (
                sanitized_summary.get("sections")
                if isinstance(sanitized_summary, dict)
                else None
            )
            if isinstance(sections, dict):
                for key in ("next action", "next actions"):
                    if next_action is None and sections.get(key):
                        next_action = sections[key][:600]
                blockers_text = sections.get("current blockers") or sections.get("blockers")
                if isinstance(blockers_text, str) and not current_blockers:
                    current_blockers = [
                        line.strip("- *").strip()
                        for line in blockers_text.splitlines()
                        if line.strip()
                    ][:8]

        if status == "MISSING_PAYLOAD":
            next_action = (
                next_action
                or "publisher emits no payload yet; lane shown explicitly with stale=true so it cannot hide"
            )

        # Sanitize next_action / blockers text just in case.
        if next_action is not None:
            next_action = sanitize_text(next_action)
        current_blockers = [sanitize_text(b) for b in current_blockers]

        entry = {
            "report_id": spec.lane_id,
            "title": spec.title,
            "lane": spec.lane_id,
            "owner": spec.owner,
            "source_type": source_type,
            "go_no_go": go_no_go,
            "status": status,
            "generated_at": (
                time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ", time.gmtime(artifact.stat().st_mtime)
                )
                if artifact is not None
                else None
            ),
            "freshness_seconds": age,
            "stale": stale,
            "codex_passed": codex_passed,
            "blocks_live": spec.blocks_live,
            "blocks_shutdown": spec.blocks_shutdown,
            "blocks_production_equivalence": spec.blocks_production_equivalence,
            "blocks_recovery": spec.blocks_recovery,
            "current_blockers": current_blockers,
            "next_action": next_action,
            "public_payload_path": _public_relative(spec.public_payload)
                if spec.public_payload and spec.public_payload.exists()
                else _public_relative(artifact),
            "safe_report_path": (
                "/v2_report_center/latest/safe_summaries/" + spec.lane_id + ".json"
            ),
            "frontend_visible": spec.frontend_visible,
            "live_gate": live_gate if live_gate is not None else "blocked_human_only",
            "live_symbols": live_symbols if live_symbols is not None else [],
            "approves_live": approves_live,
            "approves_canary": approves_canary,
            "approves_legacy_shutdown": approves_legacy_shutdown,
            "approves_redis_trim": approves_redis_trim,
            "redaction_applied": bool(
                isinstance(sanitized_summary, dict)
                and sanitized_summary.get("redaction_applied")
            ),
            "sanitized_summary": sanitized_summary,
        }
        entries.append(entry)
    return {"entries": entries}
