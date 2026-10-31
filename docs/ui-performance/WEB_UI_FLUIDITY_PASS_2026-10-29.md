# Web UI fluidity pass — audit and results (2026-10-29)

Scope: `apps/web` only. No backend, database or Flutter changes. Nothing committed.

## Method
- Production build (`next build --webpack`, `next start`) against a disposable loopback stack
  (`browser_stack.sh`, run `browser-perf1`, removed afterwards), 125 seeded employees.
- Playwright + Chromium, 1440x900, **4x CPU throttle**, with and without a simulated 150 ms
  per-request API latency (loopback otherwise hides network cost). Event Timing, long tasks and
  layout shift were captured in-page. Event Timing is quantised to 8 ms.
- Scripts live outside the repo (session scratchpad); they are not part of this change.
- CSP was bypassed in the test browser context only (see finding F1).

## Baseline (before)
Interactions were already cheap on this dataset: max interaction 16-72 ms, 0-1 long tasks,
CLS ~0, no console errors. The measurable problems were about **perceived** behaviour under
latency, not main-thread cost.

## Findings (prioritised)

| # | Finding | Evidence | Status |
|---|---------|----------|--------|
| F1 | A production build served over plain HTTP loads **no scripts**: the nonce + `strict-dynamic` CSP in `src/middleware.ts` cannot nonce statically prerendered pages, and `upgrade-insecure-requests` upgrades the API origin. | Browser console: every `/_next/static/chunks/*.js` blocked by CSP; login never completes. | **Not changed** (security-sensitive). Verify how production is actually deployed; needs its own decision. |
| F2 | Paginated lists replace the whole table (and the toolbar/search box, and the pagination footer) with a spinner on every page change. | Employees "Next": 10 blank frames at 150 ms latency; toolbar + footer unmount during load. | **Fixed** on employees, users, leave-applications, policy-assignments. |
| F3 | No request cancellation or sequencing: `apiClient` had no caller `signal`; 73 pages hand-roll `useEffect` fetches, only ~14 guard against stale results. Leave applications fires two requests on every filter change (old page, then page 1). | Code audit. | **Primitive added** (`signal`, `useLatestRequest`) and applied to the 4 pages above. 69 other pages unchanged. |
| F4 | `TableSkeleton` existed but was used nowhere; first loads use a centred spinner that collapses the layout. | grep: 0 usages; 77 `<LoadingState>` in pages. | **Fixed** on the 4 pages (skeleton on first load only). |
| F5 | Every full page load waits for `/auth/me` before any page renders, so page data starts one round trip late (3 sequential round trips to content). | Revisit of `/app/employees` = ~900 ms at 150 ms latency vs ~190 ms at 0 ms. | **Not changed.** Rendering gated pages before permissions are known risks flashing hidden content; needs a design decision. |
| F6 | No client cache: roster/grid/calendar pages refetch employees (hard-capped at 100) and shifts on every visit. | Network capture: 5 API calls on navigation to the roster grid. | **Not changed.** Cache must be tenant/user scoped and invalidated on mutation. |
| F7 | Roster grid/calendar fetch up to 500 entries with no paging; employee pickers silently cap at 100. | Code: `bounded_pagination_params` max 500; `per_page: 100`. | **Not changed** (data-correctness bug for large teams, reported separately). |
| F8 | No code splitting, `React.memo` or debouncing anywhere. | grep. | Not needed by measurement: no long tasks, filter is local `useMemo` on one page of rows. Left alone deliberately. |

## Changes
- `lib/api/client.ts`: optional `signal`; cancellation rejects with `AbortError`, never `ApiError`.
- `hooks/use-latest-request.ts` (new): cancels the previous request, ignores stale results, aborts on unmount.
- `components/common/busy-region.tsx` (new): keeps old content visible, dimmed and non-interactive, with an
  announced "Refreshing…" status, instead of swapping to a spinner.
- Employees, Users, Leave applications, Policy assignments pages: use the above; skeleton on first load;
  toolbar and pagination stay mounted (pagination disabled while loading).
- `ui/button.tsx`: pressed state for `ghost`/`tertiary` variants (they had none).
- `ui/dialog.tsx`, `ui/sheet.tsx`: shorter open/close animation (dialog 200→150 ms; sheet 300→200 open, 200→150 close).
  **Not measured** — a perceptual choice, honours `prefers-reduced-motion` through the existing global rule.
- Tried and **reverted**: press-scale + wider transition property on buttons (decorative, no benefit).

## After (150 ms latency, 4x CPU, 3 runs each)
- Employees "Next page": blank frames **10 → 0** in all three runs.
- Max interaction, long tasks, CLS, request counts: unchanged within noise, except dialog open
  (72 → 80-96 ms) and dialog typing (40 → 48-56 ms) which read slightly higher. Reverting the button and
  dialog changes did not remove it, so it is not attributable to them; likely run-to-run/machine drift
  (8 ms granularity), but it is **not proven** noise because the old build could not be re-measured.
- Responsive: no horizontal overflow at 1440, 768 and 375 px on the four changed pages.

## Verification
- `tsc --noEmit`: exit 0. `vitest run`: 630 passed (baseline 623; +7 new tests), exit 0.
- `eslint .`: exit 1 with 127 errors, same count as before this pass (pre-existing, mostly React-compiler
  `set-state-in-effect`); no new errors in changed files.
- `next build --webpack`: exit 0 (three times).

## Not done / remaining
- F1, F5, F6, F7 above.
- Other 69 hand-rolled fetch pages keep the old spinner-swap pattern; onboarding and leave-balances have the
  same paged-list shape and are the obvious next candidates for `BusyRegion` + `useLatestRequest`.
- No keyboard/screen-reader walkthrough beyond the roles/labels exercised by the new unit tests.
- Payroll and attendance workflows were not exercised in the browser.
