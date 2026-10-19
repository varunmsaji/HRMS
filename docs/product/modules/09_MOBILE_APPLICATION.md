# Module 09 — Mobile Application (Flutter)

> Part of [Staff Spectrum HRMS Functional Documentation](../STAFF_SPECTRUM_HRMS_FUNCTIONAL_DOCUMENTATION.md) · [Catalog](../STAFF_SPECTRUM_HRMS_MODULE_CATALOG.md) · [Web app](08_WEB_APPLICATION.md)

**Status:** Implemented, not fully verified end-to-end (33 widget/unit test files incl. `live/` contract tests; no device testing observed). Platform: Android (declares `INTERNET`, `CAMERA`); iOS folder present but its permission strings were not verified.

## 1. Overview
`apps/mobile` — Flutter (Dart ≥ 3.7), Riverpod, go_router, Dio with persisted cookie jar, `flutter_secure_storage`, `camera`, `google_mlkit_face_detection`, `image_picker`, `file_picker`, `pdf`/`printing`/`share_plus`, `timezone`. API base URL from `--dart-define=API_BASE_URL` (+ `/v1`). Same REST API and permission model as web; the app is a second client, not a separate product.

## 2. Session lifecycle
Login/Register/Accept-invite return tokens; the access token + company id + company list are kept in **secure storage** (`hrms.session`), the refresh token only in the cookie jar (never read by app code). Startup: `/splash` → load session → `/auth/me` → role-based landing. 401 → single-flight refresh → retry; failed refresh clears the session and returns to login. Timeouts: connect 10 s, receive 30 s, send 60 s, file transfer 120 s; timeouts and offline are reported as distinct errors, **never auto-retried**; writes whose outcome is unknown reuse their idempotency key on the next tap (plain punch, face punch, leave submit). Public paths available regardless of login: reset-password, verify-email, accept-invite, onboarding (deep links).

## 3. Navigation
Bottom tabs: **Dashboard, Attendance, Leave, Profile**; "More" settings hub (unfiltered list): Employees, Onboarding, Team Attendance, Attendance Insights, Shift Rosters, Regularizations, Overtime, Leave Balances, Payroll, My Payslips; configuration groups (Organisation, Attendance & Time, Leave, Payroll, Policies, Administration) mirror web. The hub does **not** filter by permission; screens/API return 403 states. The Dashboard tab requires `DASHBOARD.COMPANY.VIEW` and otherwise shows "You do not have permission to view the company dashboard." — employees land elsewhere via `landingPathFor`.

## 4. Feature availability
| Area | Mobile capability |
|---|---|
| Auth | login, register company, forgot/reset, verify email, accept invite |
| Attendance (self) | plain punch in/out (server-timed; recorded as source `WEB`), **face punch**, month card, 14-day list, day detail |
| Attendance (HR/manager) | team attendance, insights (needs attention, trend, leave & absence, work hours, overtime, heatmap), rosters + roster calendar, periods (validate/finalize/reopen), policy assignments and resolution, regularization and overtime request screens, face-enrolment admin card |
| Face attendance | **mobile only**: five-pose enrolment with on-device pose guidance, liveness capture (N frames), punches (see Attendance §4.8) |
| Leave | apply, list, detail with approve/reject/cancel, balances, leave-year setting, resource screens for types/policies/rules/statutory minimums |
| Payroll | pay runs list/detail/employee view, statutory rates, salary components/structures, employee salary panel, bulk assign, my payslips, payslip **PDF generation and share on device** |
| Employees | list, profile sections, documents (upload/verify), actions (create/terminate/confirm/invite per `employee_forms.dart`) |
| Onboarding | HR case list/detail; candidate wizard via deep link; users and setup screens |
| Organisation | generic list/detail forms (`FormSpec`-driven) for all masters, versioned resource editors (`versions_section`) |

## 5. Device permissions and data handling
Camera (face enrolment/punch); file picker/image picker for documents. Face frames are held in memory and cleared after the attempt; ML Kit runs on-device only as a capture-quality/pose gate, never as liveness. No location permission, no GPS, no geofencing. **No push notifications, no local notifications, no offline mode or local database** (no such dependencies; every action needs connectivity). No biometric app-lock.

## 6. Differences from web
Mobile adds face attendance and PDF payslips; web adds bulk import, payslip print, onboarding document review UI depth and the analytics dashboards' fuller layout. Both use the same permission checks; neither filters navigation by permission. Mobile hub lists screens (e.g. Payroll) to everyone.

## 7. Limitations
No push/offline; plain punch bypasses face verification; recorded punch source is `WEB` even from mobile (Attendance A-3); iOS readiness unverified; company switching absent; the Android `CAMERA` permission is declared but runtime-denial paths are handled by `FaceCapturePermissionDenied`.

## 8. Evidence
`apps/mobile/lib/{main.dart,core,features}`, `pubspec.yaml`, `android/app/src/main/AndroidManifest.xml`, tests `apps/mobile/test/*`, CI mobile job (`.github/workflows/ci.yml`), `docs/operations/FACE_ATTENDANCE_*`.
