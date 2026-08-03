import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test.describe('cockpit realtime data contract', () => {
  test('shared cockpit hook streams payload files instead of one-shot fetching them', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/cockpitData.ts'), 'utf8');

    expect(source).toContain('usePayloadFile');
    expect(source).not.toContain('fetchJson');
    expect(source).not.toContain('fetch(');
    expect(source).not.toContain('useEffect(');
  });

  test('resource hook opens WebSockets for cockpit static JSON folders', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain('/enterprise_trading_cockpit/');
    expect(source).toContain('/readonly_market_exchange_data_plane/');
    expect(source).toContain('/system_atlas_runtime_coverage/');
    expect(source).toContain('/autonomous_governor/');
  });
});
