import type { APIResponse, Page } from "@playwright/test";
import { expect, test } from "@playwright/test";

const API_ORIGIN = "https://api.hrms.test";

interface PageDiagnostics {
  violations: { directive: string; blocked: string }[];
  consoleErrors: string[];
  pageErrors: string[];
  failedRequests: { url: string; reason: string }[];
  requestHosts: Set<string>;
}

/** Records every CSP violation (via the standard `securitypolicyviolation` event, installed
 * before any page script runs), console errors, uncaught errors and failed/third-party requests. */
async function watch(page: Page): Promise<PageDiagnostics> {
  const diag: PageDiagnostics = {
    violations: [],
    consoleErrors: [],
    pageErrors: [],
    failedRequests: [],
    requestHosts: new Set(),
  };
  await page.addInitScript(() => {
    (window as unknown as { __csp: unknown[] }).__csp = [];
    document.addEventListener("securitypolicyviolation", (e) => {
      (window as unknown as { __csp: unknown[] }).__csp.push({
        directive: e.effectiveDirective,
        blocked: e.blockedURI,
      });
    });
  });
  page.on("console", (m) => {
    if (m.type() === "error") diag.consoleErrors.push(m.text());
  });
  page.on("pageerror", (e) => diag.pageErrors.push(e.message));
  page.on("requestfailed", (r) => diag.failedRequests.push({ url: r.url(), reason: r.failure()?.errorText ?? "" }));
  page.on("request", (r) => {
    const url = new URL(r.url());
    if (url.protocol === "http:" || url.protocol === "https:") diag.requestHosts.add(url.origin);
  });
  return diag;
}

async function collectViolations(page: Page, diag: PageDiagnostics) {
  const fromEvents = await page.evaluate(
    () => (window as unknown as { __csp: { directive: string; blocked: string }[] }).__csp ?? [],
  );
  diag.violations.push(...fromEvents);
}

/** React attaches fibers/props to DOM nodes it manages — the browser-side proof of hydration. */
async function isHydrated(page: Page): Promise<boolean> {
  return page.evaluate(() =>
    [...document.querySelectorAll("body *")].some((el) =>
      Object.keys(el).some((k) => k.startsWith("__reactFiber") || k.startsWith("__reactProps")),
    ),
  );
}

function expectClean(diag: PageDiagnostics) {
  expect(diag.violations, "CSP violations").toEqual([]);
  expect(
    diag.consoleErrors.filter((m) => /content security policy|refused to/i.test(m)),
    "CSP console errors",
  ).toEqual([]);
  expect(diag.pageErrors, "uncaught page errors").toEqual([]);
  // Only same-origin app assets and the configured API origin may ever be contacted.
  const allowed = new Set([new URL(test.info().project.use.baseURL as string).origin, API_ORIGIN]);
  expect([...diag.requestHosts].filter((o) => !allowed.has(o)), "unexpected origins contacted").toEqual([]);
  // (A prefetch the router cancels itself shows up as ERR_ABORTED on an `_rsc` URL — not a failure.)
  expect(
    diag.failedRequests.filter(
      (r) => !r.url.startsWith(API_ORIGIN) && !(r.reason === "net::ERR_ABORTED" && r.url.includes("_rsc=")),
    ),
    "failed non-API requests",
  ).toEqual([]);
}

function nonceFromCsp(csp: string | undefined): string {
  return /'nonce-([^']+)'/.exec(csp ?? "")?.[1] ?? "";
}

