import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:3001",
    trace: "retain-on-failure",
  },
  webServer: {
    command: "pnpm dev:local",
    url: "http://127.0.0.1:3001/api/v1/agent/config",
    reuseExistingServer: true,
    timeout: 120_000,
  },
});
