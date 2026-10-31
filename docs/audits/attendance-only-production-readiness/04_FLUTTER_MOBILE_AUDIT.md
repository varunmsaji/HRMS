# Flutter mobile audit

Evidence: source under `apps/mobile`, `flutter analyze` (no issues), and `flutter test` (557 passed, 1 skipped). No Android device, emulator, or release APK was installed. No request was sent to a running API.

## 7.1 Recording attendance

The employee punch screen is `lib/features/attendance/presentation/attendance_self_screen.dart`.

`POST /attendance/punches/me` body (`attendance_repository.dart` 376–385):

- `direction`: `IN` or `OUT`
- `idempotency_key`: a new key, or the in-memory key kept after a response-less failure
- `location` or `location_error` when applicable

No `punch_time`, `source`, or `employee_id`. That matches `PunchCreateSelf` (`extra="forbid"`) in `apps/api/src/hrms/modules/attendance/schemas.py` 1339–1381. The server stamps the instant.

Location (`punch_location_flow.dart`, `geolocator_gateway.dart`):

- Policy from `GET /attendance/geofence-policy/me`.
- `DISABLED`: no GPS.
- `OPTIONAL`: punch proceeds if capture fails.
- `REQUIRED`: the UI retries until a usable fix exists or the user cancels. A failed policy fetch still attempts the punch without a location, and the server answers `PUNCH_LOCATION_REQUIRED` when the mode is required.
- `getCurrentPosition` only. No last-known fix. Timeout 15 seconds. Accuracy `best`.

Duplicate taps: plain buttons are disabled while `_punching` is true, including during GPS (`attendance_self_screen.dart` 75–76, 181–189). Face punch has a separate phase flag, so a plain punch and a face punch can overlap. Plain buttons stay visible until face status loads; a 403 `FACE_VERIFICATION_REQUIRED` then hides them.

Idempotency survives only in memory, and only when `ApiError.status == 0` (no HTTP response). A 502/503 on a plain punch gets a new key. Killing the app drops the key. There is no local queue. A failed punch does not paint a success state; geofence failures open “Punch not recorded” (`punch_location_flow.dart` 89–108).

Session: access token in `FlutterSecureStorage`. Refresh token is the persisted `hrms_refresh` cookie. Startup calls `/auth/me`. A network failure on that call can leave `user == null` while still authenticated, and the attendance tab then shows “No employee record” (`attendance_self_screen.dart` 155–161). Logout posts `/auth/logout` and clears secure storage.

### ATT-MOB-002 — No durable idempotency across process death

- Severity: Medium. Platform: Flutter. Feature: check-in on a flaky network.
- Paths: `attendance_self_screen.dart` 71–73 and 95–119; repository punch body.
- Impact: the UI does not claim success when the network fails. A retry after the process is killed can insert a second punch if the first request actually landed.
- Correction: persist the key until the server returns a definitive punch id, matching the server’s idempotency index.
- Blocks deployment: no. It is the main mobile duplicate risk.

## 7.2 History and regularization

| Surface | Status |
|---|---|
| Last 14 company-zone business days | Implemented. `GET /attendance/days`, paged. |
| Month grid | Client counts of returned statuses. Not the period-summary API. |
| Day detail | Schedule, actuals, breaks, overtime fractions, leave overlay. Clocks use `day.timezone`. |
| Punch log | `listPunches` has no UI caller. Days show first in / last out. |
| Team day | Implemented, including on-behalf time in the company zone. |
| Regularization | Types in `request_resources.dart` include `EARLY_DEPARTURE_APPROVAL`, which the database cannot store (ATT-REG-001). |
| Dashboard | Company summary plus quick actions. Employees without `DASHBOARD.COMPANY.VIEW` land on `/app/me`, not the punch tab. |

`AttendanceDay.fromJson` keeps unknown fields in `raw`. A bad cast on one row fails the whole list.

## 7.3 API client

```dart
const _apiBaseUrl = String.fromEnvironment(
  'API_BASE_URL',
  defaultValue: 'http://localhost:8000',
);
```

