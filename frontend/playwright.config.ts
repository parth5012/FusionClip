import { defineConfig, devices } from '@playwright/test';

/**
 * FusionClip E2E Test Configuration
 *
 * Targets the full-stack Docker Compose environment:
 *   - Frontend: Next.js on port 3000
 *   - Backend:  FastAPI on port 8000
 *   - MinIO:    S3-compatible storage on port 9000
 *   - Postgres: pgvector on port 5432
 *   - Redis:    pub/sub + Celery broker on port 6379
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false, // serialize — tests share backend state (uploads, tasks)
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'e2e-report' }],
  ],

  /* Shared timeout settings */
  timeout: 60_000,
  expect: { timeout: 10_000 },

  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'on-first-retry',
    actionTimeout: 15_000,
    navigationTimeout: 30_000,
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],

  /* Do NOT auto-start dev server — Docker Compose manages services */
});
