import { defineConfig, devices } from '@playwright/test';

// Tests run against a vite preview server on port 5174 (built dist).
// Port 5173 is the production FastAPI service and must not be used.
// Run `npm run build` before running tests to ensure dist is current.
// Release command: npm run test:admin-release (builds + retries=0)
export default defineConfig({
  testDir: './tests/e2e',
  timeout: 30_000,
  fullyParallel: true,
  retries: 1,
  reporter: [['list']],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5174',
    trace: 'retain-on-failure',
    serviceWorkers: 'block',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
  ],
  webServer: process.env.PLAYWRIGHT_NO_WEBSERVER
    ? undefined
    : {
        command: 'npx vite preview --port 5174 --host 127.0.0.1',
        port: 5174,
        reuseExistingServer: true,
        timeout: 60_000,
      },
});