test.describe("CSP enforced on the production build", () => {
  test("the test browser really enforces the policy (negative controls)", async ({ page }) => {
    const diag = await watch(page);
    await page.goto("/login");
    await page.getByRole("button", { name: "Sign in" }).waitFor();

    // A connection to an origin that is not allowed must be refused by connect-src ...
    const blocked = await page.evaluate(() =>
      fetch("https://evil.example/collect").then(() => "allowed", () => "blocked"),
    );
    expect(blocked).toBe("blocked");
    // ... inline event handlers are not allowed (no 'unsafe-inline' for scripts) ...
    const handlerRan = await page.evaluate(() => {
      const button = document.createElement("button");
      button.setAttribute("onclick", "window.__handler = true");
      document.body.appendChild(button);
      button.click();
      return (window as unknown as { __handler?: boolean }).__handler === true;
    });
    expect(handlerRan).toBe(false);
    // ... a script without this response's nonce, inserted by the parser, must not run ...
    const parsedInlineRan = await page.evaluate(() => {
      const frame = document.createElement("iframe");
      frame.srcdoc = "<script>parent.__parsed = true<\/script>";
      document.body.appendChild(frame);
      return new Promise<boolean>((resolve) =>
        setTimeout(() => resolve((window as unknown as { __parsed?: boolean }).__parsed === true), 500),
      );
    });
    // (an about:srcdoc iframe inherits the policy, so its inline script is refused too)
    expect(parsedInlineRan).toBe(false);
    // ... and eval is refused for page code. Two test-harness details matter here: DevTools'
    // `evaluate` is exempt from the CSP (CDP `allowUnsafeEvalBlockedByCSP`) for everything it runs
    // synchronously, so the attempt is made from a later timer; and the script carries this page's
    // own nonce so that it is allowed to run at all.
    await page.evaluate(() => {
      const script = document.createElement("script");
      script.nonce = (document.querySelector("script[nonce]") as HTMLScriptElement).nonce;
      script.textContent =
        "setTimeout(function () { try { eval('1+1'); window.__eval = 'allowed'; } catch (e) { window.__eval = 'blocked'; } }, 0);";
      document.head.appendChild(script);
    });
    await page.waitForFunction(() => (window as unknown as { __eval?: string }).__eval !== undefined);
    expect(await page.evaluate(() => (window as unknown as { __eval?: string }).__eval)).toBe("blocked");

    await collectViolations(page, diag);
    const directives = diag.violations.map((v) => v.directive);
    expect(directives).toContain("connect-src");
    expect(directives).toContain("script-src-attr");
    expect(directives).toContain("script-src");
  });

  for (const route of ["/login", "/register", "/app/dashboard", "/verify-email/abc123"]) {
    test(`${route}: scripts load, React hydrates, no violations`, async ({ page }) => {
      const diag = await watch(page);
      const scriptResponses: { url: string; status: number }[] = [];
      page.on("response", (r) => {
        if (r.url().includes("/_next/static/chunks/") && r.url().endsWith(".js")) {
          scriptResponses.push({ url: r.url(), status: r.status() });
        }
      });

      await page.goto(route, { waitUntil: "load" });
      if (route === "/app/dashboard") {
        // Unauthenticated: the (client-side) auth guard redirects — only possible once hydrated.
        await page.waitForURL(/\/login$/);
      }
      await page.locator("form, main, body").first().waitFor();
      await expect.poll(() => isHydrated(page)).toBe(true);

      expect(scriptResponses.length).toBeGreaterThan(3);
      expect(scriptResponses.filter((s) => s.status !== 200)).toEqual([]);
      await collectViolations(page, diag);
      expectClean(diag);
    });
  }

  test("login form is interactive and its submit handler runs under the CSP", async ({ page }) => {
    const diag = await watch(page);
    await page.goto("/login");
    const email = page.locator("#email");
    await email.fill("someone@example.com");
    await page.locator("#password").fill("not-a-real-password");
    await expect(email).toHaveValue("someone@example.com");

    await page.getByRole("button", { name: "Sign in" }).click();
    // The request to the configured API origin is allowed by connect-src and then fails at DNS;
    // the app must surface that as an error instead of hanging or being silently blocked.
    await expect(page.getByRole("alert").filter({ hasText: "Could not reach the server" })).toBeVisible();
    await collectViolations(page, diag);
    expect(diag.violations, "CSP violations").toEqual([]);
    expect(diag.failedRequests.some((r) => r.url.startsWith(API_ORIGIN))).toBe(true);
  });

  test("register form is interactive", async ({ page }) => {
    const diag = await watch(page);
    await page.goto("/register");
    await page.locator("#name").fill("Acme Pvt Ltd");
    await expect(page.locator("#name")).toHaveValue("Acme Pvt Ltd");
    await page.locator("#adminEmail").fill("admin@acme.example");
    await expect(page.locator("#adminEmail")).toHaveValue("admin@acme.example");
    await collectViolations(page, diag);
    expect(diag.violations).toEqual([]);
  });
});

