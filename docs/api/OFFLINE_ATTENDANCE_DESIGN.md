# Offline attendance - decision record and design (not implemented)

**Status: online-only is the current, intentional behaviour. Nothing here is built.** This page records why, what the mobile client must do today, and the design that would be needed if the product owner decides offline capture is required. Implementing any of it needs the decisions in §4.

## 1. Established behaviour (evidence)
* `DEC-TZ-01` (docs/audits/ATTENDANCE_TIMEZONE_CLIENT_APPROVAL.md:519, implemented per ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md:88): the **server clock is the official attendance clock; device time is never trusted for a normal punch.** `PunchCreateSelf` has no time field, `POST /v1/attendance/punches/me` stamps receipt time, and face punches do the same.
* The only client-supplied instants the API accepts are (a) on-behalf punches by HR (`ATTENDANCE.PUNCH_ON_BEHALF`, never in the future, not before employment start) and (b) regularization `requested_time`, which becomes a punch only after approval.
* Therefore a punch queued on a phone and replayed later would be recorded at *replay* time. That is correct for an online-only product and wrong for an offline one - it must never be presented to the user as "punch saved".

## 2. What the mobile client should do now (online-only)
1. Disable the punch buttons when there is no connectivity (or show "needs a connection"); do not queue punches.
2. Treat a timeout on `POST /attendance/punches/me` as **unknown outcome**: re-read `GET /attendance/punches?employee_id=<me>&date_from=<today>&date_to=<today>` before offering a retry, and send a random `idempotency_key` with the first attempt so an automatic retry with the same key returns the original punch instead of creating a second one (same direction only).
3. A missed punch is corrected with `POST /regularizations` (`MISSING_PUNCH`/`WRONG_PUNCH`, client-supplied `requested_time` with offset, approval-gated).
4. Surface `source`: self punches are labelled `WEB` regardless of client (see H-5 decision below); do not use it to detect the mobile app.

## 3. Design if offline capture is required
Goal: let an employee record "I arrived at 09:02" without connectivity, without letting a client forge, replay or back-date attendance.

| Concern | Proposed control |
|---|---|
| Event identity & replay | Client generates a UUIDv4 `event_id` per tap; server stores it with a unique index `(company_id, employee_id, event_id)`; replays return the stored result (same mechanism as the face-punch key, scoped per employee). |
| Two timestamps | Store `device_time` (as claimed) and `received_at` (server). The authoritative `punch_time` remains server-derived: `punch_time = clamp(device_time, received_at - max_offline_window, received_at)` only if the integrity checks below pass; otherwise `received_at`. |
| Clock manipulation | Client also sends a monotonic elapsed value since a server-anchored sync point (`server_time` from the last response + `SystemClock.elapsedRealtime`/`ProcessInfo.systemUptime` delta). Server compares claimed `device_time` with `anchor + elapsed`; skew beyond a threshold (e.g. 120 s) downgrades the event to `received_at` and flags it `CLOCK_SKEW`. Reboots invalidate the anchor (flag `UNANCHORED`). |
| Window & policy | Company policy `offline_punch_max_age` (e.g. 12 h) and per-direction rules; events older than the window are rejected with a stable code and routed to regularization. Never accept events dated before employment start or after receipt. |
| Device identity & trust | Bind events to a registered device (`device_id` + public key generated in Keystore/Secure Enclave; each event signed). Server verifies signature and that the device belongs to the employee. Attestation (Play Integrity / App Attest) is recommended before trusting `device_time` at all - without it, offline events must be flagged `UNATTESTED` and approval-gated. |
| Face punch | Offline face verification is not possible with the current server-side liveness + provider design; offline face punches are out of scope. |
| Sync protocol | `POST /v1/attendance/punches/sync` accepting an ordered batch (≤50) of signed events; per-event results (`ACCEPTED`, `REPLAYED`, `FLAGGED`, `REJECTED` + code); partial success; idempotent as a whole through the per-event ids; rate-limited. |
| Audit & correction | Persist `source=MOBILE_OFFLINE`, `device_time`, `received_at`, flags, device id; HR sees flagged events in a review queue; correction stays via the existing regularization workflow. Attendance calculation treats flagged events per policy (accept / require approval). |
| Privacy/security | No location or biometric data in the event; payload signed; tokens are not stored with queued events (use the session at sync time). |

## 4. Decisions required (product / security owner)
1. Is offline capture a requirement for the current mobile release? (If no, stop here.)
2. Maximum offline age and whether late events need approval.
3. Acceptable trust model: attested devices only, or flagged-and-reviewed events from any device?
4. Is a distinct `MOBILE` / `MOBILE_OFFLINE` punch source wanted for reporting? (`MOBILE` is already allowed by the `punch_source_check` constraint; no code sets it.) A client-declared client type could only ever be an *unauthenticated hint*; a trustworthy value needs app attestation or per-app client credentials.
5. Retention of device keys/events and employee notice (privacy review).
