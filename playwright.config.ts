// End-to-end test of the lot flow against the dev server (npm run e2e). Uses the real lot records on the
// external drive (LOT_DATA_DIR, default ~/musa-drive/lots) and skips when they are not there.
import { defineConfig, devices } from '@playwright/test';

const PORT = Number(process.env.E2E_PORT ?? 5199);

export default defineConfig({
  testDir: 'app/e2e',
  timeout: 120_000,
  expect: { timeout: 30_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${PORT}`,
    ...devices['Desktop Chrome'],
    // MapLibre needs WebGL. Headless Chrome gets it from SwiftShader.
    launchOptions: { args: ['--use-angle=swiftshader', '--enable-unsafe-swiftshader'] },
  },
  webServer: { command: `npx vite --port ${PORT} --strictPort`, url: `http://localhost:${PORT}`, reuseExistingServer: false, timeout: 60_000 },
});
