/** Pure construction of the response security headers, kept separate from `middleware.ts` so the
 * exact policy can be unit-tested. See `middleware.ts` for the rationale behind each directive.
 *
 * Nothing here is allowed to widen the policy: scripts are limited to `'self'` + the per-request
 * nonce with `'strict-dynamic'`; there is no `'unsafe-inline'`/`'unsafe-eval'` for scripts in
 * production, and no wildcard origin anywhere. */

export interface SecurityHeaderOptions {
  nonce: string;
  /** `process.env.NODE_ENV === "production"` — inlined at build time. */
  isProduction: boolean;
  /** Origin of the API the browser may call (`NEXT_PUBLIC_API_URL`), or "" if unparseable. */
  apiOrigin: string;
}

/** A fresh unpredictable nonce: 128 bits from the platform CSPRNG, base64-encoded. */
export function generateNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

/** The origin (scheme + host + port) of the configured API URL — never a path, never a wildcard. */
export function resolveApiOrigin(rawApiUrl: string | undefined): string {
  try {
    return new URL(rawApiUrl ?? "http://localhost:8000").origin;
  } catch {
    return "";
  }
}

export function buildContentSecurityPolicy({
  nonce,
  isProduction,
  apiOrigin,
}: SecurityHeaderOptions): string {
  return [
    "default-src 'self'",
    // 'unsafe-eval' is dev-only: Next.js's dev bundler executes chunks via eval() for fast
    // refresh. Production builds do not eval().
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${isProduction ? "" : " 'unsafe-eval'"}`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self'",
    `connect-src 'self'${apiOrigin ? ` ${apiOrigin}` : ""}`,
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(isProduction ? ["upgrade-insecure-requests"] : []),
  ].join("; ");
}

/** True only when the first hop recorded by the TLS-terminating proxy says https. The web
 * container is not published to the network (docker-compose.prod.yml puts it on the internal
 * `edge` network behind nginx), and nginx overwrites the header with its own `$scheme`, so a
 * client cannot choose this value in the intended deployment. It only ever toggles HSTS — it
 * never changes the CSP. */
export function isForwardedHttps(headerValue: string | null): boolean {
  return (headerValue?.split(",")[0]?.trim().toLowerCase() ?? "") === "https";
}

export function responseSecurityHeaders(
  options: SecurityHeaderOptions,
  forwardedProto: string | null,
): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Security-Policy": buildContentSecurityPolicy(options),
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
  };
  // HSTS on a host not actually served over HTTPS would lock browsers out, so it is only sent
  // when the proxy reports that the client connection was HTTPS.
  if (isForwardedHttps(forwardedProto)) {
    headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains";
  }
  return headers;
}
