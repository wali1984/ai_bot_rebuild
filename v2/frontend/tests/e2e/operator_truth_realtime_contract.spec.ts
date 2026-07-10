import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test.describe('operator truth realtime contract', () => {
  test('operator truth hooks use resource streams instead of interval fetch loops', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/operatorTruthData.ts'), 'utf8');

    expect(source).toContain('usePayloadFile');
    expect(source).toContain("const paperOnlineRuntimePayloadPath = '/api/v2/paper/runtime-status'");
    expect(source).not.toContain('setInterval(');
    expect(source).not.toContain('fetchJson');
    expect(source).not.toContain('fetch(');
  });

  test('current runtime lineage is derived from active runtime status API', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/data/currentRuntimeLineage.ts'), 'utf8');

    expect(source).toContain("export const CURRENT_RUNTIME_LINEAGE_PATH = '/api/v2/paper/runtime-status'");
    expect(source).toContain('current_signal_lineage');
    expect(source).not.toContain('/operator_runtime/paper_online/latest/current_signal_lineage.json');
  });

  test('trainer system page renders paper runtime trainer quality contract', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/admin-intelligence/index.tsx'), 'utf8');

    expect(source).toContain("const PAPER_RUNTIME_ENDPOINT = '/api/v2/paper/runtime-status'");
    expect(source).toContain('paper_trainer_model_quality_runtime_status');
    expect(source).toContain('Paper Runtime Trainer Quality');
    expect(source).toContain('Optimizer steps last hour');
    expect(source).toContain('Checkpoint reload');
    expect(source).toContain('A-grade promotion');
  });

  test('adaptive capital panel renders paper runtime churn and forward canary blockers', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/components/trading/AdaptiveCapitalTelemetryPanel.tsx'), 'utf8');

    expect(source).toContain("url: '/api/v2/paper/runtime-status'");
    expect(source).toContain('blockers?: PaperRuntimeBlocker[]');
    expect(source).toContain('FORWARD_CANARY_EVIDENCE_NOT_READY');
    expect(source).toContain('A_GRADE_SUPPLY_ZERO');
    expect(source).toContain('ONE_THOUSAND_X_TRAJECTORY_NOT_READY');
    expect(source).toContain('paper_churn_equity_bleed_governor_status');
    expect(source).toContain('paper_forward_canary_evidence_status');
    expect(source).toContain('paper_a_grade_gate_burndown_status');
    expect(source).toContain('paper_trainer_model_quality_runtime_status');
    expect(source).toContain('trainer_model_quality_runtime_status');
    expect(source).toContain('one_thousand_x_trajectory_runtime_status');
    expect(source).toContain('forward_canary_shortfalls');
    expect(source).toContain('root_cause_counts');
    expect(source).toContain('predicate_counts');
    expect(source).toContain('after_cost_expectancy_bps');
    expect(source).toContain('directional_accuracy');
    expect(source).toContain('checkpoint_reload_verified');
    expect(source).toContain('closest_gap_reason');
    expect(source).toContain('Churn Governor');
    expect(source).toContain('Canary Outcomes');
    expect(source).toContain('Canary Shortfall');
    expect(source).toContain('Trainer Quality');
    expect(source).toContain('Trainer Edge');
    expect(source).toContain('Trainer Acc/Base');
    expect(source).toContain('Trainer Reload');
    expect(source).toContain('1000x Trajectory');
    expect(source).toContain('1000x Projection');
    expect(source).toContain('A-grade Source');
    expect(source).toContain('A-grade Roots');
    expect(source).toContain('A-grade Dominant');
    expect(source).toContain('A-grade Predicates');
    expect(source).toContain('A-grade Guardian');
  });

  test('resource hook opens WebSockets for operator truth static JSON folders', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain('/operator_truth/');
    expect(source).toContain('/tonight_live_like_paper_shadow/');
  });

  test('trader snapshot waits for the shared stream before using HTTP fallback', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useTraderSnapshot.ts'), 'utf8');

    expect(source).toContain("url: '/api/v2/trader/snapshot'");
    expect(source).toContain('initialFetchWhenStreaming: false');
    expect(source).toContain('httpFallback: true');
  });

  test('resource hook preserves current payloads when a later frame is stale or incomplete', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain('mergeRealtimeResourceEnvelope(prev, nextEnvelope)');
    expect(source).toContain('Latest resource frame was stale or incomplete; preserving last current payload');
  });

  test('frontend realtime payload contracts do not expose retired providers as active data sources', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/data/realtimeUserWebsitePayloads.ts'), 'utf8');

    expect(source).toContain('RetiredAltDataProviderStatus');
    expect(source).toContain('retired_from_active_panels');
    expect(source).not.toMatch(/AltDataNansenStatus|AltDataLunarCrushStatus/);
    expect(source).not.toMatch(/nansen_payload_present|lunarcrush_payload_present/);
    expect(source).not.toMatch(/\\bnansen\\b|\\blunarcrush\\b|Alpha\\s*Vantage|AlphaVantage/i);
  });
});
