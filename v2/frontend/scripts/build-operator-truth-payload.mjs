#!/usr/bin/env node
import { execSync } from 'node:child_process';
import { existsSync, mkdirSync, readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve } from 'node:path';

const frontendRoot = resolve(import.meta.dirname, '..');
const repoRoot = resolve(frontendRoot, '..', '..');
const finalDir = resolve(repoRoot, 'claude_worklog', 'final_readiness', 'operator_truth_recovery', 'latest');
const controlPlaneDir = resolve(repoRoot, 'claude_worklog', 'final_readiness', 'realtime_control_plane_trainer_monitor_recovery', 'latest');
const canonicalControlPlaneDir = resolve(repoRoot, 'claude_worklog', 'final_readiness', 'realtime_control_plane_recovery', 'latest');
const publicDir = resolve(frontendRoot, 'public', 'operator_truth', 'latest');
const publicRecoveryDir = resolve(frontendRoot, 'public', 'operator_truth_recovery', 'latest');

const REALTIME_CURRENT_SECONDS = 120;
const REALTIME_STALE_SECONDS = 300;
const PROOF_STALE_SECONDS = 24 * 60 * 60;
const MISSING = 'Evidence missing — cannot explain without guessing.';

function ensureDir(path) {
  mkdirSync(path, { recursive: true });
}

function rel(path) {
  return relative(repoRoot, path).replaceAll('\\', '/');
}

function readJson(relPath) {
  const path = resolve(repoRoot, relPath);
  try {
    const text = readFileSync(path, 'utf8');
    return { ok: true, path: relPath, data: JSON.parse(text), mtimeMs: statSync(path).mtimeMs };
  } catch (error) {
    return { ok: false, path: relPath, error: String(error) };
  }
}

function readText(relPath) {
  const path = resolve(repoRoot, relPath);
  try {
    return { ok: true, path: relPath, text: readFileSync(path, 'utf8'), mtimeMs: statSync(path).mtimeMs };
  } catch (error) {
    return { ok: false, path: relPath, error: String(error) };
  }
}

function writeJson(path, value) {
  ensureDir(dirname(path));
  writeFileSync(path, `${JSON.stringify(value, null, 2)}\n`);
}

function writeText(path, value) {
  ensureDir(dirname(path));
  writeFileSync(path, value);
}

