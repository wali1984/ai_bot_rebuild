import { expect, test } from '@playwright/test';

const backendUrl = process.env.ENTERPRISE_BACKEND_URL ?? 'http://127.0.0.1:8000';

test.describe('enterprise realtime contract', () => {
  test('health and bootstrap are readonly and complete', async ({ request }) => {
    const healthResponse = await request.get(`${backendUrl}/api/v2/realtime/health`);
    expect(healthResponse.ok()).toBeTruthy();
    const health = await healthResponse.json();
    expect(health.schema_version).toBe('enterprise_realtime_health_v1');
    expect(health.one_socket_per_session).toBe(true);
    expect(health.readonly_path_multiplexing).toBe(true);
    expect(health.live_gate).toBe('blocked_human_only');
    expect(health.routes_to_live).toBe(false);
    expect(health.places_real_order).toBe(false);

    const bootstrapResponse = await request.get(`${backendUrl}/api/v2/realtime/bootstrap`);
    expect(bootstrapResponse.ok()).toBeTruthy();
    const bootstrap = await bootstrapResponse.json();
    expect(bootstrap.schema_version).toBe('enterprise_realtime_bootstrap_v1');
    expect(bootstrap.display_timezone).toBe('America/New_York');
    expect(bootstrap.ui_hints.default_pnl_display).toBe('usd_and_percent');
    expect(bootstrap.live_gate).toBe('blocked_human_only');
    expect(bootstrap.routes_to_live).toBe(false);
    expect(bootstrap.places_real_order).toBe(false);

    for (const resource of [
      'dashboard',
      'markets',
      'ai_brain',
      'risk',
      'portfolio',
      'providers',
      'system_health',
      'trader_cockpit',
    ]) {
      expect(bootstrap.resources[resource].schema_version).toBe('enterprise_ui_snapshot_v1');
      expect(bootstrap.resources[resource].resource).toBe(resource);
      expect(bootstrap.resources[resource].display_timezone).toBe('America/New_York');
      expect(bootstrap.resources[resource].places_real_order).toBe(false);
    }
  });

  test('provider and AI surfaces expose the public-ready data plane', async ({ request }) => {
    const providersResponse = await request.get(`${backendUrl}/api/v2/ui/providers`);
    expect(providersResponse.ok()).toBeTruthy();
    const providers = await providersResponse.json();
    const names = providers.payload.providers.map((card: { provider: string }) => card.provider);
    expect(names).toEqual(expect.arrayContaining([
      'binance',
      'kucoin',
      'coinank',
      'coinglass',
      'moralis',
      'ta',
      'microstructure',
      'liquidations',
      'trainer_feed',
    ]));
    for (const card of providers.payload.providers) {
      expect(card).toHaveProperty('actual_payload_count');
      expect(card).toHaveProperty('heartbeat_only');
      expect(card).toHaveProperty('consumer_count');
      expect(card.places_real_order).toBe(false);
    }

    const aiResponse = await request.get(`${backendUrl}/api/v2/ui/ai-brain`);
    expect(aiResponse.ok()).toBeTruthy();
    const ai = await aiResponse.json();
    expect(ai.payload.ai_page_contract.schema_version).toBe('enterprise_ai_page_contract_v1');
    expect(ai.payload.ai_page_contract.routes_to_live).toBe(false);
    expect(ai.payload.ai_page_contract.places_real_order).toBe(false);
    expect(ai.payload.ai_page_contract.provider_feature_count_by_provider).toHaveProperty('coinglass');
    expect(ai.payload.ai_page_contract.provider_feature_count_by_provider).toHaveProperty('moralis');
    expect(ai.payload.ai_page_contract.provider_feature_count_by_provider).not.toHaveProperty('santiment');
  });
});
