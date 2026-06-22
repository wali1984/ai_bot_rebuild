import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test.describe('operator truth realtime contract', () => {
  test('operator truth hooks use resource streams instead of interval fetch loops', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/operatorTruthData.ts'), 'utf8');

    expect(source).toContain('usePayloadFile');
    expect(source).not.toContain('setInterval(');
    expect(source).not.toContain('fetchJson');
    expect(source).not.toContain('fetch(');
  });

  test('resource hook opens WebSockets for operator truth static JSON folders', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain('/operator_truth/');
    expect(source).toContain('/tonight_live_like_paper_shadow/');
  });

  test('resource hook preserves current payloads when a later frame is stale or incomplete', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain('shouldCacheEnvelope(prev)');
    expect(source).toContain('Latest resource frame was stale or incomplete; preserving last current payload');
  });
});
