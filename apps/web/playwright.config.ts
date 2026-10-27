import path from "node:path";

import { defineConfig } from "@playwright/test";

const artifacts = process.env.E2E_ARTIFACTS ?? path.join(__dirname, "e2e/.artifacts");

export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts",
  timeout: 180_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  outputDir: path.join(artifacts, "playwright"),
  globalSetup: "./e2e/global-setup.ts",
  use: {
    baseURL: process.env.E2E_WEB_URL ?? "http://127.0.0.1:13000",
    // Traces embed localStorage tokens, so they stay off. Failures still keep a screenshot
    // and the diagnostics log written by the tests (status codes and paths only).
    trace: "off",
    screenshot: "only-on-failure",
    video: "off",
  },
});
