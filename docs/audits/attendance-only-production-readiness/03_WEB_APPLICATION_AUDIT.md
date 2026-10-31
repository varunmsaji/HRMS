# Web application audit

Evidence: working-tree source, `tsc --noEmit` (exit 0), and Vitest. No logged-in browser session against the API was run. CSP browser evidence is in document 08.

## Employee path

| Step | Implementation | Live browser |
|---|---|---|
| Login | `/login`, access token in `localStorage` key `hrms.session`, refresh via HttpOnly cookie | Not executed |
| Landing | `DASHBOARD.COMPANY.VIEW` goes to `/app/dashboard`; otherwise `/app/me` (`lib/auth/landing.ts` 9–12) | Not executed |
| Today’s status | Self view loads the current month of `GET /attendance/days` (`components/attendance/dashboard/self-view.tsx`) | Not executed |
| Check in / out | `PunchEntryDialog` posts `POST /attendance/punches/me` with `{direction, reference?}` when the target is the caller (`punch-entry-dialog.tsx` 87–112). Copy says the server stamps the time. | Not executed. Component tests passed on rerun. |
| See the time and hours | Rendered from the returned punch and from day `worked_minutes` / `formatClockTime` in the company zone | Not executed |
| History and month | Self view and `EmployeeMonthView`. Profile panel defaults a range (`employee-attendance-panel.tsx`). | Not executed |
| Corrections | `regularization-request-dialog.tsx` posts `POST /regularizations` | Not executed |

There is no `/app/attendance/me` route. Self-service is `/app/attendance` (self mode when the user lacks company-wide rows), `/app/me`, and `/app/me/calendar`.

The dialog sets `saving` and disables the button. That does not cover two clicks in the same tick, and no idempotency key is sent. Success is shown from the API response, not before the request returns (the `onRecorded` callback follows the awaited post).

### ATT-WEB-001 — Web punch cannot satisfy a required geofence

- Severity: High if `geofence_mode` is `REQUIRED`. Low at the default `DISABLED`.
- Paths: punch dialog does not call `navigator.geolocation`. `Permissions-Policy` includes `geolocation=()` (`apps/web/src/lib/security/csp.ts` 73). Server rejects a required punch with no fix (`geofence.py` 182–185) and does not insert a row.
- Impact: turning geofence to required makes web self-service check-in fail. Mobile can still send a fix. The policy default is `DISABLED` (`schemas.py` 414).
- Correction: either keep required mode off for web-only staff, or send a location from a page that is allowed to use geolocation and stop blocking it in `Permissions-Policy`.
- Blocks deployment: no at the default. It blocks any rollout that turns geofence on for people who punch from the browser.

### ATT-WEB-002 — “From” date on the profile panel uses the browser calendar

- Severity: Low. Platform: web.
- Path: `employee-attendance-panel.tsx` uses `daysAgoIso` (browser local date) for the start and `businessToday(company timezone)` for the end.
- Impact: around midnight the range can be off by one day relative to `Asia/Kolkata`.
- Blocks deployment: no.

Loading, empty, and error states exist on the attendance page (403 versus generic, retry), the self view, the profile panel, and the company dashboard. `useLatestRequest` aborts stale calls on the workforce overview, pending approvals, and several lists. The attendance day loader (`use-dashboard-data.ts`) marks stale results ignored and does not abort the HTTP call.

## Admin path

`/app/dashboard` (`apps/web/src/app/app/dashboard/page.tsx`):

- Organisation counts come from `GET /dashboards/company` (setup, plan, branch, department, employee counts). Those are not attendance counts.
- Workforce counts come from `useWorkforceOverview` → `GET /dashboards/company/attendance-overview`. The client type in `lib/dashboard/overview.ts` matches `AttendanceOverviewRead`. The comment in that file says the client does not re-derive attendance.
- This API module and these components are **untracked**. They are not in `HEAD`.

Cards: total, present (includes half day), absent, on leave, late (overlay, still inside present), not checked in (today only), exceptions, remote only if non-zero, weekly off/holiday combined as `not_expected`, `no_record`, on duty, incomplete. Department rows show total, present, absent, on leave.

Pending queues are separate list calls (`use-pending-approvals.ts`): submitted leave, submitted regularization, pending overtime, and onboarding states, each gated by its approve/review permission. Preview size is 5. The count is `pagination.total`. Approve and reject dialogs are wired. This audit did not click them.

### ATT-WEB-003 — Two admin surfaces do not count the same people

