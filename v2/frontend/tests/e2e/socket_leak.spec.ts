import { expect, test } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const artifactCandidates = [
  path.resolve(
    process.cwd(),
    'goal_state/V2_ENTERPRISE_WEB_IOS_REALTIME_DATA_PLANE_PUBLIC_READY_COMPLETION/phase11_dedicated_stream_soak_observation.json',
  ),
  path.resolve(
    process.cwd(),
    '../../goal_state/V2_ENTERPRISE_WEB_IOS_REALTIME_DATA_PLANE_PUBLIC_READY_COMPLETION/phase11_dedicated_stream_soak_observation.json',
  ),
];

test.describe('enterprise realtime socket leak budget', () => {
  test('30 minute dedicated stream soak stayed within the socket budget', async () => {
    const artifactPath = artifactCandidates.find((candidate) => fs.existsSync(candidate));
    expect(artifactPath).toBeTruthy();
    if (!artifactPath) throw new Error('phase11_dedicated_stream_soak_observation.json not found');
    const artifact = JSON.parse(fs.readFileSync(artifactPath, 'utf8'));

    expect(artifact.duration_requirement_met).toBe(true);
    expect(artifact.duration_ms_observed).toBeGreaterThanOrEqual(1_800_000);
    expect(artifact.websocket_summary.max_concurrent).toBeLessThanOrEqual(
      artifact.websocket_summary.max_active_socket_budget,
    );
    expect(artifact.websocket_summary.legacy_resource_socket_count).toBe(0);
    expect(artifact.browser_health.unexpected_console_error_count).toBe(0);
    expect(artifact.browser_health.page_error_count).toBe(0);
    expect(artifact.browser_health.unexpected_failed_same_origin_request_count).toBe(0);
  });
});
