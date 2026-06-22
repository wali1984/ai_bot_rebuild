import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test.describe('trade terminal realtime contract', () => {
  test('trade terminal hook streams read endpoints instead of owning polling loops', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useTradeTerminal.ts'), 'utf8');

    expect(source).toContain('useRealtimeResource');
    expect(source).not.toContain('setInterval(');
    expect(source).not.toContain('getV2Portfolio');
    expect(source).not.toContain('getV2Signals');
    expect(source).not.toContain('getV2MarketDepth');
  });

  test('trader account truth streams portfolio data instead of polling the portfolio API', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/usePaperAccountTruth.ts'), 'utf8');

    expect(source).toContain('useRealtimeResource<PortfolioData>');
    expect(source).toContain("url: '/api/v2/portfolio'");
    expect(source).toContain("source_type: 'websocket'");
    expect(source).not.toContain('getV2Portfolio');
    expect(source).not.toContain('setInterval(');
    expect(source).not.toContain('window.setInterval');
  });

  test('dashboard supervisor status hooks use resource websockets instead of the deleted polling helper', () => {
    const querySource = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeQuery.ts'), 'utf8');
    const resourceSource = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');
    const hookSources = [
      'src/hooks/useAgentHealth.ts',
      'src/hooks/useBuildStatus.ts',
      'src/hooks/useQueueStatus.ts',
      'src/hooks/useAuditChain.ts',
    ].map((relativePath) => readFileSync(path.resolve(process.cwd(), relativePath), 'utf8'));

    expect(querySource).toContain('useRealtimeResource<T>');
    expect(querySource).toContain("source_type: 'websocket'");
    expect(querySource).toContain("unwrapEnvelopeData: 'contract'");
    expect(resourceSource).toContain("unwrapEnvelopeData?: boolean | 'contract'");
    for (const source of hookSources) {
      expect(source).toContain('useRealtimeQuery');
      expect(source).not.toContain('usePollingQuery');
      expect(source).not.toContain('fetchJson');
      expect(source).not.toContain('setInterval(');
    }
  });

  test('resource envelope preserves trader account scope metadata for streamed account panels', () => {
    const dataContract = readFileSync(path.resolve(process.cwd(), 'src/types/dataContract.ts'), 'utf8');
    const resourceHook = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(dataContract).toContain('trader_context?: unknown');
    expect(dataContract).toContain('account_scope?: unknown');
    expect(resourceHook).toContain('trader_context: raw.trader_context');
    expect(resourceHook).toContain('account_scope: raw.account_scope');
  });
});
