// @vitest-environment node
import { describe, expect, it } from "vitest";

import {
  buildContentSecurityPolicy,
  generateNonce,
  isForwardedHttps,
  resolveApiOrigin,
  responseSecurityHeaders,
} from "@/lib/security/csp";

const prod = { nonce: "NONCE123==", isProduction: true, apiOrigin: "https://api.example.com" };

function directives(policy: string): Map<string, string[]> {
  return new Map(
    policy.split(";").map((part) => {
      const [name, ...values] = part.trim().split(/\s+/);
      return [name as string, values];
    }),
  );
}

describe("generateNonce", () => {
  it("is base64 with at least 128 bits of entropy and unique per call", () => {
    const nonces = new Set(Array.from({ length: 500 }, () => generateNonce()));
    expect(nonces.size).toBe(500);
    for (const nonce of nonces) {
      expect(nonce).toMatch(/^[A-Za-z0-9+/]+={0,2}$/);
      expect(atob(nonce).length).toBeGreaterThanOrEqual(16);
    }
  });
});

describe("buildContentSecurityPolicy (production)", () => {
  const policy = buildContentSecurityPolicy(prod);
  const d = directives(policy);

  it("limits scripts to self + this response's nonce + strict-dynamic, nothing broader", () => {
    expect(d.get("script-src")).toEqual(["'self'", "'nonce-NONCE123=='", "'strict-dynamic'"]);
    expect(policy).not.toMatch(/script-src[^;]*'unsafe-(inline|eval)'/);
  });

  it("allows connections only to self and the configured API origin", () => {
    expect(d.get("connect-src")).toEqual(["'self'", "https://api.example.com"]);
  });

  it("keeps the restrictive defaults and upgrades insecure requests", () => {
    expect(d.get("default-src")).toEqual(["'self'"]);
    expect(d.get("object-src")).toEqual(["'none'"]);
    expect(d.get("base-uri")).toEqual(["'self'"]);
    expect(d.get("form-action")).toEqual(["'self'"]);
    expect(d.get("frame-ancestors")).toEqual(["'none'"]);
    expect(d.get("img-src")).toEqual(["'self'", "data:"]);
    expect(d.get("font-src")).toEqual(["'self'"]);
    expect(d.has("upgrade-insecure-requests")).toBe(true);
  });

  it("never contains a wildcard source or a catch-all scheme", () => {
    expect(policy).not.toMatch(/(^|\s)\*(\s|;|$)/);
    expect(policy).not.toMatch(/\bhttps?:(\s|;|$)/);
  });

  it("only style-src keeps unsafe-inline (the documented, style-only exception)", () => {
    expect(d.get("style-src")).toEqual(["'self'", "'unsafe-inline'"]);
    for (const [name, values] of d) {
      if (name !== "style-src") expect(values).not.toContain("'unsafe-inline'");
    }
  });

  it("omits the API origin entry when the URL could not be parsed", () => {
    const d2 = directives(buildContentSecurityPolicy({ ...prod, apiOrigin: "" }));
    expect(d2.get("connect-src")).toEqual(["'self'"]);
  });
});

describe("buildContentSecurityPolicy (development)", () => {
  it("adds unsafe-eval to script-src only, and does not upgrade insecure requests", () => {
    const policy = buildContentSecurityPolicy({ ...prod, isProduction: false });
    expect(directives(policy).get("script-src")).toContain("'unsafe-eval'");
    expect(directives(policy).has("upgrade-insecure-requests")).toBe(false);
  });
});

describe("resolveApiOrigin", () => {
  it("reduces the URL to its origin", () => {
    expect(resolveApiOrigin("https://api.example.com/v1/x?y=1")).toBe("https://api.example.com");
    expect(resolveApiOrigin("http://localhost:8000")).toBe("http://localhost:8000");
  });
  it("defaults to the local dev API and tolerates garbage", () => {
    expect(resolveApiOrigin(undefined)).toBe("http://localhost:8000");
    expect(resolveApiOrigin("not a url")).toBe("");
  });
});

describe("forwarded protocol handling", () => {
  it("sends HSTS only when the proxy says https", () => {
    expect(responseSecurityHeaders(prod, "https")["Strict-Transport-Security"]).toContain("max-age=63072000");
    expect(responseSecurityHeaders(prod, "http")["Strict-Transport-Security"]).toBeUndefined();
    expect(responseSecurityHeaders(prod, null)["Strict-Transport-Security"]).toBeUndefined();
  });

  it("looks only at the first hop and is case/whitespace tolerant", () => {
    expect(isForwardedHttps("https, http")).toBe(true);
    expect(isForwardedHttps(" HTTPS ")).toBe(true);
    expect(isForwardedHttps("http, https")).toBe(false);
    expect(isForwardedHttps("")).toBe(false);
  });

  it("never lets the forwarded header change the CSP", () => {
    expect(responseSecurityHeaders(prod, "https")["Content-Security-Policy"]).toBe(
      responseSecurityHeaders(prod, "http")["Content-Security-Policy"],
    );
    expect(responseSecurityHeaders(prod, "evil, https")["Content-Security-Policy"]).toBe(
      buildContentSecurityPolicy(prod),
    );
  });
});

describe("responseSecurityHeaders", () => {
  it("always carries the fixed hardening headers", () => {
    const h = responseSecurityHeaders(prod, null);
    expect(h["X-Content-Type-Options"]).toBe("nosniff");
    expect(h["X-Frame-Options"]).toBe("DENY");
    expect(h["Referrer-Policy"]).toBe("strict-origin-when-cross-origin");
    expect(h["Permissions-Policy"]).toContain("camera=()");
  });
});
