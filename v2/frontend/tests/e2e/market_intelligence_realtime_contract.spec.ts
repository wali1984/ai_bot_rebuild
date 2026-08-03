import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test.describe('market intelligence realtime contract', () => {
  test('research market intelligence is WebSocket-first with API fallback', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/market-intelligence/index.tsx'), 'utf8');
    const resourceHook = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain("source_type: 'websocket'");
    expect(source).toContain('httpFallback: true');
    expect(source).toContain('WebSocket market data');
    expect(source).toContain('WebSocket stream with API fallback');
    expect(source).not.toContain('Refreshes every 30s');
    expect(source).not.toContain('Market Data Not Loaded');
    expect(source).not.toContain('Retry');
    expect(source).not.toContain('Paper only');
    expect(source).not.toContain('NO DATA');
    expect(resourceHook).toContain('deliveredSourceType?: SourceType');
    expect(resourceHook).toContain("applyRawEnvelope(raw, Date.now(), 0, 'websocket')");
  });
});