`api_client.dart` 22–33. Base path is `$base/v1`. Timeouts: connect 10s, receive 30s, send 60s. No automatic retry. Headers: `Authorization`, `X-Company-Id`, `X-Request-Id`. One 401 triggers a single refresh. A rejected refresh clears the session for the whole app, including attendance. Timeouts are not retried.

There is no flavor and no `.env`. A release built without `--dart-define=API_BASE_URL=https://…` targets localhost.

## 7.4 Android release

`android/app/build.gradle.kts`:

- `applicationId`: `com.staffspectrum.hrms_mobile` (line 24). Manifest label is Krewoxa.
- `version` in `pubspec.yaml`: `0.1.0` with no `+build` number.
- Release `signingConfig` is the debug keystore (lines 33–38). Comment: “Signing with the debug keys for now”.
- No minify, no product flavors, no upload keystore in `android/`.

`AndroidManifest.xml`: `INTERNET`, `CAMERA`, `ACCESS_FINE_LOCATION`, `ACCESS_COARSE_LOCATION`. No background location. `allowBackup="false"`.

`android/app/src/debug/AndroidManifest.xml` sets `usesCleartextTraffic="true"`. The main and release manifests do not. An HTTP production URL fails on a release build. The default localhost URL is HTTP.

### ATT-MOB-001 — Android cannot be shipped as a production build

- Severity: Critical for the mobile half of this release.
- Paths: `android/app/build.gradle.kts` 33–38; `api_client.dart` 22–25; debug manifest cleartext flag.
- Reproduction: `flutter build apk --release` without a dart-define. The binary is debug-signed and calls `http://localhost:8000`, which release networking will not allow in cleartext.
- Impact: Play will reject the signature. A sideloaded release build will not reach the API. A debug build can, which is not a production configuration.
- Correction: a release keystore outside git, `versionCode`, and `--dart-define=API_BASE_URL=https://<production-api>` (or a flavor that bakes it). Confirm the host is HTTPS so cleartext stays disabled.
- Blocks deployment: yes for Flutter distribution. Web and API can ship without this binary.

iOS: project exists (`ios/Runner`). Location-when-in-use and camera usage strings are present. `CODE_SIGN_STYLE = Automatic`, no development team. Not an App Store configuration. Treat iOS as deferred unless this release explicitly includes it.

## 7.5 Time and offline

`lib/core/time.dart` loads the IANA database. `businessToday` uses the company zone. Unknown zone names fall back to UTC. Missing company zone falls back to `Asia/Kolkata`. Self punch does not send a client timestamp. Face-enrollment expiry is shown in device local time (`face_punch_card.dart` 249–252), unlike the rest of attendance.

Offline attendance is not implemented. The UI reports the failure. It does not show a punch as recorded when the request did not return a punch.

## 7.6 Payroll inside the same binary

Pay runs, salary structures, and payslips are routes (`app_router.dart`). More lists them without a permission filter (`settings_hub_screen.dart`). A payroll load error is caught on the pay-runs screen and does not remove the attendance tab. A payroll 401 that fails refresh logs the user out of attendance as well, because the session is shared. Payroll code is not compiled out.

## 7.7 Tests and logging

Executed this audit:

- `flutter analyze --no-fatal-infos`: no issues (2.4s).
- `flutter test --reporter compact`: all tests passed, 557 passed, 1 skipped.

Attendance-related test files include `attendance_screens_test.dart`, `attendance_self_mandatory_face_test.dart`, `punch_location_flow_test.dart`, `location_capture_test.dart`, `punch_idempotency_test.dart`, `punch_location_payload_test.dart`, face punch tests, `request_screens_test.dart`, `time_test.dart`, and `contract_fixtures_test.dart`. `live/live_contract_test.dart` refuses the default port-8000 API and was not pointed at a server.

No Dio log interceptor. Tokens are not printed. `debugPrint` of uncaught errors is debug-only (`main.dart` 53–56). Release `FlutterError.onError` records the error and does not present it.

## Mobile release verdict

The attendance workflow in code is fit to talk to the current API. The release package is not. Do not distribute an APK until ATT-MOB-001 is fixed and one physical-device pass records a check-in against the production API URL.
