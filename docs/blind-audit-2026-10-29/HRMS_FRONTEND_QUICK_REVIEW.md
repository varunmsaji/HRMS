# HRMS Frontend — Quick Structural Review

> **Limited scope.** This is a short structural/security glance because the frontend is under active development. It is **not** a complete frontend security audit and says nothing about UI, UX, accessibility, or styling. No frontend file was modified.

## Stack
Next.js 16 (App Router, webpack), React 18.3, TypeScript, Tailwind 3, Radix UI primitives, Vitest + Testing Library, Playwright e2e. Dependencies caret-ranged with `package-lock.json`; CI uses `npm ci`, `tsc --noEmit`, vitest, `next build --webpack`. (ESLint is non-blocking in CI.) Flutter mobile app also present (`apps/mobile`).

## Observations
| ID | Sev | Conf. | Observation | Evidence |
|---|---|---|---|---|
| F-13a | P2 | confirmed | Access token (15 min) + company metadata stored in `localStorage` key `hrms.session`. Refresh token is **not** in JS (HttpOnly cookie, `credentials: "include"`). XSS could steal a live access token. | `src/lib/auth/token-storage.ts` |
| F-13b | P3 | confirmed | `NEXT_PUBLIC_API_URL ?? "http://localhost:8000"` fallback in `lib/api/client.ts:12`, `lib/platform/api.ts:9`, `middleware.ts:30`. Production compose makes the variable mandatory (`docker-compose.prod.yml:249`, `Dockerfile ARG`) so it fails at build, but the silent fallback remains for other build paths. | |
| — | P3 | confirmed | Platform console token handled in `sessionStorage` (`lib/platform/api.ts`, tests) — separate from tenant storage; acceptable. | |
| — | ok | confirmed | No `dangerouslySetInnerHTML` in `src`. | grep |
| — | ok | confirmed | No secrets found in `NEXT_PUBLIC_*` usage (only the API URL). `.env.local` exists locally with localhost URL (ignored by git; `.env.local.example` tracked). | |
| — | ok | confirmed | A Next `middleware.ts` builds CSP/connect-src from the API origin (header logic not reviewed in detail). | |
| — | info | confirmed | Role/permission UI gating is client-side convenience only; every sensitive route I traced enforces permission + scope server-side, so client checks are not load-bearing. | Backend reports |

## Not examined
Duplicate-submission protection on forms (backend offers `Idempotency-Key`), error-handling UX, CSP strictness, dependency CVEs, e2e correctness (`apps/web/e2e/*` not run), API contract mismatches beyond what backend inventory implies.

## Suggested (not done)
Keep tokens in memory with silent refresh before launch to non-pilot customers; fail the build if `NEXT_PUBLIC_API_URL` is unset; make ESLint blocking once the codebase is stable.
