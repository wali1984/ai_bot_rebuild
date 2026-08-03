import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

const STREAMED_PAYLOAD_PAGES = [
  'src/pages/coverage-system-atlas/index.tsx',
  'src/pages/script-registry/index.tsx',
  'src/pages/replay/index.tsx',
  'src/pages/operator-proof-dashboard/index.tsx',
] as const;

test.describe('static admin payload realtime contract', () => {
  test('admin payload pages use resource streams instead of one-shot fetch effects', () => {
    for (const file of STREAMED_PAYLOAD_PAGES) {
      const source = readFileSync(path.resolve(process.cwd(), file), 'utf8');

      expect(source, file).toContain('usePayloadFile');
      expect(source, file).not.toContain('fetch(');
      expect(source, file).not.toContain('setInterval(');
    }
  });

  test('resource hook opens WebSockets for static admin payload folders', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/hooks/useRealtimeResource.ts'), 'utf8');

    expect(source).toContain('/system_atlas_runtime_coverage/');
    expect(source).toContain('/system_atlas_gap_remediation/');
    expect(source).toContain('/historical_30d_replay_and_paper_proof/');
    expect(source).toContain('/operator_gui_real_data_and_explainability/');
    expect(source).toContain('/external_manual_position_quarantine/');
  });
});