test.describe("nonce and cache behaviour of the served HTML", () => {
  const routes = ["/login", "/register", "/app/dashboard", "/verify-email/abc123", "/does-not-exist", "/"];

  async function fetchHtml(request: import("@playwright/test").APIRequestContext, route: string) {
    const response: APIResponse = await request.get(route);
    const headers = response.headers();
    const html = await response.text();
    return { status: response.status(), headers, html, nonce: nonceFromCsp(headers["content-security-policy"]) };
  }

  for (const route of routes) {
    test(`${route}: every script carries this response's nonce; nothing is cached or replayed`, async ({ request }) => {
      const first = await fetchHtml(request, route);
      const second = await fetchHtml(request, route);

      for (const r of [first, second]) {
        expect(r.nonce.length).toBeGreaterThanOrEqual(22);
        const scriptTags = r.html.match(/<script\b[^>]*>/g) ?? [];
        expect(scriptTags.length).toBeGreaterThan(0);
        for (const tag of scriptTags) expect(tag).toContain(`nonce="${r.nonce}"`);
        // Request-time rendering: never a build-time prerender, never shared-cacheable.
        expect(r.headers["x-nextjs-prerender"]).toBeUndefined();
        const cacheControl = r.headers["cache-control"] ?? "";
        expect(cacheControl).toMatch(/no-store/);
        expect(cacheControl).not.toMatch(/s-maxage|public/);
      }

      // A fresh nonce per request, and the first response's nonce appears nowhere in the second.
      expect(first.nonce).not.toBe(second.nonce);
      expect(second.html).not.toContain(first.nonce);
    });
  }

  test("the CSP header values are exactly the strict policy", async ({ request }) => {
    const { headers, nonce } = await fetchHtml(request, "/login");
    const csp = headers["content-security-policy"] ?? "";
    expect(csp).toContain(`script-src 'self' 'nonce-${nonce}' 'strict-dynamic';`);
    expect(csp).toContain(`connect-src 'self' ${API_ORIGIN};`);
    expect(csp).not.toMatch(/script-src[^;]*'unsafe-(inline|eval)'/);
    expect(csp).not.toMatch(/(^|\s)\*(\s|;|$)/);
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("upgrade-insecure-requests");
    expect(headers["strict-transport-security"]).toContain("max-age=63072000");
  });

  test("shared static assets stay long-lived and immutable", async ({ request }) => {
    const { html } = await fetchHtml(request, "/login");
    const chunk = /\/_next\/static\/chunks\/[^"]+\.js/.exec(html)?.[0];
    expect(chunk).toBeTruthy();
    const asset = await request.get(chunk as string);
    expect(asset.status()).toBe(200);
    expect(asset.headers()["cache-control"]).toMatch(/immutable/);
    expect(asset.headers()["cache-control"]).toMatch(/max-age=31536000/);
  });
});

// Only meaningful (and only run) when the suite is pointed at a real nginx+TLS front.
test.describe("through the nginx/TLS reverse proxy", () => {
  test.skip(!process.env.CSP_E2E_BASE_URL, "set CSP_E2E_BASE_URL to run the proxy checks");

  test("TLS is terminated by nginx and the application's security headers arrive intact", async ({ request }) => {
    const response = await request.get("/login");
    const names = response.headersArray().map((h) => h.name.toLowerCase());
    expect(response.url().startsWith("https://")).toBe(true);
    expect(response.headers()["server"]).toMatch(/^nginx/);
    // exactly one of each — nginx neither duplicates nor drops the application's headers
    for (const header of ["content-security-policy", "strict-transport-security", "x-frame-options", "x-content-type-options", "cache-control"]) {
      expect(names.filter((n) => n === header), header).toHaveLength(1);
    }
    const csp = response.headers()["content-security-policy"] ?? "";
    const nonce = nonceFromCsp(csp);
    expect(csp).toContain(`script-src 'self' 'nonce-${nonce}' 'strict-dynamic';`);
    expect(csp).toContain(`connect-src 'self' ${API_ORIGIN};`);
    // body and header come from the same response
    for (const tag of (await response.text()).match(/<script\b[^>]*>/g) ?? []) {
      expect(tag).toContain(`nonce="${nonce}"`);
    }
    expect(response.headers()["cache-control"]).toMatch(/no-store/);
  });

  test("HSTS comes from nginx's forwarded protocol; a client cannot spoof or suppress it", async ({ request }) => {
    const spoofed = await request.get("/login", { headers: { "X-Forwarded-Proto": "http" } });
    expect(spoofed.headers()["strict-transport-security"]).toContain("max-age=63072000");
  });

  test("nonces are still unique per request through the proxy", async ({ request }) => {
    const nonces = new Set<string>();
    for (let i = 0; i < 5; i++) {
      nonces.add(nonceFromCsp((await request.get("/login")).headers()["content-security-policy"]));
    }
    expect(nonces.size).toBe(5);
  });
});
