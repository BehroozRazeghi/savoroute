import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  retries: process.env.CI ? 1 : 0,
  use: {
    ...devices['Desktop Chrome'],
    baseURL: 'http://127.0.0.1:8000',
    trace: 'retain-on-failure',
  },
  webServer: {
    command: 'python -m uvicorn savoroute.api.app:create_app --factory --host 127.0.0.1 --port 8000',
    url: 'http://127.0.0.1:8000/healthz',
    reuseExistingServer: !process.env.CI,
    timeout: 45000,
  },
});