- Severity: High for operators who compare the two pages. Platform: web + API.
- Paths: `overview.py` 35–105 folds `HALF_DAY` into present and, for today, keeps an in-progress zero-punch day out of absent. `lib/attendance/dashboard.ts` `bucketOf` (261–288) keeps half day, WFH, holiday, and weekly off separate. Drill links from the company card (`overview.ts` 54–78) do not filter exceptions or weekly off.
- Impact: “Present” on the company dashboard can be larger than “Present” on `/app/attendance`. That is a trust problem even when both numbers are internally consistent with their own rules.
- Correction: drive both pages from the overview buckets, or label the Attendance page as a row sample rather than a company total.
- Blocks deployment: no if admins are told to use `/app/dashboard` for the daily total and the overview code is what ships. It blocks using `/app/attendance` as the system of record for headcount.

### ATT-WEB-004 — Attendance command centre silently stops at 500 rows

- Severity: High for companies above roughly 35 people over a 14-day window. Platform: web.
- Paths: API max 500; `use-dashboard-data.ts` uses `apiClient.get` and discards `pagination`. The employee directory on the same page does page and does warn.
- Impact: KPIs and hour charts under-count with no truncation message.
- Blocks deployment: not for a pilot under that size. Required before a larger company relies on that page. See ATT-API-001.

Roster calendar (`rosters/calendar/page.tsx`) uses a single `apiClient.get` on a paged roster list. The grid page follows further pages. A large calendar can stop at 500 entries.

## Navigation and payroll

Sidebar (`components/layout/nav-items.ts` 61–100) shows Attendance, rosters, regularizations, overtime, leave, and **Payroll → `/app/payroll/pay-runs`** with no permission gate. Settings also lists salary components, structures, and statutory rates.

Attendance routes do not import payroll modules. A payroll page error is caught by the app route error boundary and does not remove the Attendance link. Unfinished payroll does not prevent the web app from building (`tsc --noEmit` passed).

### ATT-WEB-005 — Payroll is presented as a live product

- Severity: Low for availability. Medium for operator trust.
- Path: `nav-items.ts` 90–94 and the settings payroll group.
- Impact: an admin can open pay runs during an attendance-only launch. Those screens are API-backed, not placeholders. They are outside this release’s promise.
- Correction: hide the group or mark it as not part of this release. Do not delete the module.
- Blocks deployment: no.

## Timezone display

Formatters require a zone (`lib/attendance/format.ts`). Fallback at call sites is `user.company_timezone ?? "Asia/Kolkata"`. `lib/timezones.ts` is the company/branch/shift picker, not the attendance clock. On-behalf punch time is converted with `wallTimeToUtcIso` in the company zone. The isolated Vitest rerun confirmed that 09:00 IST maps to the same UTC instant under process timezones `Asia/Kolkata` and `UTC`.

## Auth client

- Bearer token and `X-Company-Id` on every call, `credentials: "include"` (`lib/api/client.ts` 102–136).
- 401 refreshes `POST /v1/auth/token/refresh` once, with a Web Lock across tabs.
- Base URL: `process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"` (`client.ts` 12). CSP `connect-src` inlines that origin at **build** time (`csp.ts` 10–13, 46). A runtime env change in the container does not retarget the browser.

## CSP (code)

Working tree, also uncommitted relative to the portions touched in `middleware.ts` and `layout.tsx`:

- Per-request 128-bit nonce (`csp.ts` 17–21).
- Production `script-src`: `'self' 'nonce-…' 'strict-dynamic'`. Development adds `'unsafe-eval'`.
- `style-src 'unsafe-inline'` remains.
- Root layout awaits `connection()` so HTML is not prerendered without a nonce (`app/layout.tsx` 39–52).
- `img-src 'self' data:'`. A company logo URL on another host will be blocked. The dashboard renders `profile.branding.logo_url` (`dashboard/page.tsx`). The middleware comment that says there is no `<img>` in `src/` is stale.

Browser enforcement is covered in document 08. A previous note, `docs/audits/CSP_HYDRATION_REMEDIATION_2026-10-29.md`, says the fix was not committed or deployed. That is still true of git: the changes are in the working tree.

## UI quality

From code, not from a responsive browser pass:

- Routes used by attendance exist as `page.tsx` files (attendance, dashboard, shifts, rosters, regularizations, leave, calendars).
- Buttons that post attendance disable while saving.
- Empty and error copy is present on the main attendance and dashboard components.
- This audit did not measure overflow at mobile width, focus order, or console errors in a real session.

### ATT-WEB-006 — No end-to-end browser proof of check-in

- Severity: High as a release gate, not as a located defect.
- Evidence: unverified. Component tests mock the client.
- Impact: integration mistakes (cookie, company header, CSP connect-src, hydration) would not show up in Vitest.
- Correction: run the existing API integration tests and one browser pass of login → check-in → check-out → history on the production build.
- Blocks deployment: yes as part of ATT-QA-001, not as a separate code defect.
