# Attendance geofencing — administration, privacy, security and rollout

API contract: [`../api/GEOFENCING.md`](../api/GEOFENCING.md). Code: `apps/api/src/hrms/modules/attendance/geofence*.py`, migration `20261030090000`, web page `/app/attendance-geofences`, mobile `lib/features/attendance/{domain/punch_location,data/geolocator_gateway,presentation/punch_location_flow}.dart`.

## 1. Design in one paragraph
A workplace geofence is an existing **Branch** (latitude/longitude/radius). A new, versioned **attendance-policy** setting (`DISABLED` / `OPTIONAL` / `REQUIRED`) decides whether an employee's own *self-service* punches (plain and face) are location-checked. The phone sends one fresh foreground fix with the punch; **the server decides** using trusted data (the employee's assignment branch, administrator-granted extra workplaces, the published policy thresholds). Every evaluated location is recorded as a coordinate-light `geofence_attempt`; a refused punch creates no attendance. Existing attendance behaviour is unchanged until a policy version with `OPTIONAL` or `REQUIRED` is published and assigned.

## 2. Defaults
* **Existing tenants / existing policy versions:** `DISABLED` (column default, applied by the migration). Nothing changes.
* **New companies:** also `DISABLED` — the policy form defaults to it and the API default is `DISABLED`. An administrator must publish a new policy version to turn it on. Nothing enables it automatically.

## 3. Administering it
1. **Create the workplace**: Branches → set latitude, longitude and radius (metres). Use *Workplace Geofences* (`/app/attendance-geofences`) to see every branch, whether it is usable, how many employees are assigned, and open the coordinates in OpenStreetMap to check them. *No map component is bundled* (none exists in the repo and no provider/paid dependency was introduced): coordinates are typed in and verified through the external map link; there is no draggable map or address search. This is a known limitation.
2. **Assign employees**: nothing to do — each employee's assignment branch is used. For people who work across sites, add *extra workplaces* on the same page (audited; employees cannot choose a workplace).
3. **Set the policy**: Attendance Policies → new version → *Location check*. Start with **Optional**, review *Location attempts* for a few weeks, then move to **Required** in a new published version. Thresholds are bounded (accuracy 5–500 m, age 5–300 s) and cannot be loosened by the client.
4. **Deactivating a workplace**: refused while employees are assigned to the branch or authorised for it (`409`), so no one is silently stranded. Clearing a branch's coordinates while a `REQUIRED` policy applies leaves its employees with `NO_APPLICABLE_WORKPLACE` (fail-closed, visible in the attempts list) — check the *Assigned* count first.
5. **Review & exceptions**: *Location attempts* (permission `ATTENDANCE.VIEW_ALL`, data-scoped) lists rejected attempts with reason, distance/radius and accuracy. A rejected attempt is never turned into attendance silently; correct legitimate cases with the existing regularization workflow or an HR on-behalf punch (both require a reason and are audited).

## 4. Privacy and data minimisation
| Item | Handling |
|---|---|
| When location is read | Only when the employee taps Punch in/out and only if their policy is `OPTIONAL`/`REQUIRED`. One-shot foreground fix; no background location permission is declared; no tracking, no stream, no cached "last known" position. |
| What is stored | Per evaluated punch: outcome, nearest workplace id, distance, radius, accuracy, the device's capture time, **coordinates rounded to 4 decimals (~11 m)**, client error code, direction/source/mode. Nothing is stored when the policy is `DISABLED`. |
| Why | To explain a rejection or resolve a dispute without keeping a precise track. |
| What is not stored | The raw fix, device identifiers, any movement history. |
| Retention | `GEOFENCE_ATTEMPT_RETENTION_DAYS` (default 90). Purge with `GeofenceService.purge_expired_attempts(company_id, days)` per company — **schedule it (e.g. daily Celery beat) as part of rollout; it is not wired to a schedule yet.** The punch and its audit event are unaffected. Set the period with HR/legal for your jurisdiction; this document does not give legal advice. |
| Logs / errors / URLs | Coordinates never appear in application logs (the operation logger uses an allow-list), error messages, audit events (`PUNCH_REJECTED_GEOFENCE` carries outcome and measurements only), notifications, or URLs. The employee sees distance/radius/accuracy, never coordinates. |
| Who can see coordinates | `ATTENDANCE.VIEW_ALL` holders, within their data scope. |
| Isolation | `ENABLE`+`FORCE ROW LEVEL SECURITY` with the standard `tenant_isolation` policy (USING + WITH CHECK) on both new tables; composite `(company_id, …)` foreign keys to `employee` and `branch` make cross-company rows impossible even for the owner role; every query also filters `company_id` explicitly. |
| Offline | There is no offline punch queue (see `../api/OFFLINE_ATTENDANCE_DESIGN.md`); a location is never queued or replayed. |

## 5. Security — what GPS does and does not prove
**A device-reported location is a claim, not proof of presence.** A rooted/jailbroken phone, a developer mock-location app, an emulator or a modified client can report any position, and the server has no independent view of the handset. A passing check means: "the device said it was inside an approved workplace, with a fresh timestamp and acceptable stated accuracy".

