import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import { gotoAs } from './_shared';

test.describe('public landing realtime data health', () => {
  test('data atlas uses resource WebSockets instead of a component polling loop', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/components/realtimeWebsite/RealtimeDataAtlasPanel.tsx'), 'utf8');

    expect(source).toContain('useRealtimeResource');
    expect(source).toContain('httpFallback: true');
    expect(source).not.toContain('setInterval(');
    expect(source).not.toContain('fetch(');
  });

  test('shows public-safe realtime data health without backend path clutter', async ({ page }) => {
    await gotoAs(page, '/landing', 'public');

    await expect(page.getByTestId('page-public-landing')).toBeVisible();
    await expect(page.getByTestId('realtime-data-atlas-public')).toBeVisible();
    await expect(page.getByTestId('realtime-data-atlas-public')).toContainText(/Realtime data health|data feeds available/i);
    await expect(page.locator('body')).not.toContainText(/operator_dashboard_payload|\/operator_runtime|\/home\/wali|payload|paper/i);
  });
});
