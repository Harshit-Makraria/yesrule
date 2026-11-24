import { defineConfig, devices } from "@playwright/test";

const PORT = 8791;
export default defineConfig({
  testDir: "e2e",
  fullyParallel: false,
  workers: 1, // one shared engine database: the specs run in order as one story
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: `http://localhost:${PORT}`,
    // Local: the installed Chrome. CI: Playwright's bundled Chromium.
    ...devices["Desktop Chrome"],
    channel: process.env.CI ? undefined : "chrome",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "./e2e/start-engine.sh",
    url: `http://localhost:${PORT}/health`,
    env: { PORT: String(PORT) },
    reuseExistingServer: false,
    timeout: 120_000,
  },
});
