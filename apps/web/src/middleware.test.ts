// @vitest-environment node
import { NextRequest } from "next/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { config, middleware } from "@/middleware";

function run(path = "/login", headers: Record<string, string> = {}) {
  return middleware(new NextRequest(`http://web.internal:3000${path}`, { headers }));
}

function nonceOf(csp: string | null): string {
  return /'nonce-([^']+)'/.exec(csp ?? "")?.[1] ?? "";
}

/** `NextResponse.next({ request: { headers } })` forwards overridden request headers to the
 * renderer as `x-middleware-request-*` — this is how Next.js receives the nonce to stamp. */
function forwarded(response: Response, name: string): string | null {
  return response.headers.get(`x-middleware-request-${name}`);
}

describe("middleware", () => {
  beforeEach(() => {
    vi.stubEnv("NODE_ENV", "production");
    vi.stubEnv("NEXT_PUBLIC_API_URL", "https://api.example.com");
  });
  afterEach(() => vi.unstubAllEnvs());

  it("sets a CSP with a per-response nonce on the response", () => {
    const csp = run().headers.get("content-security-policy");
    expect(csp).toContain("script-src 'self' 'nonce-");
    expect(csp).toContain("'strict-dynamic'");
    expect(nonceOf(csp)).not.toBe("");
  });

  it("hands the SAME nonce and CSP to the renderer via the request headers", () => {
    const response = run();
    const csp = response.headers.get("content-security-policy");
    expect(forwarded(response, "content-security-policy")).toBe(csp);
    expect(forwarded(response, "x-nonce")).toBe(nonceOf(csp));
  });

  it("uses a different nonce for every request", () => {
    const nonces = new Set(Array.from({ length: 50 }, () => nonceOf(run().headers.get("content-security-policy"))));
    expect(nonces.size).toBe(50);
  });

  it("ignores a client-supplied CSP or nonce header", () => {
    const response = run("/login", {
      "content-security-policy": "script-src 'unsafe-inline'",
      "x-nonce": "attacker",
    });
    const csp = response.headers.get("content-security-policy") ?? "";
    expect(csp).not.toMatch(/script-src[^;]*'unsafe-inline'/);
    expect(csp).not.toContain("attacker");
    expect(forwarded(response, "x-nonce")).not.toBe("attacker");
    expect(forwarded(response, "content-security-policy")).toBe(response.headers.get("content-security-policy"));
  });

  it("allows only self and the build-time API origin in connect-src, with no script weakening", () => {
    const csp = run().headers.get("content-security-policy") ?? "";
    expect(csp).toContain("connect-src 'self' https://api.example.com;");
    expect(csp).not.toMatch(/script-src[^;]*'unsafe-(inline|eval)'/);
    expect(csp).not.toMatch(/(^|\s)\*(\s|;|$)/);
  });

  it("sends HSTS only behind a proxy that reports https", () => {
    expect(run("/login", { "x-forwarded-proto": "https" }).headers.get("strict-transport-security")).toContain("max-age=");
    expect(run("/login", { "x-forwarded-proto": "http" }).headers.get("strict-transport-security")).toBeNull();
    expect(run().headers.get("strict-transport-security")).toBeNull();
  });

  it("does not let x-forwarded-proto change the CSP", () => {
    const a = run("/login", { "x-forwarded-proto": "https" }).headers.get("content-security-policy") ?? "";
    const b = run("/login", { "x-forwarded-proto": "http" }).headers.get("content-security-policy") ?? "";
    expect(a.replace(nonceOf(a), "N")).toBe(b.replace(nonceOf(b), "N"));
  });

  it("does not add Cache-Control itself (Next's request-time rendering owns it, assets stay cacheable)", () => {
    expect(run().headers.get("cache-control")).toBeNull();
  });
});

describe("middleware matcher", () => {
  const matcher = new RegExp(`^${(config.matcher[0] as string).replace(/^\//, "/")}$`);
  const covered = (path: string) => matcher.test(path);

  it("covers every page route, including the ones that used to be prerendered", () => {
    for (const path of ["/", "/login", "/register", "/app/dashboard", "/app/employees/123", "/verify-email/abc", "/does-not-exist", "/platform/login"]) {
      expect(covered(path), path).toBe(true);
    }
  });

  it("leaves Next static assets and the favicon alone", () => {
    for (const path of ["/_next/static/chunks/main.js", "/_next/static/css/app.css", "/_next/image", "/favicon.ico"]) {
      expect(covered(path), path).toBe(false);
    }
  });
});