Signals used and their limits:
* Server-side: range/finite validation, freshness against the **server** clock (30 s future skew tolerated), policy-bounded accuracy, authenticated employee/company, server-resolved workplaces, idempotency, rate limiting. None detects spoofing.
* Client-side, convenience only: the app refuses a fix the Android platform flags as `isMocked`. A modified app can skip this, the server does not rely on it, and it is not sent. No other anti-spoofing assumption (e.g. SSID, IP geolocation, attestation) is made; none was found in the repo to reuse. Play Integrity / App Attest would be the next layer if the risk warrants it.
* Corroboration that already exists: face verification (liveness + match) for enrolled employees; `OPTIONAL` mode and the attempts list let HR look for implausible patterns before enforcing.

Accuracy: a point inside the radius with acceptable stated accuracy is accepted even if its error circle crosses the edge; a point just outside whose error circle reaches the fence is refused as `OUTSIDE_GEOFENCE_UNCERTAIN`. The fence is never silently expanded. Indoors, urban canyons and low-power modes can produce poor fixes — set the accuracy ceiling and radius with that in mind (very small radii will cause false rejections).

## 6. Rollout and feature-flag strategy
There is no separate flag: the **policy version is the flag**, per tenant, reversible by publishing a version with `DISABLED`.
1. Deploy the backend + migration (additive; all tenants `DISABLED`; behaviour identical). Deploy the web app. Ship the mobile build (it asks the server first and sends nothing when `DISABLED`; older app builds keep working for `DISABLED` and `OPTIONAL`).
2. Configure branch coordinates/radius; add extra workplaces where needed; verify with the OpenStreetMap links.
3. Pilot tenant/group: publish `OPTIONAL`. Watch *Location attempts* (share of `INSIDE`, poor accuracy, `NO_APPLICABLE_WORKPLACE`).
4. Only when the pilot is clean **and the app version in the field supports location**, publish `REQUIRED`. Older app builds cannot send a location, so under `REQUIRED` their punches are refused with `PUNCH_LOCATION_REQUIRED`; the web has no self-punch location capture either (see limitations).
5. Schedule the retention purge before enabling anywhere.
Rollback: publish a policy version with `DISABLED` (effective immediately for new punches); data already recorded is retained until purged.

## 7. Known limitations
* GPS spoofing cannot be ruled out (§5).
* No map picker/address search/radius drawing; coordinates are typed in and previewed via an external map link.
* The browser web app has no self-service punch location capture; under `REQUIRED`, a plain web self-punch is refused with `PUNCH_LOCATION_REQUIRED`. Use the mobile app, or HR on-behalf punches.
* The retention purge is not scheduled by this change.
* The policy is looked up by the UTC calendar date of the punch (the same documented approximation the punch path already uses before shift resolution, WD-30), so a version that becomes effective in the few hours between UTC and local midnight may apply slightly early/late.
* A client clock far from real time can make `captured_at` look stale/future (a 30 s future skew is tolerated). The app uses the platform's fix timestamp, not the wall clock.
* Geofence thresholds cannot differ per workplace — they are per policy version; the radius is per branch.
* Clearing a branch's coordinates is not blocked even if a `REQUIRED` policy depends on it (fail-closed instead).
* The mobile text-scale layout of the existing punch screen overflows at 2× text on a 360 px phone (pre-existing, unrelated); the new dialogs do not.

## 8. Manual acceptance checklist (not yet performed — see report)
1. **Create an office geofence**: Branches → create/edit "Test Office" with coordinates and radius 100 m → open *Workplace Geofences* → it shows Active, the coordinates link opens the right place on OpenStreetMap, Assigned count matches.
2. **Assign the policy**: Attendance Policies → new version → Location check **Required**, accuracy 50 m, age 30 s → publish → assign to the test employee/company (Policy Assignments). Confirm *Policy Resolution* shows it.
3. **Inside**: on a phone, as the test employee, tap *Punch in* inside the radius with Location on → permission prompt appears only now → success; the punch shows in the day; *Location attempts* (with *Rejected only* off) shows `Inside the workplace`.
4. **Outside**: move >radius+accuracy away (or use a mock for a *test build only*) → *Punch out* → "Punch not recorded" dialog with the server message; no punch added; attempt listed as Rejected / Outside the workplace.
5. **Poor accuracy / permissions**: Location services off → dialog with *Open settings*; deny permission → explanation; "Don't ask again" → *Open settings* opens app settings; indoors with weak GPS → accuracy guidance, *Try again* takes a new fix. Airplane mode → network error, key reused on retry (no double punch).
6. **Check-out** works the same way; face-enrolled employee: face punch with location inside succeeds, outside is refused **before** the camera challenge is consumed.
7. **Exception**: as the employee, submit a regularization for the refused punch; as HR approve with a reason; confirm the audit trail and that the rejected attempt still shows as rejected.
8. **Disabled tenant**: with a policy version at `DISABLED` (or a tenant that never configured it), punch in/out with Location off → works, no permission prompt, no attempts recorded.
9. **Extra workplace**: authorise the employee for a second office → punch inside it works; remove the authorisation → refused; trying to deactivate that branch while authorised → `409`.
10. **Cross-company**: with two tenants, confirm neither sees the other's attempts/workplaces/authorisations.
