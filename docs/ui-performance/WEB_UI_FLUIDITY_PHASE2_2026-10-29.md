# Web UI fluidity — phase 2 (2026-10-29)

Scope: `apps/web` only. No backend, database, CSP or Flutter changes. Nothing committed.
Start: branch `main`, HEAD `f6340eb`, 61 changed/untracked paths (all kept). End: same HEAD, 91 paths.

## 1. Verification of the phase-1 work
Read and exercised `lib/api/client.ts`, `use-latest-request`, `BusyRegion` and the four pages.
- Cancellation: caller `signal` aborts the underlying fetch; rejection is an `AbortError`, never an `ApiError`
  (no error UI, no spurious refresh/retry). Verified by `client.test.ts`.
- Stale responses: `useLatestRequest().isCurrent()` guards every setState; verified by new tests that make an older
  response arrive last (leave balances, onboarding).
- Unmount: in-flight request is aborted (tests on employees, leave balances, onboarding, directory).
- Failure: a failed refresh clears the data and shows the error; it never shows the previous page as current and never
  a success state (tests on leave balances, onboarding).
- `BusyRegion`: `pointer-events-none` while busy, so rows cannot be clicked while they are about to be replaced; the
  `role="status"` "Refreshing…" announcement is only rendered while busy (not on every interaction).
- Gap found and fixed: onboarding hid its toolbar (status filter) during every load; leave balances would have kept
  the *previous employee's* balances dimmed under a new selection — now cleared immediately (see 4).

## 2. Silent limits (audit → fix)
API facts (read from the backend): `GET /employees` is paginated, **max 100/page, no search and no id-batch lookup**;
`GET /rosters`, `/regularizations`, `/overtime` are "bounded" lists — default and max **500/page**, paginated, with
`pagination.total`.

| Place | Was | Classification | Now |
|---|---|---|---|
| 17 employee dropdowns (rosters list/calendar/entry dialog, regularizations page+dialog, overtime, leave applications+dialog, leave balances, punch dialog, policy resolution, geofences, department head, assignment manager ×2) | first 100 only; others unreachable | silent restriction, functional defect | `EmployeeSelect` + `useEmployeeDirectory`: shows "Showing N of TOTAL", explicit **Load more** (bounded by user action), filter that says it only searches what is loaded, selection kept across loads, error + retry |
| name columns built from that list (rosters, regularizations, overtime, leave applications, geofences, department head, assignment manager) | raw UUID / "Unknown" for anyone past 100 | silent display defect | `useEmployeeNames`: loaded directory first, otherwise one `GET /employees/{id}` per unseen id (4 concurrent, per-page cache, never shared across users/tenants; 403/404 → "Unavailable employee") |
| Roster grid | first 100 employees ∩ first 500 entries, no warning | silent partial dataset | employee rows paged on the server (50/page, reachable to the end); roster entries loaded across pages (parallel, ≤10 pages = 5,000); if the range is larger a visible warning says so |
| Roster list, regularizations list, overtime list | first 500 rows, no paging controls | silent truncation | `getList` + `PaginationControls` (100/page), filters reset to page 1 |
| Roster calendar | one employee, ≤42 rows | safety bound, provably complete (≤1 entry/employee/date) | unchanged, documented in code; employee picker fixed |
| Geofence authorisations | first 100, no paging | silent | visible "Showing first N of M" warning |
| Departments list `employees` fetch | 100, only used by the form | picker | now loads only while the form is open |

Not changed: other `per_page: 100` fetches that are not employee lists (holiday calendars: year-scoped reference data).

**API limitation (no backend change made):** without `?q=`/`search` and an `ids=` batch lookup on `/employees`, a company
with thousands of employees must use "Load more" to find someone, and name columns cost one request per unseen id.
Recommended backend work: `GET /employees?search=` (server-side) and `GET /employees?ids=a,b,c` (batch, scope-filtered).

Proof of completeness (tests, all passing): 342 employees across 4 server pages reachable through the hook; 230 through the
picker incl. selecting #230; roster grid with 1,200 entries (entry #1100 on server page 3 is rendered), 120 employees
(Person120 reachable by paging), 6,000 entries (exactly 10 pages fetched, warning shown); roster list with 205 employees
(employee beyond 100 is named, not shown as an id) and 130 entries over 2 pages.

## 3. Loading pattern extended
Adopted (page state fit): leave balances, onboarding (+ the four from phase 1). New this phase: roster list, regularizations,
overtime, roster grid. Deliberately not applied elsewhere (single-record or form pages have no list refresh to preserve).
Tests: skeleton on first load, rows kept + dimmed + controls disabled during refresh, refresh failure shows error and no
stale rows/no success state, late response for a superseded filter/employee ignored, abort on unmount.

## 4. Measurement (same dataset/viewport/throttle/latency)
Dataset: 250 employees, 1,500 roster entries (6/employee) in the 14-day window. Production builds, 1440x900, 4x CPU throttle,
150 ms added per API request, 3 runs each, isolated stack `browser-perf2` (removed afterwards).

