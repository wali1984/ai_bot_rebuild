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

  test('resource hook opens WebSockets for operator truth static JSON folders', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain('/operator_truth/');
    expect(source).toContain('/tonight_live_like_paper_shadow/');
  });

  test('resource hook preserves current payloads when a later frame is stale or incomplete', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain('mergeRealtimeResourceEnvelope(prev, nextEnvelope)');
    expect(source).toContain('Latest resource frame was stale or incomplete; preserving last current payload');
  });
});
