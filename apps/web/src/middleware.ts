import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import {
  generateNonce,
  resolveApiOrigin,
  responseSecurityHeaders,
} from "@/lib/security/csp";

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
  const options = {
    nonce: generateNonce(),
    isProduction: process.env.NODE_ENV === "production",
    apiOrigin: resolveApiOrigin(process.env.NEXT_PUBLIC_API_URL),
  };
  const headers = responseSecurityHeaders(options, request.headers.get("x-forwarded-proto"));

  // Next.js reads the nonce back out of the *request's* CSP header while it server-renders the
  // page and stamps it on every framework script. That only happens for request-time rendering —
  // see the root layout, which opts the whole app out of build-time prerendering so no HTML is
  // ever produced without a nonce.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", options.nonce);
  requestHeaders.set("Content-Security-Policy", headers["Content-Security-Policy"]!);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  for (const [name, value] of Object.entries(headers)) response.headers.set(name, value);
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
