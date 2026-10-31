# CSP / hydration remediation (2026-10-29)

Scope: `apps/web` security headers and rendering mode. No Flutter, attendance, payroll or other backend
changes. Nothing committed or deployed. Branch `main`, HEAD `f6340eb7c1679e449ecd87079cb6de01cb5cafec`,
unchanged (working tree: 91 changed/untracked paths before this task, kept; this task added/changed the files listed in §4).

## 1. Root cause (independently reproduced on a production build, Next.js 16.3.8)
`src/middleware.ts` generates a fresh nonce per request and sends `script-src 'self' 'nonce-…' 'strict-dynamic'`. Next.js can
only stamp that nonce on its scripts while it renders *for a request* (Next's own CSP guide: "you must use dynamic rendering
to add nonces"). 58 of 88 routes were prerendered at build time (`○`, `x-nextjs-prerender`, `Cache-Control: s-maxage=31536000`):
their HTML was generated once, with no nonce, so under `strict-dynamic` the browser refused every script and the page
never hydrated. Reproduced on `/login`, `/register`, `/app/dashboard`, `/` and the 404 page; `/verify-email/[token]` (dynamic)
worked. `next dev` renders per request, which is why it was never noticed; earlier "verification" only `curl`ed the header.
The same happens over HTTPS behind nginx — plain HTTP was not the cause. A prerendered page would also have been cached for a year
with a stale nonce.

Also verified (no defect): the built middleware inlines `NEXT_PUBLIC_API_URL` at build time
(`new URL("https://api.hrms.test").origin` in `.next/server/src/middleware.js`), so `connect-src` always matches the
client bundle's API origin, regardless of the container's runtime env; the web container is on the internal `edge` network
only and nginx overwrites `X-Forwarded-Proto` with `$scheme`; the repo's nginx only gzips (no `proxy_cache`, no header rewriting).

## 2. Fix (smallest secure change)
- `src/app/layout.tsx`: root layout is now `async` and calls `await connection()` (Next's documented way to wait for an incoming
  request). That one call makes every route and the not-found page request-rendered. Result: 86 dynamic routes, only the two
  icon image routes stay static (no HTML, no scripts).
- `src/lib/security/csp.ts` (new) + `src/middleware.ts`: the policy construction moved into a pure, unit-tested module. **Policy
  values are unchanged** (still `'self' 'nonce-…' 'strict-dynamic'`, no `unsafe-inline`/`unsafe-eval` for scripts, `connect-src`
  = `'self'` + the one API origin, no wildcards). Nonce generation now uses 128 bits of `crypto.getRandomValues`. The forwarded-protocol
  header only toggles HSTS and only its first hop is read; it can never change the CSP.
- No `Cache-Control` is set by middleware (it would also hit assets). Request-time rendering makes Next send
  `private, no-cache, no-store` on HTML; `/_next/static/**` stays `public, max-age=31536000, immutable`.
- Not changed: nginx config, CSP strictness, fluidity code.

Why it is secure: every HTML response is rendered for that request with that request's nonce, is not shareable/cacheable, and
no HTML exists that could be served without a matching nonce. An attacker who can inject markup still cannot run inline scripts,
inline handlers or `eval`, nor contact any origin except `'self'` and the API (all proven by negative controls in the suite).

## 3. Before / after (same routes, 2 requests each, `X-Forwarded-Proto: https`)
| | before | after |
|---|---|---|
| routes prerendered / dynamic | 58 / 30 | 2 (icons) / 86 |
| `/login`, `/register`, `/app/dashboard`, `/`, 404: `<script>` with this response's nonce | 0 of 17 / 17 / 21 / 15 / 12 | all (17 / 17 / 21 / 15 / 12) |
| browser: CSP-blocked scripts, React hydrated | 17–21 blocked, **not hydrated** | 0 blocked, hydrated |
| HTML `Cache-Control` | `s-maxage=31536000` (static routes) | `private, no-cache, no-store, max-age=0, must-revalidate` |
| nonce across two requests | header differs, body has none | differs; first nonce absent from second body |
| `/_next/static/*.js` | immutable 1 year | unchanged |

## 4. Files
`src/app/layout.tsx`, `src/middleware.ts`, `src/lib/security/csp.ts` (+ `csp.test.ts`), `src/middleware.test.ts`,
`playwright.csp.config.ts`, `e2e-csp/csp.e2e.ts`, `package.json` (`test:e2e:csp`), `vitest.config.ts` (exclude `e2e-csp/**`),
`docs/deployment/PRODUCTION_DEPLOYMENT.md` (§12 verification now checks that scripts carry the response's nonce).

## 5. Tests and results (real exit codes)
- `tsc --noEmit`: 0. `vitest run`: 0 — 92 files / 684 tests (24 new: policy construction, nonce entropy/uniqueness, matcher,
  forwarded-proto handling, request-header propagation, client-supplied CSP/nonce ignored).
- `npm run test:e2e:csp` (builds the production app, serves it, CSP **enforced**, no bypass): **exit 0, 15/15** —
  negative controls (cross-origin fetch blocked, inline handler blocked, parser-inserted inline script blocked, eval blocked),
  `/login` `/register` `/app/dashboard` `/verify-email/abc123`: scripts 200, React hydrated, no violations, only same-origin and the
  API origin contacted; login form fills and submits (request to the allowed API origin, then the app's error state);
  register form interactive; nonce/cache tests on 6 routes × 2 requests (every script carries its own nonce, nonces differ,
  no `x-nextjs-prerender`, `no-store`, never `s-maxage`/`public`); exact header values; static assets immutable.
  **Regression proof:** with the old root layout restored the same suite fails 11 of 15 (exit 1); the layout was then restored.
- Real **nginx 1.27.5 + TLS (HTTP/2)** in front of the production build, using the repo's own `hrms.conf.template`
  (only listen ports and the web upstream address changed), self-signed cert, loopback only: **same suite + 3 proxy tests, 18/18,
  exit 0** — exactly one of each security header, CSP and HSTS arrive unchanged, header/body nonce consistent, HSTS present even when
  the client sends `X-Forwarded-Proto: http`, nonces unique per request, HTTP → 301 HTTPS, assets immutable, no nginx HTML caching.
- Lint: changed/new files clean; repository baseline `eslint .` = 132 errors / 1 warning (pre-existing rule class, unchanged by this task).
- A full `npm run build` into the default `.next` was not run (it would overwrite the running dev server's directory); every
  production build used a separate `NEXT_DIST_DIR`, all exit 0.

## 6. Not verified / remaining risk
- The actual production host, real certificates (Let's Encrypt), the real `NEXT_PUBLIC_API_URL`, any CDN in front of nginx, and the
  Docker image build (`apps/web/Dockerfile`, standalone output) were **not** exercised. The standalone server was not run; `next start` was.
  Run `npm run test:e2e:csp` with `CSP_E2E_BASE_URL` against the staging stack, and the §12 `curl` check, before go-live.
- Any CDN/WAF in front of nginx must not cache HTML (the app now sends `no-store`) or strip/alter `Content-Security-Policy`.
- `style-src 'unsafe-inline'` remains (documented, styles only). `img-src` allows only `'self' data:` — a future `<img>` from the
  storage domain needs a deliberate, minimal addition.
- Request-time rendering means HTML shells are generated per request (small CPU cost, no CDN caching of HTML by design).