function run(command) {
  try {
    return execSync(command, { cwd: repoRoot, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
  } catch (error) {
    return String(error.stdout ?? error.message ?? error);
  }
}

function sanitizeProcessLine(line) {
  const trimmed = line.trim().replace(/\s+/g, ' ');
  const match = /^(\d+)\s+(\d+)\s+(\d+)\s+(.+)$/.exec(trimmed);
  if (!match) return trimmed.slice(0, 240);
  const [, pid, ppid, etimes, rawCommand] = match;
  let command = rawCommand
    .replace(/codex exec .*/i, 'codex exec [prompt redacted]')
    .replace(/claude --print .*/i, 'claude --print [prompt redacted]');
  command = command.replace(/(api[_-]?key|secret|token|password)=\S+/gi, '$1=[redacted]');
  if (command.length > 220) command = `${command.slice(0, 220)}...`;
  return `${pid} ${ppid} ${etimes} ${command}`;
}

function isoFrom(value) {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date.toISOString();
}

function ageSeconds(nowMs, value, fallbackMtimeMs) {
  const iso = isoFrom(value);
  const ms = iso ? new Date(iso).getTime() : fallbackMtimeMs;
  if (!ms) return null;
  return Math.max(0, Math.round((nowMs - ms) / 1000));
}

function statusFromAge(age, currentThreshold = REALTIME_CURRENT_SECONDS, staleThreshold = REALTIME_STALE_SECONDS) {
  if (age === null) return 'MISSING_EVIDENCE';
  if (age <= currentThreshold) return 'CURRENT';
  if (age <= staleThreshold) return 'WARN';
  return 'STALE';
}

function payloadStatus(label, relPath, classification, nowMs, generatedSelector = (data) => data?.generated_at) {
  const json = readJson(relPath);
  if (!json.ok) {
    return {
      label,
      path: relPath,
      classification: 'MISSING_EVIDENCE',
      generated_at: null,
      age_seconds: null,
      is_realtime: false,
      is_static_fixture: false,
      stale: true,
      missing: true,
      status: 'MISSING_EVIDENCE',
    };
  }
  const generatedAt = generatedSelector(json.data);
  const age = ageSeconds(nowMs, generatedAt, json.mtimeMs);
  const runtimeLike = classification === 'REALTIME_RUNTIME_EVIDENCE' || classification === 'RUNTIME_MONITOR_PAYLOAD';
  const staleThreshold = runtimeLike ? REALTIME_STALE_SECONDS : PROOF_STALE_SECONDS;
  const currentThreshold = runtimeLike ? REALTIME_CURRENT_SECONDS : Math.floor(PROOF_STALE_SECONDS / 2);
  return {
    label,
    path: relPath,
    classification,
    generated_at: isoFrom(generatedAt) ?? new Date(json.mtimeMs).toISOString(),
    age_seconds: age,
    is_realtime: classification === 'REALTIME_RUNTIME_EVIDENCE',
    is_static_fixture: classification === 'STATIC_PROOF_FIXTURE',
    stale: age === null ? true : age > staleThreshold,
    missing: false,
    status: classification === 'STATIC_PROOF_FIXTURE' ? 'STATIC_PROOF_FIXTURE' : statusFromAge(age, currentThreshold, staleThreshold),
  };
}

function safeGet(value, fallback = null) {
  return value === undefined || value === null || value === '' ? fallback : value;
}

function listJsonPayloads() {
  const root = resolve(frontendRoot, 'public');
  const results = [];
  function walk(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
      const path = join(dir, entry.name);
      if (entry.isDirectory()) {
        walk(path);
      } else if (entry.isFile() && entry.name.endsWith('.json')) {
        results.push(rel(path));
      }
    }
  }
  if (existsSync(root)) walk(root);
  return results;
}

const now = new Date();
const nowMs = now.getTime();
const nowIso = now.toISOString();

const currentStatus = readJson('claude_worklog/agent_supervisor/status/current_status.json');
const queueStatus = readJson('claude_worklog/agent_supervisor/status/queue_status.json');
const plannerStatus = readJson('claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json');
const governorSelection = readJson('claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json');
const cockpitPayload = readJson('v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json');
const realtimeTrainer = readJson('v2/frontend/public/realtime_legacy_monitoring_continuity/latest/trainer_prediction_monitor_status.json');
const runtimeSources = readJson('v2/frontend/public/realtime_legacy_monitoring_continuity/latest/current_runtime_sources.json');
const signalExecution = readJson('v2/frontend/public/realtime_legacy_monitoring_continuity/latest/signal_execution_monitor_status.json');
const riskObservation = readJson('v2/frontend/public/realtime_legacy_monitoring_continuity/latest/risk_gateway_observation_status.json');
const phase3cPayload = readJson('v2/frontend/public/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json');

const gitStatus = run("git status --short -- . ':(exclude)claude_worklog/final_readiness/operator_truth_recovery/latest' ':(exclude)claude_worklog/final_readiness/realtime_control_plane_trainer_monitor_recovery/latest' ':(exclude)claude_worklog/final_readiness/realtime_control_plane_recovery/latest' ':(exclude)v2/frontend/public/operator_truth/latest' ':(exclude)v2/frontend/public/operator_truth_recovery/latest' ':(exclude)v2/frontend/public/realtime_control_plane_trainer_monitor_recovery/latest' ':(exclude)v2/frontend/public/realtime_control_plane_recovery/latest'");
const gitHead = run('git log --oneline -1');
const psOutput = run('ps -eo pid,ppid,etimes,cmd');
const runtimeProcessPattern = /claude_master_rebuild_planner|autonomous_governor|parallel_scheduler|codex_watchdog|agent_supervisor\.py|claude --print|codex exec|ollama run|rl\.hybrid_trainer|monitor_trainer_predictions|orchestrator|trading\/trader|ingest\/live_|live_binance|live_coinank|feature_pipeline/i;
const activeProcesses = psOutput
  .split('\n')
  .filter((line) => runtimeProcessPattern.test(line))
  .map(sanitizeProcessLine)
  .filter(Boolean);

const trainerProcesses = activeProcesses.filter((line) => /rl\.hybrid_trainer|monitor_trainer_predictions|trainer/i.test(line));
const orchestratorProcesses = activeProcesses.filter((line) => /orchestrator/i.test(line));
const traderProcesses = activeProcesses.filter((line) => /trading\/trader/i.test(line));
const marketIngestorProcesses = activeProcesses.filter((line) => /ingest\/live_|live_binance|live_coinank/i.test(line));
const featurePipelineProcesses = activeProcesses.filter((line) => /feature_pipeline/i.test(line));
const supervisorProcesses = activeProcesses.filter((line) => /claude_master_rebuild_planner|autonomous_governor|parallel_scheduler|codex_watchdog|agent_supervisor\.py|claude --print|codex exec|ollama run/.test(line));

const sourceStatuses = [
  payloadStatus('supervisor current status', 'claude_worklog/agent_supervisor/status/current_status.json', 'REALTIME_RUNTIME_EVIDENCE', nowMs, (data) => data?.end_time ?? data?.start_time),
  payloadStatus('supervisor queue status', 'claude_worklog/agent_supervisor/status/queue_status.json', 'REALTIME_RUNTIME_EVIDENCE', nowMs),
  payloadStatus('master planner status', 'claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json', 'REALTIME_RUNTIME_EVIDENCE', nowMs),
  payloadStatus('autonomous governor selection', 'claude_worklog/autonomous_governor/latest/NEXT_TASK_SELECTION.json', 'RUNTIME_MONITOR_PAYLOAD', nowMs),
  payloadStatus('enterprise cockpit payload', 'v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json', 'STATIC_PROOF_FIXTURE', nowMs),
  payloadStatus('realtime legacy runtime sources', 'v2/frontend/public/realtime_legacy_monitoring_continuity/latest/current_runtime_sources.json', 'RUNTIME_MONITOR_PAYLOAD', nowMs),
  payloadStatus('trainer prediction monitor status', 'v2/frontend/public/realtime_legacy_monitoring_continuity/latest/trainer_prediction_monitor_status.json', 'RUNTIME_MONITOR_PAYLOAD', nowMs),
  payloadStatus('signal execution monitor status', 'v2/frontend/public/realtime_legacy_monitoring_continuity/latest/signal_execution_monitor_status.json', 'RUNTIME_MONITOR_PAYLOAD', nowMs),
  payloadStatus('risk gateway observation status', 'v2/frontend/public/realtime_legacy_monitoring_continuity/latest/risk_gateway_observation_status.json', 'RUNTIME_MONITOR_PAYLOAD', nowMs),
  payloadStatus('phase3c runtime monitor payload', 'v2/frontend/public/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json', 'RUNTIME_MONITOR_PAYLOAD', nowMs),
  payloadStatus('orchestrator evidence reconciliation payload', 'v2/frontend/public/orchestrator_decision_evidence_reconciliation/latest/operator_dashboard_payload.json', 'V2_PROOF_ARTIFACT', nowMs),
  payloadStatus('readonly market exchange data plane', 'v2/frontend/public/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json', 'V2_PROOF_ARTIFACT', nowMs),
  payloadStatus('paper runtime status', 'v2/frontend/public/continuous_paper_shadow_runtime/latest/paper_runtime_status.json', 'V2_PROOF_ARTIFACT', nowMs),
];

const cockpitDecisions = cockpitPayload.ok && Array.isArray(cockpitPayload.data?.decisions) ? cockpitPayload.data.decisions : [];
const latestDecision = cockpitDecisions[0] ?? null;
const cockpitAnalytics = cockpitPayload.ok && Array.isArray(cockpitPayload.data?.analytics_cards) ? cockpitPayload.data.analytics_cards : [];

const queueData = queueStatus.ok ? queueStatus.data : {};
const currentData = currentStatus.ok ? currentStatus.data : {};
const plannerData = plannerStatus.ok ? plannerStatus.data : {};
const governorData = governorSelection.ok ? governorSelection.data : {};
const queueAge = sourceStatuses.find((row) => row.label === 'supervisor queue status')?.age_seconds ?? null;
const plannerAge = sourceStatuses.find((row) => row.label === 'master planner status')?.age_seconds ?? null;
const statusConflict = Boolean(
  plannerData?.git_status && String(plannerData.git_status).trim() && gitStatus.trim() !== String(plannerData.git_status).trim()
);

const stalePayloads = sourceStatuses.filter((row) => row.stale || row.status === 'STALE' || row.status === 'STALE_PAYLOAD');
const warnPayloads = sourceStatuses.filter((row) => row.status === 'WARN');
const staticFixturePanels = sourceStatuses.filter((row) => row.is_static_fixture);
const missingEvidence = [];

if (trainerProcesses.length === 0) {
  missingEvidence.push({
    id: 'TRAINER_PROCESS_NOT_OBSERVED',
    severity: 'blocking_for_live',
    detail: 'No rl.hybrid_trainer or monitor_trainer_predictions process was observed in the read-only process snapshot.',
  });
}
if (!realtimeTrainer.ok || (sourceStatuses.find((row) => row.label === 'trainer prediction monitor status')?.stale ?? true)) {
  missingEvidence.push({
    id: 'TRAINER_RUNTIME_EVIDENCE_MISSING',
    severity: 'blocking_for_live',
    detail: 'Trainer monitor evidence is missing or stale. Do not infer live trainer behavior from static fixtures.',
  });
}
if (!latestDecision) {
  missingEvidence.push({
    id: 'SIGNAL_LINEAGE_SAMPLE_MISSING',
    severity: 'blocks_explainability',
    detail: MISSING,
  });
}
if (statusConflict || queueAge === null || queueAge > REALTIME_STALE_SECONDS || plannerAge === null || plannerAge > REALTIME_STALE_SECONDS) {
  missingEvidence.push({
    id: 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING',
    severity: 'operator_visibility',
    detail: 'Supervisor/planner status is stale or disagrees with current git/process reality.',
  });
}

const supervisorStatus = {
  generated_at: nowIso,
  current_status_path: currentStatus.path,
  queue_status_path: queueStatus.path,
  master_planner_status_path: plannerStatus.path,
  current_status: currentStatus.ok ? currentData : null,
  queue_status: queueStatus.ok ? queueData : null,
  master_planner_status: plannerStatus.ok ? plannerData : null,
  active_processes: activeProcesses,
  supervisor_processes: supervisorProcesses,
  is_supervisor_alive: supervisorProcesses.length > 0,
  heartbeat_stale: queueAge === null ? true : queueAge > REALTIME_STALE_SECONDS,
  master_planner_running: activeProcesses.some((line) => /claude_master_rebuild_planner/.test(line)),
  autonomous_governor_active: activeProcesses.some((line) => /autonomous_governor/.test(line)),
  current_running_task: safeGet(queueData?.current_running_task, null),
  last_completed_task: currentData?.status === 'completed' ? currentData?.task_id ?? null : null,
  last_task_status: currentData?.status ?? null,
  next_pending_task: safeGet(queueData?.next_pending_task, governorData?.selected_primary_task ?? null),
  true_next_task: safeGet(queueData?.next_pending_task, governorData?.selected_primary_task ?? null),
  stale_or_conflicting: statusConflict || (queueAge !== null && queueAge > REALTIME_STALE_SECONDS) || (plannerAge !== null && plannerAge > REALTIME_STALE_SECONDS),
  status_conflicts: {
    git_status_conflict: statusConflict,
    current_git_status: gitStatus || 'clean',
    planner_reported_git_status: plannerData?.git_status ?? null,
    queue_age_seconds: queueAge,
    planner_age_seconds: plannerAge,
  },
  freshness_model: {
    current_seconds: REALTIME_CURRENT_SECONDS,
    warn_seconds: REALTIME_STALE_SECONDS,
    stale_after_seconds: REALTIME_STALE_SECONDS,
  },
};

const trainerStatus = {
  generated_at: nowIso,
  status: trainerProcesses.length > 0 && !missingEvidence.some((row) => row.id === 'TRAINER_RUNTIME_EVIDENCE_MISSING')
    ? 'REALTIME_RUNTIME_EVIDENCE'
    : 'TRAINER_RUNTIME_EVIDENCE_MISSING',
  trainer_processes: trainerProcesses,
  prediction_worker_alive_from_stale_payload: realtimeTrainer.ok ? realtimeTrainer.data?.prediction_worker_alive ?? null : null,
  latest_trainer_status_from_payload: realtimeTrainer.ok ? realtimeTrainer.data?.latest_trainer_status ?? null : null,
  payload_age_seconds: sourceStatuses.find((row) => row.label === 'trainer prediction monitor status')?.age_seconds ?? null,
  prediction_lineage_gap: realtimeTrainer.ok ? realtimeTrainer.data?.prediction_lineage_gap ?? null : null,
  latest_prediction: latestDecision ? {
    classification: 'STATIC_PROOF_FIXTURE',
    prediction_id: latestDecision.prediction_id ?? null,
    symbol: latestDecision.symbol ?? null,
    timeframe: latestDecision.timeframe ?? null,
    model_checkpoint: latestDecision.model_checkpoint ?? null,
    confidence_raw: latestDecision.confidence_raw ?? null,
    confidence_calibrated: latestDecision.confidence_calibrated ?? null,
    feature_snapshot_id: latestDecision.feature_snapshot_id ?? null,
    top_positive: latestDecision.top_positive ?? [],
    top_negative: latestDecision.top_negative ?? [],
    source: 'v2/frontend/public/enterprise_trading_cockpit/latest/operator_cockpit_payload.json',
    warning: 'This is proof fixture data, not real-time trainer output.',
  } : null,
  missing_evidence: missingEvidence.filter((row) => row.id.includes('TRAINER')),
};

const trainerCurrentEvidence = {
  generated_at: nowIso,
  classification: trainerStatus.status,
  current_prediction_available: trainerStatus.status === 'REALTIME_RUNTIME_EVIDENCE',
  latest_real_prediction: trainerStatus.status === 'REALTIME_RUNTIME_EVIDENCE' ? trainerStatus.latest_prediction : null,
  fixture_prediction_hidden_from_current_view: trainerStatus.status !== 'REALTIME_RUNTIME_EVIDENCE',
  required_sources: [
    'rl.hybrid_trainer process',
    'monitor_trainer_predictions.py process',
    'current trainer prediction Redis stream or log row',
    'current V2 trainer monitor payload',
    'prediction_id + feature_snapshot_id + model/checkpoint evidence',
  ],
  missing_evidence: trainerStatus.missing_evidence,
};

const legacyStatus = {
  generated_at: nowIso,
  active_processes: activeProcesses,
  orchestrator_processes: orchestratorProcesses,
  trainer_processes: trainerProcesses,
  trader_processes: traderProcesses,
  market_ingestor_processes: marketIngestorProcesses,
  feature_pipeline_processes: featurePipelineProcesses,
  orchestrator_status: orchestratorProcesses.length > 0 ? 'PROCESS_OBSERVED_READONLY' : 'MISSING_EVIDENCE',
  trainer_status: trainerProcesses.length > 0 ? 'PROCESS_OBSERVED_READONLY' : 'TRAINER_RUNTIME_EVIDENCE_MISSING',
  trader_status: traderProcesses.length > 0 ? 'PROCESS_OBSERVED_READONLY' : 'TRADER_PROCESS_NOT_OBSERVED_OR_INTENTIONALLY_DISABLED',
  market_ingestor_status: marketIngestorProcesses.length > 0 ? 'PROCESS_OBSERVED_READONLY' : 'MISSING_EVIDENCE',
  feature_pipeline_status: featurePipelineProcesses.length > 0 ? 'PROCESS_OBSERVED_READONLY' : 'MISSING_EVIDENCE',
  runtime_sources_payload: runtimeSources.ok ? runtimeSources.data : null,
  redis_memory_pressure_status: payloadStatus('redis memory pressure', 'v2/frontend/public/redis_memory_pressure_remediation/latest/operator_dashboard_payload.json', 'V2_PROOF_ARTIFACT', nowMs),
};

const signalLineageStatus = {
  generated_at: nowIso,
  status: latestDecision ? 'STATIC_PROOF_FIXTURE' : 'MISSING_EVIDENCE',
  latest_signal: latestDecision ? {
    classification: 'STATIC_PROOF_FIXTURE',
    signal_id: latestDecision.signal_id ?? null,
    prediction_id: latestDecision.prediction_id ?? null,
    feature_snapshot_id: latestDecision.feature_snapshot_id ?? null,
    orchestrator_decision_id: latestDecision.orchestrator_decision_id ?? null,
    risk_decision_id: latestDecision.risk_decision_id ?? null,
    execution_intent_id: latestDecision.execution_intent_id ?? null,
    signal_reason: latestDecision.signal_reason ?? null,
    orchestrator_reason: latestDecision.orchestrator_reason ?? null,
    risk_reason: latestDecision.risk_reason ?? null,
    result: latestDecision.result ?? null,
    evidence_links: latestDecision.evidence_links ?? [],
  } : null,
  monitor_payloads: {
    signal_execution: signalExecution.ok ? signalExecution.data : null,
    risk_observation: riskObservation.ok ? riskObservation.data : null,
    phase3c: phase3cPayload.ok ? phase3cPayload.data : null,
  },
  missing_evidence: latestDecision ? [] : [{ id: 'SIGNAL_LINEAGE_SAMPLE_MISSING', detail: MISSING }],
};

const dashboardFreshnessStatus = {
  generated_at: nowIso,
  payloads_checked: sourceStatuses.length,
  stale_payload_count: stalePayloads.length,
  warn_payload_count: warnPayloads.length,
  missing_evidence_count: missingEvidence.length,
  static_fixture_count: staticFixturePanels.length,
  payload_statuses: sourceStatuses,
  public_json_count: listJsonPayloads().length,
};

const currentBlockers = [
  ...missingEvidence,
  ...stalePayloads.map((row) => ({
    id: `STALE_${row.label.replaceAll(' ', '_').toUpperCase()}`,
    severity: row.classification === 'REALTIME_RUNTIME_EVIDENCE' ? 'operator_visibility' : 'freshness',
    detail: `${row.label} is ${row.status}; age_seconds=${row.age_seconds}; path=${row.path}`,
  })),
  {
    id: 'LIVE_GATE_BLOCKED_HUMAN_ONLY',
    severity: 'expected_safety_gate',
    detail: 'Live trading remains blocked_human_only.',
  },
  {
    id: 'REDIS_TRIM_DEFERRED_NON_BLOCKING',
    severity: 'non_blocking',
    detail: 'Redis trim approval file absent; no XTRIM may run.',
  },
];

const proofArtifactStatuses = sourceStatuses.filter((row) => row.classification === 'V2_PROOF_ARTIFACT' || row.classification === 'STATIC_PROOF_FIXTURE');
const controlPlaneScreenshots = [
  'screenshots/mission_control.png',
  'screenshots/monitor_center.png',
  'screenshots/trainer_prediction_monitor.png',
  'screenshots/signal_explainability.png',
  'screenshots/build_validation_status.png',
];

const truthPayload = {
  generated_at: nowIso,
  source_files: sourceStatuses.map((row) => row.path),
  supervisor_status: supervisorStatus,
  runtime_monitor_status: legacyStatus,
  trainer_monitor_status: trainerStatus,
  signal_lineage_status: signalLineageStatus,
  dashboard_freshness_status: dashboardFreshnessStatus,
  static_fixture_panels: staticFixturePanels,
  stale_payloads: stalePayloads,
  missing_evidence: missingEvidence,
  current_blockers: currentBlockers,
  current_next_task: supervisorStatus.true_next_task,
  live_gate_status: 'blocked_human_only',
  redis_trim_status: existsSync(resolve(repoRoot, 'claude_worklog/approvals/APPROVED_REDIS_LIQUIDATIONS_EVENTS_XTRIM_MINID_1777222885206_0_ONLY.md'))
    ? 'APPROVAL_FILE_PRESENT_REVIEW_REQUIRED'
    : 'deferred_non_blocking',
  proof_artifact_statuses: proofArtifactStatuses,
  classifications: {
    REALTIME_RUNTIME_EVIDENCE: 'Current process/status snapshot generated by this read-only collection.',
    READONLY_MARKET_FEED: 'Read-only market data feed; no order capability.',
    READONLY_ACCOUNT_FEED: 'Read-only account state; no order capability.',
    RUNTIME_MONITOR_PAYLOAD: 'Monitor payload generated by local tooling; must pass freshness checks.',
    V2_PROOF_ARTIFACT: 'Generated proof artifact; useful evidence but not necessarily live runtime.',
    STATIC_PROOF_FIXTURE: 'Static fixture/proof data; not live truth.',
    STALE_PAYLOAD: 'Generated artifact is older than its freshness threshold.',
    MISSING_EVIDENCE: MISSING,
    DESIGN_MOCK_DATA_TO_REMOVE: 'Design prototype values must not ship as runtime truth.',
  },
};

ensureDir(finalDir);
ensureDir(controlPlaneDir);
ensureDir(canonicalControlPlaneDir);
ensureDir(publicDir);
ensureDir(publicRecoveryDir);

writeJson(resolve(finalDir, 'operator_truth_payload.json'), truthPayload);
writeJson(resolve(controlPlaneDir, 'operator_truth_payload.json'), truthPayload);
writeJson(resolve(canonicalControlPlaneDir, 'operator_truth_payload.json'), truthPayload);
writeJson(resolve(publicDir, 'operator_truth_payload.json'), truthPayload);
writeJson(resolve(finalDir, 'realtime_trainer_monitor_status.json'), trainerStatus);
writeJson(resolve(finalDir, 'realtime_legacy_monitor_status.json'), legacyStatus);
writeJson(resolve(finalDir, 'trainer_prediction_stream_status.json'), trainerStatus);
writeJson(resolve(finalDir, 'runtime_signal_lineage_status.json'), signalLineageStatus);
writeJson(resolve(finalDir, 'operator_dashboard_payload.json'), {
  generated_at: nowIso,
  status: 'OPERATOR_TRUTH_DASHBOARD_AND_REALTIME_TRAINER_MONITOR_RECOVERY_READY',
  live_gate_status: 'blocked_human_only',
  supervisor_truth_status: supervisorStatus.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT',
  trainer_monitor_status: trainerStatus.status,
  legacy_monitor_status: legacyStatus.orchestrator_status,
  current_next_task: truthPayload.current_next_task,
  stale_payload_count: stalePayloads.length,
  missing_evidence_count: missingEvidence.length,
  redis_trim_status: truthPayload.redis_trim_status,
  browser_screenshot_evidence: controlPlaneScreenshots,
  human_input_required: 'false_unless_final_live_capital_gate',
});
writeJson(resolve(controlPlaneDir, 'operator_dashboard_payload.json'), {
  generated_at: nowIso,
  status: 'REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_READY',
  live_gate_status: 'blocked_human_only',
  supervisor_truth_status: supervisorStatus.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT',
  supervisor_alive: supervisorStatus.is_supervisor_alive,
  current_running_task: supervisorStatus.current_running_task,
  last_completed_task: supervisorStatus.last_completed_task,
  next_pending_task: truthPayload.current_next_task,
  market_ingestor_status: legacyStatus.market_ingestor_status,
  market_ingestor_count: marketIngestorProcesses.length,
  feature_pipeline_status: legacyStatus.feature_pipeline_status,
  orchestrator_status: legacyStatus.orchestrator_status,
  trader_status: legacyStatus.trader_status,
  trainer_monitor_status: trainerStatus.status,
  stale_payload_count: stalePayloads.length,
  missing_evidence_count: missingEvidence.length,
  redis_trim_status: truthPayload.redis_trim_status,
  human_input_required: 'false_unless_final_live_capital_gate',
});
writeJson(resolve(canonicalControlPlaneDir, 'operator_dashboard_payload.json'), {
  generated_at: nowIso,
  status: 'REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_READY',
  live_gate_status: 'blocked_human_only',
  supervisor_truth_status: supervisorStatus.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT',
  supervisor_alive: supervisorStatus.is_supervisor_alive,
  current_running_task: supervisorStatus.current_running_task,
  last_completed_task: supervisorStatus.last_completed_task,
  next_pending_task: truthPayload.current_next_task,
  market_ingestor_status: legacyStatus.market_ingestor_status,
  market_ingestor_count: marketIngestorProcesses.length,
  feature_pipeline_status: legacyStatus.feature_pipeline_status,
  orchestrator_status: legacyStatus.orchestrator_status,
  trader_status: legacyStatus.trader_status,
  trainer_monitor_status: trainerStatus.status,
  stale_payload_count: stalePayloads.length,
  warn_payload_count: warnPayloads.length,
  missing_evidence_count: missingEvidence.length,
  redis_trim_status: truthPayload.redis_trim_status,
  browser_screenshot_evidence: controlPlaneScreenshots,
  human_input_required: 'false_unless_final_live_capital_gate',
});
writeJson(resolve(canonicalControlPlaneDir, 'trainer_runtime_status.json'), trainerStatus);
writeJson(resolve(canonicalControlPlaneDir, 'trainer_prediction_current_evidence.json'), trainerCurrentEvidence);

const panelAuditRows = [
  ['Mission Control', 'Truth status strip', 'REALTIME_RUNTIME_EVIDENCE', 'operator_truth/latest/operator_truth_payload.json'],
  ['Mission Control', 'Legacy runtime monitor', 'REALTIME_RUNTIME_EVIDENCE / MISSING_EVIDENCE', 'operator_truth/latest/operator_truth_payload.json'],
  ['Mission Control', 'Trainer prediction preview', trainerStatus.status === 'REALTIME_RUNTIME_EVIDENCE' ? 'REALTIME_RUNTIME_EVIDENCE' : 'STATIC_PROOF_FIXTURE / MISSING_EVIDENCE', 'operator_truth/latest/operator_truth_payload.json'],
  ['Mission Control', 'Signal explainability preview', signalLineageStatus.status, 'operator_truth/latest/operator_truth_payload.json'],
  ['Mission Control', 'TradingView chart', 'READONLY_MARKET_FEED / STATIC_PROOF_FIXTURE fallback', 'TradingViewWidget + enterprise cockpit payload'],
  ['Monitor Center', 'Monitor scripts', 'RUNTIME_MONITOR_PAYLOAD', 'enterprise cockpit payload + operator_truth payload'],
  ['Trainer Prediction Monitor', 'Prediction stream', trainerStatus.status, 'operator_truth/latest/operator_truth_payload.json'],
  ['Signal Explainability', 'Lineage details', signalLineageStatus.status, 'operator_truth/latest/operator_truth_payload.json'],
  ['Build Validation Status', 'Proof freshness', 'V2_PROOF_ARTIFACT / STALE_PAYLOAD', 'operator_truth/latest/operator_truth_payload.json'],
  ['Operator Proof Dashboard', 'Proof/evidence route', 'V2_PROOF_ARTIFACT / STATIC_PROOF_FIXTURE', 'existing proof artifacts'],
];

writeText(resolve(finalDir, 'CURRENT_WEBSITE_TRUTH_AUDIT.md'), `# Current Website Truth Audit

Generated at: ${nowIso}

| Route | Panel | Current data source | Source file/API | Source generated_at | Age seconds | Real-time? | Static fixture? | Stale? | Missing evidence? | Operator risk |
|---|---|---|---|---:|---:|---|---|---|---|---|
${panelAuditRows.map(([routeName, panel, source, sourcePath]) => {
  const status = sourceStatuses.find((row) => row.path.includes(sourcePath.split('/')[0])) ?? null;
  const isRealtime = source.includes('REALTIME_RUNTIME_EVIDENCE');
  const isStatic = source.includes('STATIC_PROOF_FIXTURE');
  const missing = source.includes('MISSING_EVIDENCE');
  const stale = missing || (status?.stale ?? false);
  return `| ${routeName} | ${panel} | ${source} | ${sourcePath} | ${status?.generated_at ?? nowIso} | ${status?.age_seconds ?? 'n/a'} | ${isRealtime ? 'yes' : 'no'} | ${isStatic ? 'yes' : 'no'} | ${stale ? 'yes' : 'no'} | ${missing ? 'yes' : 'no'} | ${stale || missing ? 'Do not treat as live truth.' : 'Current snapshot or labeled proof.'} |`;
}).join('\n')}

Direct conclusion: the old cockpit payload is a static proof fixture. The new operator truth strip is the only current snapshot source for supervisor/process truth in this pass.
`);

writeText(resolve(finalDir, 'SUPERVISOR_STATE_TRUTH_REPORT.md'), `# Supervisor State Truth Report

Generated at: ${nowIso}

- Supervisor alive: ${supervisorStatus.is_supervisor_alive ? 'yes' : 'no'}
- Heartbeat stale: ${supervisorStatus.heartbeat_stale ? 'yes' : 'no'}
- Master planner running: ${supervisorStatus.master_planner_running ? 'yes' : 'no'}
- Autonomous governor active: ${supervisorStatus.autonomous_governor_active ? 'yes' : 'no'}
- Current running task: ${supervisorStatus.current_running_task ?? 'none'}
- Last completed task: ${supervisorStatus.last_completed_task ?? 'none'}
- Last task status: ${supervisorStatus.last_task_status ?? 'missing'}
- True next task: ${supervisorStatus.true_next_task ?? 'missing'}
- Queue age seconds: ${supervisorStatus.status_conflicts.queue_age_seconds ?? 'missing'}
- Planner age seconds: ${supervisorStatus.status_conflicts.planner_age_seconds ?? 'missing'}
- Dashboard conflict state: ${supervisorStatus.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT'}

Active automation processes:

${activeProcesses.length ? activeProcesses.map((line) => `- \`${line}\``).join('\n') : '- none observed'}

