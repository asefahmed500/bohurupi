import { defineConfig } from "@playwright/test";

// E2E against the local stack: web on :3300, API on :8000 (both CORS-allowed).
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  retries: 1,
  reporter: [["list"]],
  use: {
    baseURL: "http://localhost:3300",
    trace: "retain-on-failure",
    locale: "en-US",
  },
});
