# Self-punch behaviour: before and after the T1-03 refactor

Written 2026-10-30 **before** the code moved. Source of the "before" column: `AttendanceSelfScreen._punch/_punchOnce` and `FacePunchCard._punch` at the working tree before T1-03. Every row is pinned by a test that was green against the old code and is green, unchanged, against the new `PunchController`.

Scope: client behaviour only. No backend, API or schema change. Server rules the client relies on (API matrix §5.1): directions `IN`/`OUT`; server time; no alternation check; idempotency replay on the same key + employee + direction; a key reused for another employee is refused; plain punch refused with 403 `FACE_VERIFICATION_REQUIRED` for an enrolled face; day calculation after a punch is best-effort.

| # | Behaviour (unchanged) | Pinned by |
|---|---|---|
| 1 | **Duplicate taps.** While a plain punch is in flight (including its location step) every further plain tap, in either direction, is ignored. Exactly one request is sent. Buttons are disabled meanwhile. | `punch_characterization_test` "duplicate taps…", "other direction while one is in flight…"; `punch_location_flow_test` "buttons are disabled while the location capture is in flight…" |
| 2 | **Face duplicate taps.** One face attempt at a time; both face buttons disabled while any phase is active. | `face_punch_card_test` "disables both buttons and ignores taps while verifying" |
| 3 | **Plain and face guards are independent** (they were two separate widgets' fields). Kept separate in the controller. | `punch_controller_test` "separate guards" |
| 4 | **No response (`ApiError.status == 0`)** keeps the idempotency key. A retry of the **same direction** reuses it; the retry's success clears it; the next punch has a new key. | characterization "network failure: same direction reuses…"; `punch_location_flow_test` "network failure keeps the idempotency key…" |
| 5 | **Different direction** after an unknown outcome gets a new key and the old key is forgotten (a later IN does not resurrect it). A second unknown outcome in the other direction replaces the kept key. | characterization "…the OTHER direction…", "a second unknown outcome…" |
| 6 | **Any real answer** (HTTP error, validation, 500, 401, geofence refusal, non-API exception) clears the kept key; the next attempt uses a new key. | characterization "server error after a network failure…", "session expiry (401)…", "non-API error…"; `punch_location_flow_test` "a refused location is a real answer…" |
| 7 | **Face unknown outcome** (`facePunchOutcomeUnknown`) keeps the key; the retry gets a **new challenge and capture** but the same key; switching direction uses a new key; a liveness server error is a real answer. | `face_punch_card_test` |
| 8 | **Session expiry.** A 401 that survives the client's single refresh arrives as an `ApiError`; the server message is shown, no key kept, no crash. The auth controller then sends the app to login. | characterization "session expiry (401)…" |
| 9 | **Screen leaves mid-request** (logout/session loss/navigation): the request completes quietly; nothing is shown; the kept key dies with the screen state. | characterization "leaving the screen mid-request…" |
| 10 | **Server-confirmed state.** "Punched in." / "Punched out." is shown only after the server accepted the punch, then the day list is reloaded from the server. A failed punch never claims success and does not reload. | characterization "server-confirmed…", "a failed punch does not claim success…" |
| 11 | **Face required.** `FACE_VERIFICATION_REQUIRED` or an enrolled/`face_verification_required` status hides the plain buttons; no fallback. | `attendance_self_mandatory_face_test` |
| 12 | **Geofence.** DISABLED asks nothing; OPTIONAL reports the failure and punches; REQUIRED retries/cancels before sending; policy-lookup failure punches without location; a server geofence refusal is a real answer with Try again (new key); face punch takes its fix after the capture. | `punch_location_flow_test` (13 cases), `face_punch_card_test` |
| 13 | Face frames cleared in `finally`; camera and challenge order unchanged. | `face_punch_card_test` "drops the face frames…" |

## What moved

`_punching`, `_faceRequired`, `_unconfirmedPunch`, `_punch`, `_punchOnce` (screen) and `_phase`, `_unconfirmedPunch`, `_punch` (card) became `PunchController` (`lib/features/attendance/state/punch_controller.dart`). Dialogs, the camera route and snackbars stay in the widgets, behind `PunchUi` (`context_punch_ui.dart`), so the controller holds no `BuildContext`. The provider is **autoDispose**: when the last screen using it goes, the pending keys go with it, as the old `State` fields did.

## Deliberate differences (all strictly safer, none visible in the old tests)

| # | Difference | Why |
|---|---|---|
| D1 | After a successful punch the refresh callback (`_load` / `onPunched`) runs only while the screen is still mounted. Before, it ran unconditionally and could call `setState` on a disposed screen. | Removes a latent "setState after dispose" on logout/session loss mid-success. |
| D2 | State writes after the controller is disposed are skipped. Before, there was no shared object to dispose. | Required by the move; covered by "disposed mid-request" test. |
| D3 | Home and Attendance share the in-flight guard and the idempotency record (one provider). Before, only one screen punched. | The point of the refactor: no double submit from two screens (`punch_controller_test` rows 1–2). |
| D4 | The face card now publishes `faceVerificationRequired` to the controller itself; the `onStatus` callback is still called. | The Attendance screen and Home read it from one place. |

Tests were not edited to make the refactor pass; the characterization tests were not changed to fit the refactor (the only later edit removed an unused helper parameter).
