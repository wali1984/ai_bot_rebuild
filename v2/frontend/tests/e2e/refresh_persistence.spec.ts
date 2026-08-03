import { expect, test } from '@playwright/test';

const backendUrl = process.env.ENTERPRISE_BACKEND_URL ?? 'http://127.0.0.1:8000';

test.describe('enterprise refresh persistence', () => {
  test('repeated bootstrap reads keep every enterprise resource populated', async ({ request }) => {
    test.setTimeout(90_000);
    const requiredResources = [
      'dashboard',
      'markets',
      'ai_brain',
      'risk',
      'portfolio',
      'providers',
      'system_health',
      'trader_cockpit',
    ];

    for (let index = 0; index < 20; index += 1) {
      const response = await request.get(`${backendUrl}/api/v2/realtime/bootstrap`, {
        headers: { 'Cache-Control': 'no-cache' },
        timeout: 10_000,
      });
      expect(response.ok(), `bootstrap request ${index + 1}`).toBeTruthy();
      const bootstrap = await response.json();
      expect(bootstrap.schema_version).toBe('enterprise_realtime_bootstrap_v1');
      expect(bootstrap.places_real_order).toBe(false);

      for (const resource of requiredResources) {
        const snapshot = bootstrap.resources[resource];
        expect(snapshot, `${resource} snapshot exists on refresh ${index + 1}`).toBeTruthy();
        expect(snapshot.schema_version).toBe('enterprise_ui_snapshot_v1');
        expect(snapshot.payload, `${resource} payload exists on refresh ${index + 1}`).toBeTruthy();
        expect(snapshot.places_real_order).toBe(false);
        expect(snapshot.data_quality).not.toBe('invalid');
      }
    }
  });
});
