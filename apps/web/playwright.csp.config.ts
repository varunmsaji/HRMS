import { defineConfig } from "@playwright/test";

/**
 * Production-build browser tests with the real Content-Security-Policy ENFORCED.
 *
 * Unlike `playwright.config.ts` (which drives the disposable API/database stack against a dev
 * server), this config needs no database or API: it builds the production app, serves it with
 * `next start` and checks CSP/hydration/cache behaviour. It deliberately never sets
 * `bypassCSP` — a test browser that ignores the CSP would hide exactly the failure this suite
 * exists to catch. `NEXT_PUBLIC_API_URL` is a fake HTTPS origin: connections to it are *allowed*
 * by `connect-src` (and then fail at DNS), anything else must be blocked.
 *
 *   npm run test:e2e:csp
 *
 * Set CSP_E2E_CHROMIUM to use a specific Chromium binary instead of Playwright's own.
 *
 * Deployment-path mode: set CSP_E2E_BASE_URL=https://web.hrms.test:18443 to run the same suite
 * against an already-running nginx+TLS front of a production build (no webServer is started, no
 * forwarded-protocol header is injected — nginx must supply it — and the self-signed test
 * certificate is accepted). CSP_E2E_HOST_MAP="web.hrms.test=127.0.0.1" maps the test hostname.
 */
const PORT = 13011;
const API_ORIGIN = "https://api.hrms.test";
const DIST = ".next-csp-e2e";
const EXTERNAL_BASE_URL = process.env.CSP_E2E_BASE_URL;
const HOST_MAP = process.env.CSP_E2E_HOST_MAP; // e.g. "web.hrms.test=127.0.0.1"

export default defineConfig({
  testDir: "./e2e-csp",
  testMatch: "**/*.e2e.ts",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: EXTERNAL_BASE_URL ?? `http://127.0.0.1:${PORT}`,
    // Direct mode only: what nginx sets on every proxied request
    // (infra/nginx/conf.d/hrms.conf.template). Behind the real nginx it must come from nginx.
    extraHTTPHeaders: EXTERNAL_BASE_URL ? {} : { "X-Forwarded-Proto": "https" },
    ignoreHTTPSErrors: Boolean(EXTERNAL_BASE_URL), // self-signed test certificate only
    launchOptions: {
      ...(process.env.CSP_E2E_CHROMIUM ? { executablePath: process.env.CSP_E2E_CHROMIUM } : {}),
      ...(HOST_MAP ? { args: [`--host-resolver-rules=MAP ${HOST_MAP}`] } : {}),
    },
  },
  metadata: { apiOrigin: API_ORIGIN },
  webServer: EXTERNAL_BASE_URL
    ? undefined
    : {
        command: `npx next build --webpack && npx next start --hostname 127.0.0.1 --port ${PORT}`,
        url: `http://127.0.0.1:${PORT}/login`,
        timeout: 600_000,
        reuseExistingServer: false,
        env: { NEXT_PUBLIC_API_URL: API_ORIGIN, NEXT_DIST_DIR: DIST },
        stdout: "ignore",
        stderr: "pipe",
      },
});
