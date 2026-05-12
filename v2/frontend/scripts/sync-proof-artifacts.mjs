#!/usr/bin/env node
import { cpSync, existsSync, mkdirSync, rmSync } from 'node:fs';
import { resolve } from 'node:path';

const frontendRoot = resolve(import.meta.dirname, '..');
const repoRoot = resolve(frontendRoot, '..', '..');

const artifactSets = [
  'non_live_operational_proof',
  'historical_30d_replay_and_paper_proof',
  'operator_gui_real_data_and_explainability',
  'automation_liveness',
  'autonomous_live_readiness_builder',
  'continuous_paper_shadow_runtime',
  'trainer_lineage_and_readiness',
  'external_manual_position_quarantine',
  'enterprise_trading_cockpit',
  'readonly_market_exchange_data_plane',
  'system_atlas_runtime_coverage',
  'system_atlas_gap_remediation',
  'phase3c_runtime_monitor_verification',
  'redis_memory_pressure_remediation',
  'redis_memory_human_approval',
  'redis_export_capacity_remediation',
  'redis_liquidations_full_export',
  'redis_safe_trim_packet',
  'redis_trim_approval_hold',
  'autonomous_governor_manual_replacement',
  'autonomous_governor',
  'claude_rate_limit_codex_takeover',
  'claude_codex_rate_limit_handoff',
  'claude_primary_handoff',
  'realtime_legacy_monitoring_continuity',
  'v2_data_plane_independence',
  'codex_parallel_audit_plan',
  'codex_design_handoff_review_protocol',
  'enterprise_ui_polish',
  'performance_objective_guardrails',
  'orchestrator_risk_boundary',
  'orchestrator_decision_evidence_reconciliation',
  'root_route_redirect_to_v2_mission_control',
  'root_route_mission_control',
  'claude_design_full_visual_implementation',
  'operator_truth_recovery',
  'operator_ui_hard_fail_recovery',
  'production_operator_webapp',
  'production_dashboard_wajidali_us_repair',
  'realtime_control_plane_trainer_monitor_recovery',
  'realtime_control_plane_recovery',
  'online_readiness_control_plane',
  'v2_paper_online_recovery',
  'paper_online_canonical_truth_bridge',
  'paper_online_truth_verification',
  'control_plane_supervisor_persistence',
  'legacy_trainer_gpu_parity',
  'legacy_trainer_restart_runtime',
  'v2_live_observer_shadow_twin',
  'tonight_live_like_paper_shadow',
  'production_website_public_route_rebuild',
  'post_mvp_non_live_gap_audit',
];

for (const name of artifactSets) {
  const source = resolve(repoRoot, 'claude_worklog', 'final_readiness', name, 'latest');
  const target = resolve(frontendRoot, 'public', name, 'latest');
  if (!existsSync(source)) {
    console.log(`SKIP ${name}: source missing`);
    continue;
  }
  mkdirSync(resolve(frontendRoot, 'public', name), { recursive: true });
  rmSync(target, { recursive: true, force: true });
  if (name === 'system_atlas_runtime_coverage') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json', 'SCRIPT_REGISTRY.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'system_atlas_gap_remediation') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'phase3c_runtime_monitor_verification') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'redis_memory_pressure_remediation') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'redis_memory_human_approval') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'redis_export_capacity_remediation') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'redis_liquidations_full_export') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'redis_safe_trim_packet') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'redis_trim_approval_hold') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'autonomous_governor_manual_replacement') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'autonomous_governor') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'claude_rate_limit_codex_takeover') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else if (name === 'claude_codex_rate_limit_handoff') {
    mkdirSync(target, { recursive: true });
    for (const file of ['operator_dashboard_payload.json']) {
      cpSync(resolve(source, file), resolve(target, file));
    }
  } else {
    cpSync(source, target, { recursive: true });
  }
  console.log(`SYNCED ${name}`);
}