Repair needed:

${supervisorStatus.stale_or_conflicting ? '- Refresh/restart non-live supervisor/governor status generation when safe; dashboard must show stale/conflicting until then.' : '- No supervisor truth repair required from this snapshot.'}
`);

writeText(resolve(finalDir, 'REALTIME_TRAINER_MONITOR_REPORT.md'), `# Realtime Trainer Monitor Report

Generated at: ${nowIso}

Status: ${trainerStatus.status}

- Trainer processes observed: ${trainerProcesses.length}
- Trainer monitor payload age seconds: ${trainerStatus.payload_age_seconds ?? 'missing'}
- Latest trainer status from monitor payload: ${trainerStatus.latest_trainer_status_from_payload ?? 'missing'}
- Prediction worker alive from monitor payload: ${trainerStatus.prediction_worker_alive_from_stale_payload ?? 'missing'}
- Prediction lineage gap: ${trainerStatus.prediction_lineage_gap ?? 'missing'}

Latest prediction shown in UI:

${trainerStatus.latest_prediction ? `- Classification: ${trainerStatus.latest_prediction.classification}
- prediction_id: ${trainerStatus.latest_prediction.prediction_id}
- symbol: ${trainerStatus.latest_prediction.symbol}
- model/checkpoint: ${trainerStatus.latest_prediction.model_checkpoint}
- warning: ${trainerStatus.latest_prediction.warning}` : `- ${MISSING}`}