| | before | after |
|---|---|---|
| time to grid visible | 1007 / 1016 / 998 ms | 1035 / 1027 / 1038 ms |
| employee rows rendered | 100 (of 250; the rest unreachable) | 50 per page, last employee reachable (4 page clicks) |
| entries shown for the rows on screen | 200 of 600 (33%) | 300 of 300 (100%) |
| roster requests | 1 (first 500 of 1,500 entries) | 3 (all 1,500) |
| API calls total | 5 | 7 |
| long tasks / max interaction | 0 / 0 ms | 0 / 0 ms |
| CLS | 0.014 | 0.047 |

There is **no speed improvement** to claim: time-to-grid is ~3% slower (consistent, within a few tens of ms), CLS rose from
0.014 to 0.047 (still under the 0.1 "good" threshold; likely the pagination footer and skeleton→grid swap). The change is a
**correctness** fix: before, a 14-day grid silently showed one third of the entries and 60% of the employees.
Phase-1 results (paging flash 10 → 0 blank frames) are in the earlier report.

## 5. Production CSP — audit only (nothing changed)
Reproduced on a production build with the CSP enforced (no bypass) and `X-Forwarded-Proto: https` (what nginx sets):

| route kind | count (build) | `<script>` with nonce | scripts blocked by CSP | React hydrated |
|---|---|---|---|---|
| prerendered `○` (`/login`, `/app/dashboard`, …) | 58 | 0 / 17 (`/login`), 0 / 21 (`/app/dashboard`) | 17, 21 | **no** |
| dynamic `ƒ` (`/verify-email/[token]`, `[id]` pages) | 30 | 16 / 16 | 0 | yes |

1. **Reproduces under the intended deployment?** Yes — the cause is not plain HTTP. `middleware.ts` puts a fresh
   `'nonce-…' 'strict-dynamic'` in `script-src`, but Next only injects nonces during request-time rendering (official guide:
   "you must use dynamic rendering to add nonces"). Prerendered HTML is built without a request, so its scripts carry no nonce and,
   because `strict-dynamic` makes `'self'` ineffective, every script is refused. The same happens over HTTPS behind nginx.
   `next dev` renders on demand, which is why it works in development. The earlier "verified" claims
   (`RELEASE_HARDENING_PHASE_4…`, `PRODUCTION_DEPLOYMENT.md` step) only `curl`ed the header; nothing checks that scripts execute.
   The prerendered responses also carry `Cache-Control: s-maxage=31536000`, so even a fixed nonce would be cached for a year.
2. **Affected paths:** all 58 prerendered routes, including `/login`, `/register` and every `/app/**` list page — the login page cannot
   hydrate. `upgrade-insecure-requests` is not the cause here (it only matters if the API origin is http; behind TLS it is correct).
3. **Remediation proposal (not implemented):** make HTML request-rendered so every response gets a matching nonce — in
   `app/layout.tsx` (root) add `export const dynamic = "force-dynamic"` (or `await connection()`), keeping the middleware, `strict-dynamic`,
   no `unsafe-*`. Cost: no static HTML caching for pages that are tiny client shells anyway. Alternative if static HTML must be kept:
   Next's experimental SRI (hash-based script CSP) — needs a Next 16 compatibility check and is more invasive. Ensure nginx does not cache
   HTML responses. Also confirm the runtime value of `NEXT_PUBLIC_API_URL` used by the middleware for `connect-src` inside the standalone container.
4. **Verification to require before shipping:** (a) a Playwright test on a *production build* with CSP enforced asserting zero CSP violations and
   hydration on `/login`, `/register`, `/app/dashboard`, one `[id]` page; (b) a build-output check that every `<script>` in served HTML carries the
   nonce from that response's header and that nonces differ per request; (c) unit tests for `middleware.ts` (header values, nonce uniqueness,
   matcher, `x-forwarded-proto` handling — none exist today); (d) `Cache-Control` on HTML is `no-store`/`private`; (e) the same check through the
   real nginx+TLS compose stack.

## 6. Verification results
- `tsc --noEmit`: exit 0.  `vitest run`: exit 0, 90 files / 660 tests (phase-1 end: 83 / 630).
- `eslint .`: exit 1, **132 errors / 1 warning** vs baseline 127 / 1: 5 more errors, all the repo's existing
  `react-hooks/set-state-in-effect` rule (fetch-in-effect pattern, same as the other pages); no other rule; no new warning.
- `next build --webpack`: exit 0 (four times, in separate dist dirs, all removed).
- Browser: production builds on the isolated loopback stack; pages used: `/app/rosters/grid` (desktop, 1440x900) for the measurement;
  CSP reproduction on `/login`, `/verify-email/abc`, `/app/dashboard`. The other changed pages were verified by unit tests, not in a browser this phase.
  No tablet/mobile pass this phase.
