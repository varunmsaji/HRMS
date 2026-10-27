# SEC-R02 and SEC-R04–SEC-R14

Environment: `hrms_qa_20261026`. Timezone: Asia/Kolkata. Observed at 2026-10-26T18:37:01+05:30.

The API role is `hrms_qa` with row-level security bypass. This run does not test PostgreSQL RLS.

Two `POST /v1/auth/login` calls obtained bearer tokens. They are not scored cases. `session` went from 4 to 6. Employee, email log, company, user, child-table counts, and the QA bucket object count stayed unchanged. The bucket stayed at 0 objects.

Each case below passed in both tenant directions. A foreign header or the other employee id returned 404 `NOT_FOUND` with no foreign marker, email, company id, or employee id.

| Case | Status |
| --- | --- |
| SEC-R02 | PASS |
| SEC-R04 | PASS |
| SEC-R05 | PASS |
| SEC-R06 | PASS |
| SEC-R07 | PASS |
| SEC-R08 | PASS |
| SEC-R09 | PASS |
| SEC-R10 | PASS |
| SEC-R11 | PASS |
| SEC-R12 | PASS |
| SEC-R13 | PASS |
| SEC-R14 | PASS |
| SEC-R01 | NOT_RUN |
| SEC-R03 | NOT_RUN |

SEC-R06 through SEC-R14 own lists were empty because those child rows do not exist. The cross-id 404 shows the other employee id is refused. It does not show how a child row would be filtered.

Per-response files are `SEC-Rxx-MARKER-*-own.json`, `SEC-Rxx-MARKER-*-foreign-header.json`, and `SEC-Rxx-MARKER-*-cross-id.json` in this directory. Counts are in `database-after.json`.
