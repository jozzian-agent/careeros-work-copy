import { defineConfig, devices } from '@playwright/test';

const HOST = process.env.PLAYWRIGHT_HOST || '127.0.0.1';
const PORT = process.env.PLAYWRIGHT_PORT || '5183';
const BASE_URL = `http://${HOST}:${PORT}`;

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  reporter: 'list',
  // Raised from the 5s default: two workers cold-hitting the Vite dev
  // server's first-request transform pass can occasionally take longer
  // than that before the page settles.
  expect: { timeout: 10000 },
  use: {
    baseURL: BASE_URL,
  },
  webServer: {
    command: `npm run dev -- --host ${HOST} --port ${PORT} --strictPort`,
    url: BASE_URL,
    reuseExistingServer: !process.env.CI,
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