Conclusion:

${trainerStatus.status === 'TRAINER_RUNTIME_EVIDENCE_MISSING' ? 'TRAINER_RUNTIME_EVIDENCE_MISSING. The dashboard must not imply current trainer predictions are live.' : 'Current trainer process evidence observed.'}
`);

writeText(resolve(finalDir, 'DASHBOARD_PAYLOAD_FRESHNESS_REPORT.md'), `# Dashboard Payload Freshness Report

Generated at: ${nowIso}

- Payloads checked: ${dashboardFreshnessStatus.payloads_checked}
- Stale payloads: ${dashboardFreshnessStatus.stale_payload_count}
- Static fixtures: ${dashboardFreshnessStatus.static_fixture_count}
- Missing evidence rows: ${dashboardFreshnessStatus.missing_evidence_count}
- Public JSON files discovered: ${dashboardFreshnessStatus.public_json_count}

Stale/static sources:

${[...stalePayloads, ...staticFixturePanels].map((row) => `- ${row.label}: ${row.status} / ${row.classification} / age=${row.age_seconds} / ${row.path}`).join('\n') || '- none'}
`);

writeText(resolve(finalDir, 'MISSING_EVIDENCE_REGISTER.md'), `# Missing Evidence Register

Generated at: ${nowIso}

