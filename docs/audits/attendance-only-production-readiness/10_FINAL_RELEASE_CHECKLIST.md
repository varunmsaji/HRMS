# Final checklist — attendance-only release

Use this list to approve the release. An item is done only when the evidence exists, not when the screen exists.

## Package

- [ ] The artifact is a reviewed commit that contains the working-tree tenancy middleware, `attendance/overview.py`, the dashboard client, the CSP middleware and layout change, and migration `20261031090000`.
- [ ] `git show <release>:apps/api/src/hrms/core/tenancy/middleware.py` does not call `set_tenant` from `X-Company-Id`.
- [ ] `origin/main` at `024ce3f` and local `f6340eb` are not what production runs.

## Database

- [ ] `alembic current` on the release database is `20261031090000`.
- [ ] The migration’s cross-company shift pre-check passed, or the offending rows were corrected first.
- [ ] The API connects as `hrms_app` (`NOBYPASSRLS`), not as the schema owner.
- [ ] A restore into a new database name has been completed and the time written into `docs/deployment/HRMS_BACKUP_AND_DISASTER_RECOVERY.md`.
- [ ] At least one backup copy is not on the same VPS disk.

## Security configuration

- [ ] `ENVIRONMENT=production`.
- [ ] JWT secrets and `PII_MASTER_KEY` are not the example values.
- [ ] `TRUSTED_PROXY_HOSTS` is the Nginx hop.
- [ ] CORS origin is the web origin. Credentials are on. The list is not `*`.
- [ ] OpenAPI `/docs` is disabled (true when environment is not development).
- [ ] Face provider is disabled.
- [ ] No published attendance policy has `geofence_mode=REQUIRED` until web can send a location or only the mobile app is used to punch.
- [ ] No published regularization policy offers `EARLY_DEPARTURE_APPROVAL` unless the check constraints were migrated to allow it.
- [ ] No published policy uses punch rounding other than `NONE`, or ATT-CALC-001 is fixed.
- [ ] No published policy uses `AUTO` regularization approval unless self-approval is acceptable.
- [ ] WFH / WRONG_STATUS / FULL_DAY / EXCESS_BREAK are not offered, or ATT-CALC-004 is fixed.

## Tests that must be green on the release commit

- [ ] `pytest tests/integration tests/security` against an isolated database (CI or a disposable stack), not `hrms_dev`.
- [ ] Attendance RLS runtime-role test, tenant-resolution runtime-role test, company overview test, shift-tenant FK test.
- [ ] Web `tsc --noEmit`.
- [ ] Web Vitest.
- [ ] `flutter analyze` and `flutter test`.
- [ ] CSP browser suite against the **Nginx** URL, not only `next start` on localhost.

## Smoke on the release environment

- [ ] Employee logs in on the web.
- [ ] Employee checks in. The UI shows the time only after the API returns the punch.
- [ ] A second immediate check-in does not create a second logical in-punch (or the product’s documented collapse window is accepted and verified).
- [ ] Employee checks out and sees a worked duration that matches `attendance_day.worked_minutes`.
- [ ] History for that date shows the same status.
- [ ] Admin opens `/app/dashboard` and the present count includes that employee.
- [ ] An employee whose shift has not started is not counted absent.
- [ ] An employee on an approved leave day is on leave, not absent.
- [ ] A pending leave is not counted as on leave.
- [ ] A weekly off is not counted absent.
- [ ] Admin approves a missing-punch regularization. The day changes. A rejected request does not.
- [ ] Employee A cannot read employee B’s day. A token for company A cannot read company B (RLS test or a scripted probe on disposable tenants).
- [ ] Beat is a single replica and the heartbeat is fresh.
- [ ] `/health/ready` is 200.

## Mobile, only if phones are in this release

- [ ] Release APK is signed with the upload key, not the debug key.
- [ ] `API_BASE_URL` is the HTTPS production API.
- [ ] On a device: check in, kill the app, reopen, see the same punch, check out.
- [ ] The web dashboard shows that punch.
- [ ] Airplane mode during check-in shows a failure and does not show a success.

## Explicitly not required

- [ ] Pay run, payslip, tax, PF, ESI.
- [ ] iOS App Store listing.
- [ ] Face enrollment.
- [ ] Offline punch queue.
- [ ] A 5,000-employee load test (do not advertise that scale).

## Sign-off

| Role | Name | Date | Decision |
|---|---|---|---|
| Engineering | | | Deploy / hold |
| Security | | | Tenant fix is in the artifact |
| Operations | | | Restore drill recorded |

Release name: attendance-only. Payroll remains in the binary and out of the promise.
