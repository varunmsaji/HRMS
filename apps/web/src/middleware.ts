import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

/**
 * SEC-05 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17 §5) — security headers for every page
 * this app serves. A per-request nonce on `script-src` is Next.js's own documented strict-CSP
 * pattern (App Router reads the nonce back out of this same `Content-Security-Policy` response
 * header and threads it onto its own inline hydration/bootstrap scripts automatically — no other
 * wiring needed), which avoids `'unsafe-inline'`/`'unsafe-eval'` for scripts entirely.
 *
 * `style-src` keeps `'unsafe-inline'`: Tailwind's compiled stylesheet is a same-origin `<link>`
 * (already covered by `'self'`), but the CSP `style-src` directive also governs the `style=""`
 * HTML attribute, which `nonce-`/hash sources cannot cover (CSP3 §6.2) — and this app has exactly
 * one component using it (`components/ui/progress.tsx`'s dynamic width). `'unsafe-inline'` here
 * only weakens style-injection, not script-injection, and is the same exception Next.js's own
 * strict-CSP guide documents for React apps.
 *
 * `connect-src` includes the configured API origin (`NEXT_PUBLIC_API_URL`) — this app is a pure
 * client fetching a separate-origin JSON API, so `'self'` alone would block every request the
 * app makes. Confirmed from the actual codebase before writing this: no WebSocket, no inline
 * `<script>`, no external script/font CDN, no `next/image` remote origin, and no `<img>` element
 * anywhere in `src/` (verified by search) — so `img-src`/`font-src` need nothing beyond `'self'`.
 */
export function middleware(request: NextRequest) {
  const nonce = Buffer.from(crypto.randomUUID()).toString("base64");
  const isProduction = process.env.NODE_ENV === "production";

  let apiOrigin = "";
  try {
    apiOrigin = new URL(process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").origin;
  } catch {
    apiOrigin = "";
  }

  const cspDirectives = [
    "default-src 'self'",
    // 'unsafe-eval' is dev-only: Next.js's dev bundler executes chunks via eval() for fast
    // refresh, and without this the CSP silently blocks all client-side hydration (forms never
    // become interactive, no client-side JS runs at all) — production builds don't eval().
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isProduction ? "" : " 'unsafe-eval'"}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    // Upgrading http: subresources to https: is only meaningful — and only safe — once this app
    // is actually served over https:. In local dev (always http:) it would try to upgrade the
    // dev API origin to https: and break every request, so it's gated the same way the backend
    // gates HSTS: only when the deployment is known to be a production build.
    ...(isProduction ? ["upgrade-insecure-requests"] : []),
  ];
  const csp = cspDirectives.join("; ");

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });

  response.headers.set("Content-Security-Policy", csp);
  response.headers.set("X-Content-Type-Options", "nosniff");
  response.headers.set("X-Frame-Options", "DENY");
  response.headers.set("Referrer-Policy", "strict-origin-when-cross-origin");
  response.headers.set(
    "Permissions-Policy",
    "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  );
  // Same HTTPS-only rule as the backend's `SecurityHeadersMiddleware` (`hrms.core.
  // security_headers`) — HSTS on a host that isn't actually served over HTTPS yet would make
  // browsers refuse all future HTTP connections to it, locking out access rather than protecting
  // it. `x-forwarded-proto` is what a TLS-terminating reverse proxy sets; this app has none
  // configured yet (Nginx/HTTPS is explicitly a later phase), so this is inert until one exists.
  if (request.headers.get("x-forwarded-proto") === "https") {
    response.headers.set("Strict-Transport-Security", "max-age=63072000; includeSubDomains");
  }

  return response;
}

export const config = {
  matcher: [
    /*
     * Every request path except Next.js internals and static files, which don't need — and for
     * static files, shouldn't have overridden — a per-request CSP nonce.
     */
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