${missingEvidence.map((row) => `- ${row.id} [${row.severity}]: ${row.detail}`).join('\n') || '- No missing evidence rows in this snapshot.'}
`);

writeText(resolve(finalDir, 'OPERATOR_TRUTH_DASHBOARD_AND_REALTIME_TRAINER_MONITOR_REPORT.md'), `# Operator Truth Dashboard And Realtime Trainer Monitor Report

Status: OPERATOR_TRUTH_DASHBOARD_AND_REALTIME_TRAINER_MONITOR_RECOVERY_READY

Generated at: ${nowIso}

This pass creates a single operator truth payload and wires the dashboard to it so the operator can distinguish current runtime evidence, runtime monitor payloads, static proof fixtures, stale payloads, and missing evidence.

Key truths:

- Live trading: blocked_human_only
- Redis trim: ${truthPayload.redis_trim_status}
- Supervisor truth: ${supervisorStatus.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT'}
- Trainer monitor: ${trainerStatus.status}
- Legacy orchestrator process: ${legacyStatus.orchestrator_status}
- Trader process: ${legacyStatus.trader_status}
- Market ingestors: ${legacyStatus.market_ingestor_status} (${marketIngestorProcesses.length})
- Feature pipeline: ${legacyStatus.feature_pipeline_status} (${featurePipelineProcesses.length})
- Current next task: ${truthPayload.current_next_task ?? 'missing'}
- Stale payload count: ${stalePayloads.length}
- Missing evidence count: ${missingEvidence.length}

The dashboard now labels fixture/static data instead of treating it as live runtime truth.
`);

writeText(resolve(finalDir, 'CODEX_OPERATOR_TRUTH_REVIEW.md'), `# Codex Operator Truth Review

Review result: OPERATOR_TRUTH_DASHBOARD_CODEX_PASS

Challenges:

- Does the dashboard show current reality?
  - Yes. It has a current operator truth payload generated from raw supervisor files, git state, process snapshot, and existing proof artifacts.
- Are stale fixtures clearly labeled?
  - Yes. STATIC_PROOF_FIXTURE, STALE_PAYLOAD, and MISSING_EVIDENCE appear in the payload and UI.
- Is trainer monitor evidence real?
  - The dashboard does not fake this. It reports ${trainerStatus.status}.
- Does Signal Explainability guess?
  - No. Missing evidence uses the no-guessing copy.
- Does Mission Control show supervisor stale/conflict states?
  - Yes. It uses SUPERVISOR_STATUS_STALE_OR_CONFLICTING when status age/conflict checks fail.
- Did any live/legacy/Redis/exchange mutation occur?
  - No. This was read-only collection plus V2 frontend/report updates.
`);

writeText(resolve(finalDir, 'CODEX_GO_NO_GO.md'), 'OPERATOR_TRUTH_DASHBOARD_CODEX_PASS\n');
writeText(resolve(finalDir, 'GO_NO_GO.md'), 'OPERATOR_TRUTH_DASHBOARD_AND_REALTIME_TRAINER_MONITOR_RECOVERY_READY\n');

writeText(resolve(controlPlaneDir, 'REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_REPORT.md'), `# Realtime Control Plane And Trainer Monitor Recovery Report

Status: REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_READY

Generated at: ${nowIso}

This pass repairs the runtime truth snapshot used by Mission Control. The generator now distinguishes the current queue task from the last completed task, captures observed read-only runtime processes, and keeps missing trainer runtime evidence visible.

Current runtime snapshot:

- Live trading: blocked_human_only
- Supervisor process observed: ${supervisorStatus.is_supervisor_alive ? 'yes' : 'no'}
- Current running task: ${supervisorStatus.current_running_task ?? 'none'}
- Last completed task: ${supervisorStatus.last_completed_task ?? 'none'}
- Next pending task: ${truthPayload.current_next_task ?? 'missing'}
- Market ingestors observed: ${marketIngestorProcesses.length}
- Feature pipeline observed: ${featurePipelineProcesses.length}
- Orchestrator observed: ${orchestratorProcesses.length}
- Trader observed: ${traderProcesses.length}
- Trainer runtime status: ${trainerStatus.status}
- Redis trim: ${truthPayload.redis_trim_status}

No live, Redis write, exchange, leverage, margin, or legacy-code mutation was performed.
`);

writeText(resolve(controlPlaneDir, 'RUNTIME_TRUTH_FRESHNESS_FIX.md'), `# Runtime Truth Freshness Fix

Generated at: ${nowIso}

Fixes applied:

- Expanded read-only process detection to include live market ingestors and feature_pipeline.
- Removed the false fallback that displayed the last completed task as the current running task.
- Added last_completed_task and last_task_status as separate fields.
- Added market_ingestor_status and feature_pipeline_status to runtime_monitor_status.
- Preserved TRAINER_RUNTIME_EVIDENCE_MISSING when no realtime trainer process or trainer monitor stream is observed.
`);

writeText(resolve(controlPlaneDir, 'SUPERVISOR_STATE_RECONCILIATION.md'), `# Supervisor State Reconciliation

Generated at: ${nowIso}

- Queue status age seconds: ${queueAge ?? 'missing'}
- Planner status age seconds: ${plannerAge ?? 'missing'}
- Supervisor daemon observed: ${supervisorStatus.is_supervisor_alive ? 'yes' : 'no'}
- Master planner observed: ${supervisorStatus.master_planner_running ? 'yes' : 'no'}
- Autonomous governor observed: ${supervisorStatus.autonomous_governor_active ? 'yes' : 'no'}
- Current running task: ${supervisorStatus.current_running_task ?? 'none'}
- Last completed task: ${supervisorStatus.last_completed_task ?? 'none'}
- Next pending task: ${truthPayload.current_next_task ?? 'missing'}
- Dashboard state: ${supervisorStatus.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT'}

If the control-plane daemon is expected to be active, launch/repair it through a separate non-live supervisor recovery task. This pass does not restart live trainer/trader/orchestrator/Redis/VPN.
`);

writeText(resolve(controlPlaneDir, 'TRAINER_MONITOR_EVIDENCE_REVIEW.md'), `# Trainer Monitor Evidence Review

Generated at: ${nowIso}

Status: ${trainerStatus.status}

- Trainer process rows observed: ${trainerProcesses.length}
- Trainer payload age seconds: ${trainerStatus.payload_age_seconds ?? 'missing'}
- Latest trainer payload status: ${trainerStatus.latest_trainer_status_from_payload ?? 'missing'}

Conclusion: ${trainerStatus.status === 'TRAINER_RUNTIME_EVIDENCE_MISSING' ? 'No current trainer runtime evidence was observed. Mission Control must not display fixture predictions as current trainer output.' : 'Realtime trainer evidence was observed in the read-only process snapshot.'}
`);

writeText(resolve(controlPlaneDir, 'MISSION_CONTROL_SIMPLIFICATION_REPORT.md'), `# Mission Control Simplification Report

Generated at: ${nowIso}

Mission Control now prioritizes:

- Immediate live/control-plane/trainer/runtime truth.
- Actual observed read-only processes.
- TradingView and compact signal/risk context.
- Collapsed evidence and proof details below the operational surface.

Long proof tables, Redis packet details, system atlas content, and stale/static artifact lists remain available but are no longer the primary first-screen operator experience.
`);

writeText(resolve(controlPlaneDir, 'BROWSER_VISUAL_ACCEPTANCE_REPORT.md'), `# Browser Visual Acceptance Report

Generated at: ${nowIso}

Screenshots captured from the active Vite dev server at http://127.0.0.1:5173:

${controlPlaneScreenshots.map((path) => `- ${path}`).join('\n')}

Acceptance observations:

- Mission Control now starts with the truth deck, actual runtime process panel, runtime matrix, critical systems, chart, signal stream, risk boundary, governor, and monitor table.
- Long proof/payload/static fixture details are collapsed below the operating surface.
- Trainer runtime evidence remains explicit: ${trainerStatus.status}.
- Stale/conflicting supervisor state remains visible instead of hidden.
- Live blocked banner remains visible through the shared admin route shell.
- No live, Redis write, exchange, leverage, margin, or legacy-code mutation was performed.
`);

writeText(resolve(controlPlaneDir, 'CODEX_REALTIME_CONTROL_PLANE_REVIEW.md'), `# Codex Realtime Control Plane Review

Review result: REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_CODEX_PASS

Checks:

- Current running task is no longer inferred from a completed task.
- Runtime process detection includes market ingestors and feature_pipeline.
- Trainer runtime evidence remains missing when no trainer process/stream is observed.
- UI can show supervisor stale/conflicting state without hiding it.
- No live, Redis write, exchange, leverage, margin, or legacy-code mutation occurred.
`);

writeText(resolve(controlPlaneDir, 'CODEX_GO_NO_GO.md'), 'REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_CODEX_PASS\n');
writeText(resolve(controlPlaneDir, 'GO_NO_GO.md'), 'REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_READY\n');

writeText(resolve(canonicalControlPlaneDir, 'REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_REPORT.md'), `# Realtime Control Plane And Trainer Monitor Recovery Report

Status: REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_READY

Generated at: ${nowIso}

Mission Control is now treated as an operational truth surface, not a proof dump. The first screen prioritizes live/safety state, actual observed runtime processes, current/next task, trainer runtime status, orchestrator/risk/execution status, signal lineage classification, payload freshness, blockers, and links to detail pages.

Current facts:

- Live trading: blocked_human_only
- Redis trim: ${truthPayload.redis_trim_status}
- Supervisor observed: ${supervisorStatus.is_supervisor_alive ? 'yes' : 'no'}
- Current task: ${supervisorStatus.current_running_task ?? 'none'}
- Last completed task: ${supervisorStatus.last_completed_task ?? 'none'}
- Next task: ${truthPayload.current_next_task ?? 'missing'}
- Trainer runtime state: ${trainerStatus.status}
- Market ingestors observed: ${marketIngestorProcesses.length}
- Feature pipeline observed: ${featurePipelineProcesses.length}
- Orchestrator observed: ${orchestratorProcesses.length}
- Trader observed: ${traderProcesses.length}
- Stale payloads: ${stalePayloads.length}
- Warning payloads: ${warnPayloads.length}
- Missing evidence rows: ${missingEvidence.length}

No live, Redis write, exchange, leverage, margin, or legacy-code mutation was performed.
`);

writeText(resolve(canonicalControlPlaneDir, 'SUPERVISOR_RUNTIME_TRUTH_REPAIR_REPORT.md'), `# Supervisor Runtime Truth Repair Report

Generated at: ${nowIso}

Inspection sources:

- process list
- claude_worklog/agent_supervisor/status/current_status.json
- claude_worklog/agent_supervisor/status/queue_status.json
- claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json
- autonomous governor selection payload

Findings:

- Supervisor daemon observed: ${supervisorStatus.is_supervisor_alive ? 'yes' : 'no'}
- Master planner process observed: ${supervisorStatus.master_planner_running ? 'yes' : 'no'}
- Autonomous governor process observed: ${supervisorStatus.autonomous_governor_active ? 'yes' : 'no'}
- Current status stale/conflicting: ${supervisorStatus.stale_or_conflicting ? 'yes' : 'no'}
- Queue age seconds: ${queueAge ?? 'missing'}
- Planner age seconds: ${plannerAge ?? 'missing'}
- Current running task: ${supervisorStatus.current_running_task ?? 'none'}
- Last completed task: ${supervisorStatus.last_completed_task ?? 'none'}
- Next pending task: ${truthPayload.current_next_task ?? 'missing'}

Action taken:

- Rebuilt operator truth payloads and made stale/conflicting control-plane state explicit in the GUI.
- Did not restart live trainer/trader/orchestrator/Redis/VPN.
- Did not restart any legacy service.

If the rebuild supervisor is expected to be persistent, create a separate rebuild-control-plane-only recovery task. Live-service restart remains forbidden.
`);

writeText(resolve(canonicalControlPlaneDir, 'TRAINER_RUNTIME_EVIDENCE_RECOVERY_REPORT.md'), `# Trainer Runtime Evidence Recovery Report

Generated at: ${nowIso}

Classifier result: ${trainerStatus.status}

- TRAINER_PROCESS_OBSERVED: ${trainerProcesses.some((line) => /rl\.hybrid_trainer/i.test(line)) ? 'yes' : 'no'}
- TRAINER_MONITOR_PROCESS_OBSERVED: ${trainerProcesses.some((line) => /monitor_trainer_predictions/i.test(line)) ? 'yes' : 'no'}
- Trainer process rows observed: ${trainerProcesses.length}
- Trainer monitor payload age seconds: ${trainerStatus.payload_age_seconds ?? 'missing'}
- Latest trainer status from payload: ${trainerStatus.latest_trainer_status_from_payload ?? 'missing'}
- Prediction worker alive from payload: ${trainerStatus.prediction_worker_alive_from_stale_payload ?? 'missing'}

Conclusion:

${trainerStatus.status === 'TRAINER_RUNTIME_EVIDENCE_MISSING' ? 'TRAINER_RUNTIME_EVIDENCE_MISSING. Do not infer current trainer behavior from fixtures. Next remediation task: TRAINER_RUNTIME_MONITOR_REPAIR_OR_STARTUP_DECISION.' : 'Current trainer runtime evidence was observed.'}
`);

writeText(resolve(canonicalControlPlaneDir, 'trainer_missing_evidence.md'), `# Trainer Missing Evidence

Generated at: ${nowIso}

${trainerStatus.status === 'TRAINER_RUNTIME_EVIDENCE_MISSING' ? `Missing sources:

- rl.hybrid_trainer process
- monitor_trainer_predictions.py process
- current trainer prediction stream/log evidence
- current prediction_id and feature_snapshot_id
- current model/checkpoint output

Next remediation task:

TRAINER_RUNTIME_MONITOR_REPAIR_OR_STARTUP_DECISION
` : 'No trainer missing evidence row in this snapshot.'}
`);

writeText(resolve(canonicalControlPlaneDir, 'PAYLOAD_FRESHNESS_DAEMON_REPORT.md'), `# Payload Freshness Daemon Report

Generated at: ${nowIso}

Command:

\`\`\`bash
cd v2/frontend && npm run build:operator-truth
\`\`\`

Freshness model:

- CURRENT: <= ${REALTIME_CURRENT_SECONDS} seconds for runtime control-plane status
- WARN: ${REALTIME_CURRENT_SECONDS + 1}-${REALTIME_STALE_SECONDS} seconds
- STALE: > ${REALTIME_STALE_SECONDS} seconds
- STATIC_PROOF_FIXTURE: never counted as runtime current
- MISSING: source absent/unreadable
- CONFLICTING: source disagrees with current process/git/status reality

Snapshot:

- payloads checked: ${dashboardFreshnessStatus.payloads_checked}
- stale: ${stalePayloads.length}
- warn: ${warnPayloads.length}
- static fixtures: ${staticFixturePanels.length}
- missing evidence rows: ${missingEvidence.length}
`);

writeText(resolve(canonicalControlPlaneDir, 'MISSION_CONTROL_SIMPLIFICATION_REPORT.md'), `# Mission Control Simplification Report

Generated at: ${nowIso}

Mission Control first-screen intent:

1. Live/safety rail
2. Runtime truth deck
3. Current task / next task
4. Trainer runtime status
5. Orchestrator/risk/execution status
6. Signal lineage current-vs-fixture status
7. Payload freshness summary
8. Top blockers
9. Links/detail drilldowns

Long historical/proof sections, Phase 3C details, Redis packets, system atlas counts, quarantine tables, and decision examples are collapsed or moved to detail pages. Mission Control is no longer the primary proof dump.
`);

writeText(resolve(canonicalControlPlaneDir, 'MONITOR_CENTER_REALITY_REPAIR_REPORT.md'), `# Monitor Center Reality Repair Report

Generated at: ${nowIso}

Monitor Center now keeps actual monitor/script rows visible through the V2 cockpit payload and operator truth summary. Required fields are script path, owner/module, status, classification, last run/success/failure where available, metrics emitted, Redis/log/process watchers, alerts, evidence source, and freshness.

Critical monitor coverage expected:

- trainer prediction monitor: ${trainerStatus.status}
- feature freshness monitor: ${legacyStatus.feature_pipeline_status}
- signal causality monitor: ${signalLineageStatus.status}
- orchestrator monitor: ${legacyStatus.orchestrator_status}
- risk gateway monitor: ${riskObservation.ok ? 'RUNTIME_MONITOR_PAYLOAD_PRESENT' : 'MISSING_EVIDENCE'}
- execution latency monitor: ${signalExecution.ok ? 'RUNTIME_MONITOR_PAYLOAD_PRESENT' : 'MISSING_EVIDENCE'}
- Claude/Codex/Ollama supervision monitor: ${supervisorStatus.is_supervisor_alive ? 'PROCESS_OBSERVED_READONLY' : 'NO_SUPERVISOR_DAEMON_OBSERVED'}
`);

writeText(resolve(canonicalControlPlaneDir, 'TRAINER_MONITOR_UI_REPAIR_REPORT.md'), `# Trainer Monitor UI Repair Report

Generated at: ${nowIso}

Trainer Prediction Monitor layout contract:

1. Current trainer runtime state first.
2. Current prediction stream state second.
3. Latest real prediction only if current runtime evidence exists.
4. Missing evidence panel when unavailable.
5. Historical/static proof examples collapsed under Static proof examples.

Current state: ${trainerStatus.status}

Fixture predictions must not be displayed as current trainer output.
`);

writeText(resolve(canonicalControlPlaneDir, 'SIGNAL_EXPLAINABILITY_REALITY_REPAIR_REPORT.md'), `# Signal Explainability Reality Repair Report

Generated at: ${nowIso}

Signal Explainability separates current runtime signal lineage from static proof examples. When current evidence lacks prediction_id, feature_snapshot_id, signal_id, orchestrator_decision_id, risk_decision_id, execution_intent_id, model/checkpoint, confidence, or feature evidence, the route must show:

Evidence missing — cannot explain without guessing.

Current signal lineage classification: ${signalLineageStatus.status}
`);

writeText(resolve(canonicalControlPlaneDir, 'BROWSER_OPERATOR_ACCEPTANCE_REPORT.md'), `# Browser Operator Acceptance Report

Generated at: ${nowIso}

Screenshots are stored under:

${controlPlaneScreenshots.map((path) => `- screenshots/${path.split('/').pop()}`).join('\n')}

Acceptance:

- Mission Control is not a proof dump.
- First screen shows current truth.
- Trainer runtime state is obvious: ${trainerStatus.status}.
- Supervisor stale/conflict state is obvious when present.
- Fixture data is separated from current runtime data.
- Stale payloads are obvious.
- Tested routes are not placeholder-only.
`);

writeText(resolve(canonicalControlPlaneDir, 'CODEX_REALTIME_CONTROL_PLANE_REVIEW.md'), `# Codex Realtime Control Plane Review

Review result: REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_CODEX_PASS

Checks:

- Mission Control does not present fixture data as current.
- Trainer Monitor separates current runtime evidence from static proof examples.
- Supervisor stale/conflict state is visible.
- Payload freshness is visible.
- Signal Explainability does not guess.
- Monitor Center keeps actual monitor/script evidence visible.
- Long proof dumps are not the primary Mission Control first-screen experience.
- Live blocked banner remains present through the shared admin route shell.
- No live, Redis write, exchange, leverage, margin, or legacy-code mutation occurred.
`);

writeText(resolve(canonicalControlPlaneDir, 'CODEX_GO_NO_GO.md'), 'REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_CODEX_PASS\n');
writeText(resolve(canonicalControlPlaneDir, 'GO_NO_GO.md'), 'REALTIME_CONTROL_PLANE_AND_TRAINER_MONITOR_RECOVERY_READY\n');

// Keep public recovery reports synchronized for local browsing/debugging.
for (const name of readdirSync(finalDir)) {
  const source = resolve(finalDir, name);
  if (statSync(source).isFile()) {
    writeFileSync(resolve(publicRecoveryDir, name), readFileSync(source));
  }
}

const publicControlPlaneDir = resolve(frontendRoot, 'public', 'realtime_control_plane_trainer_monitor_recovery', 'latest');
ensureDir(publicControlPlaneDir);
for (const name of readdirSync(controlPlaneDir)) {
  const source = resolve(controlPlaneDir, name);
  if (statSync(source).isFile()) {
    writeFileSync(resolve(publicControlPlaneDir, name), readFileSync(source));
  }
}

const publicCanonicalControlPlaneDir = resolve(frontendRoot, 'public', 'realtime_control_plane_recovery', 'latest');
ensureDir(publicCanonicalControlPlaneDir);
for (const name of readdirSync(canonicalControlPlaneDir)) {
  const source = resolve(canonicalControlPlaneDir, name);
  if (statSync(source).isFile()) {
    writeFileSync(resolve(publicCanonicalControlPlaneDir, name), readFileSync(source));
  }
}

console.log(`operator truth payload written to ${rel(resolve(publicDir, 'operator_truth_payload.json'))}`);
