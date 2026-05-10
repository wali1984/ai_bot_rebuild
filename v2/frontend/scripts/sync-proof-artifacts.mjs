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
  } else {
    cpSync(source, target, { recursive: true });
  }
  console.log(`SYNCED ${name}`);
}
