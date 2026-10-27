# Test execution plan

Status: **not approved**. No batch has been run. This revision is the safety-gate update from the plan review. It does not authorise execution.

`ISOLATION PROVED` is forbidden until every check in the isolation section has passed. If any target is missing, shared, or ambiguous, the programme is `BLOCKED` and that phrase is not printed.

## What approval would mean

A later human approval may name one batch. Approval of this file as a whole is not approval of batch 10, of failure injection, or of any case listed under individual approval. `BLOCKED`, `INCONCLUSIVE`, and `NOT_RUN` are never passes. A 200 response is not a pass. Expected results in the catalogues are not edited to match actual behaviour.

## Forbidden targets

These are the developer stack in `docker-compose.yml` and `apps/api/.env.example`. A disposable run must not use them.

| Resource | Forbidden |
|---|---|
| Postgres container | `hrms-postgres` |
| Database name | `hrms_dev`, `hrms_test`, `postgres`, `template0`, `template1` |
| Postgres host port | `5432`, `5433` |
| Redis container | `hrms-redis` |
| Redis | `127.0.0.1:6380` any index, `127.0.0.1:6379` any index, database index `0` on those ports |
| Object storage container | `hrms-minio`, `hrms-minio-init` |
| S3 port | `9000`, `9001` |
| Bucket | `hrms-documents` |
| API port already used by the developer server | `8000`, unless the PID check shows that process is not running |

Bypass switches that must be unset: `HRMS_TEST_ALLOW_SHARED_DEV`, `CI`. `apps/api/.env` must not be the settings fallback. Provider tokens (`MAILTRAP_API_TOKEN`, `HOSTINGER_MAIL_API_TOKEN`, `SMTP_PASSWORD`, `FACEPP_API_KEY`, `FACEPP_API_SECRET`) must be empty. `EMAIL_PROVIDER` must be `logging`. `FACE_VERIFICATION_PROVIDER` must be `disabled`. No payment gateway and no outbound webhook URL.

The repo guard `apps/api/tests/isolation_guard.py` (`HRMS_QA_STRICT=1`) is the checklist to satisfy. This plan does not run it.

## Isolation proof

Print one block. Every line must be present. Then, and only then, print `ISOLATION PROVED`.

1. **Database.** `DATABASE_URL`, `MIGRATIONS_DATABASE_URL`, and `HRMS_APP_DATABASE_URL` are set, host `127.0.0.1`, port not in the forbidden list, database name starts with `hrms_qa_` and is not in the forbidden list. `SELECT current_database()` on that URL returns that same name. The name is not the database of container `hrms-postgres`.
2. **Redis and broker.** `REDIS_URL`, `CELERY_BROKER_URL`, and `CELERY_RESULT_BACKEND` are set, host `127.0.0.1`, port not forbidden, index recorded. `PING` returns `PONG` from that URL only.
3. **Bucket.** `S3_ENDPOINT_URL` is `http://127.0.0.1:<port>` with a port not in `{9000,9001}`. Bucket name is `hrms-qa-<run-id>`, not `hrms-documents`. The endpoint's container, if any, is not `hrms-minio`.
4. **Email.** Effective provider is `logging`. A one-line capture probe stays on the host. No SMTP connection is opened.
5. **API process.** PID, command line, and the environment values above are printed. They match this block. The PID is not a server that was already running against `hrms_dev`.
6. **Celery worker.** PID and command line are printed. Broker and result backend match this block. The worker is not the developer's worker. If no worker is required for the batch, the line is `CELERY_WORKER=not-started` and batches that need a worker stay `BLOCKED`.
7. **Test runner.** Command, working directory, and PID. The working directory's `.env` is absent or empty. The command is not the full pytest suite, the web suite, or the mobile suite.
8. **Grants and schema.** The runner does not execute grant scripts, `ALTER`, `CREATE`, `DROP`, or migration commands against any database other than the named `hrms_qa_*` database. Migrations, if a later batch needs a schema, are a separate approved step against that name only. This review does not include that step.

If any line fails, print `ISOLATION BLOCKED` and the failing line. Do not print `ISOLATION PROVED`.

## Disk, memory, stop, cleanup

- Immediately before the isolation block, and again before every batch: free space on the filesystem that holds Docker data and on the filesystem that holds the repo. Both must be at least 3 GiB. If either is under 2 GiB, stop. Do not start the batch.
- During any batch that can run longer than two minutes (leave, payroll, onboarding, failure injection): sample free disk and `MemAvailable` every 60 seconds.
- Stop only the PIDs recorded in the isolation block when free disk falls below 2 GiB or `MemAvailable` falls below 256 MiB. Do not stop `hrms-postgres`, `hrms-redis`, or `hrms-minio`.
- On interrupt: leave evidence files in place. Mark the in-flight case `INCONCLUSIVE`. Do not mark it `PASS`. Drop a database, flush a Redis index, or delete a bucket only when its name is the one on the `ISOLATION PROVED` line for that run. Do not clean up resources that were not named there.

## Order

Tenant creation is the earliest mutation. Read-only cross-tenant checks come after both synthetic tenants exist and before leave, attendance, payroll, document, and failure-injection writes.

| Batch | Cases | Writes | Stop if | Later approval |
|---|---|---|---|---|
| 0 | PLT-001 | none | health body contains a person or company | Consider only after isolation is proved |
| Setup | Register tenant A (`MARKER-FOUNDRY`) and tenant B (`MARKER-NORTHWIND`) from `TEST_DATA_CATALOGUE.md`. No other employees yet | two companies | either marker appears in the other company's registration response | Consider with batch 0 |
| S | AUTH-004, AUTH-008, AUTH-009, SEC-001, SEC-002 **GET only** | none | a response contains the other tenant's marker, or a write is attempted | Consider after Setup |
| 1 | AUTH-001 to AUTH-003, AUTH-005 to AUTH-007, AUTH-010, ORG-001, ORG-003, JRN-001 | users, masters, calendar in A | a B marker appears | Consider after S |
| 2 | EMP-001, EMP-004, ATT-012, ORG-002, JRN-007's read of history only after EMP-005 is individually allowed | employees in A, one punch for ATT-012 | punch row owner is not the caller | Consider, except EMP-005 |
| 3 | LEV-C01 to LEV-C11, LEV-C13 to LEV-C18 | leave policy and applications in A | a ledger debit does not match the case amount | Consider. LEV-C12 is not in this batch |
| 4 | LEV-C19 to LEV-C36 except none removed; JRN-005 | approvals and cancels in A | two debits for one approval, or a B row changes | Consider |
| 5 | LEV-C37 to LEV-C39, LEV-C43 to LEV-C48 | adjustments and comp-off in A | ledger sum disagrees with the screen | Consider. LEV-C40, LEV-C41, LEV-C42 excluded |
| 6 | ATT-001 to ATT-004, ATT-006 to ATT-010, JRN-003, JRN-004 | punches and regularisation in A | a punch `employee_id` is not the caller | Consider. ATT-005 excluded |
| 7 | PAY-001, PAY-003 to PAY-008, PAY-010 to PAY-012, JRN-006 | pay runs in A, statutory off | the computer of the run can approve it, or net differs from the pre-written figure | Consider only when the paise sheet exists. PAY-002 and PAY-009 excluded until then |
| 8 | ONB-001 to ONB-003, ONB-005, DOC-001, DOC-003, JRN-002, JRN-008 | invites and one synthetic file | a message is not in the capture log | Consider. Failure injection excluded |
| 9 | SEC-002 PATCH, SEC-003, SEC-004, SEC-006, ATT-004, LEV-C23, JRN-009 | denied writes only, synthetic ids | any row in the other tenant changes. Stop the programme | Consider after S has passed in that same run |
| 10 | ATT-011 | one raw `UPDATE` | the database is not the proved `hrms_qa_*` name | **Not in group approval** |
| F | ONB-004, DOC-002, JRN-010, SEC-005, LEV-C40, LEV-C41 | failed dependencies, one worker, year-end and accrual jobs | a job or failed call touches tenant B or a forbidden resource | **Not in group approval** |

EMP-002 and EMP-003 may be added to batch 2 when that batch is approved. Their expected results stay as written: a second email or a second employee is a fail, not a reason to edit the case.

## Batch 10 — ATT-011, not to be run from a group approval

This review does not execute the statement.

| Item | Value |
|---|---|
| Case | ATT-011 only |
| Table | `public.punch` |
| Statement type | `UPDATE` of the existing `punch_time` column on one row, followed by `SELECT` of that column. `DELETE` is not part of this case |
| Role | the application runtime role already used by `DATABASE_URL`, not the migration owner, not a superuser |
| Expected protection | the runtime role cannot `UPDATE` or `DELETE` `punch`. A successful `UPDATE` is a **FAIL** and stays defect K-1. The expected result is not changed to "update allowed" |
| Preconditions | `ISOLATION PROVED` for this run, the punch row belongs to tenant A in that database, a before-image of `id` and `punch_time` is stored, and a human has approved ATT-011 by name |
| Evidence | role name, database name, SQLSTATE or the before/after `punch_time`, and the defect id if the write succeeds |
| Restore | only if the `UPDATE` succeeded, and only as a second approved `UPDATE` back to the stored before-image, after the evidence file is written. No `GRANT`, no `ALTER`, no other table |
| Prohibited | schema changes, grant changes, `hrms_dev`, `hrms_test`, container `hrms-postgres`, and any database not named on the `ISOLATION PROVED` line |

## Leave arithmetic that is safe to compare

These expectations match the implemented day-count and ledger rules. They are still `NOT_RUN`.

| Case | Opening | Charge | Ledger | End status | End balance |
|---|---|---|---|---|---|
| LEV-C04 | 10.00 | Tue–Thu, 3 working days | −3.00 | APPROVED (AUTO) | 7.00 |
| LEV-C05 | 10.00 | Fri–Mon, weekend not sandwiched | −2.00 | APPROVED | 8.00 |
| LEV-C06 | 10.00 | one weekly off between two working days | −3.00 | APPROVED | 7.00 |
| LEV-C07 | 10.00 | one half day | −0.50 | APPROVED | 9.50 |
| LEV-C08 | 10.00 | calendar unresolved | none | no row | 10.00 |
| LEV-C10 | 2.00 | exactly 2.00 | −2.00 | APPROVED | 0.00 |
| LEV-C11 | 2.00 | 3.00 requested, negative off | none | no row | 2.00 |
| LEV-C13 | 10.00 | 1.00, reserve off | none while SUBMITTED | SUBMITTED | 10.00 |
| LEV-C20 / JRN-005 | 10.00 | 1.00 after manager approval | −1.00 once | APPROVED | 9.00 |
| LEV-C25 | 10.00 | manager stage then HR | −1.00 only after HR | APPROVED | 9.00 |
| LEV-C26 | 10.00 | reject | none | REJECTED | 10.00 |
| LEV-C32 | 9.00 after a 1.00 debit | cancel before start | +1.00 | CANCELLED | 10.00 |
| LEV-C34 | 9.00 | HR cancel after start with reason | +1.00 | CANCELLED | 10.00 |
| LEV-C35 | 10.00 | second cancel | none | CANCELLED | 10.00 |
| LEV-C37 | ledger +10, −3, +1 | — | sum | — | 8.00 |

LEV-C05 is what the code does. BR-01 asks whether the business wanted both weekend days charged. The expected result stays 2.00 until a product decision replaces it. Do not treat 4.00 as the expected result in the meantime.

Holiday coverage is LEV-C06's single non-working day. A public-holiday span that is not that shape is not a separate case. Partial day is LEV-C07 only. Overlap is LEV-C15 and LEV-C16. Duplicate submit is LEV-C19. Concurrent approval is LEV-C28 and LEV-C29. Rejection is LEV-C26. Cancellation is LEV-C31 to LEV-C36.

## Cases held out of group approval

| Case | Why the expectation is not a single implemented rule |
|---|---|
| LEV-C12 | BR-02. The case allows two outcomes and says to mark `BLOCKED` if submit rejects the shortfall. It must not be scored `PASS` by picking the outcome that occurred |
| LEV-C40 | Year-end bulk ledger write. BR-10 |
| LEV-C41 | Accrual window. BR-10. Needs the disposable worker from the isolation block |
| LEV-C42 | Encashment eligibility is specified. Which of those rows payroll pays is BR-03. Do not assert a payroll amount from this case |
| ATT-005 | BR-04. Late status is not an implemented rule until the engine is shown to read the grace field. The case already says `BLOCKED` rather than a rewritten expectation |
| PAY-002, PAY-009 | Net paise are not fixed in the catalogue. Before either case runs, a sheet must record statutory-off or the engine's paise, and the run must match that sheet. Synthetic salary only: Basic 30000.00, account `999000111222` |
| EMP-005, EMP-006 | BR-07 and BR-13. Sign-in failure is required. The status column and rehire are not settled |
| ONB-005 | BR-08. A missing cancel route is `BLOCKED`, not a pass |
| ATT-011 | Raw `UPDATE`. Separate approval |
| ONB-004, DOC-002, JRN-010, SEC-005 | Failure injection and a worker write |

## Attendance and payroll assertions required when those batches run

Attendance cases in batch 6 must record `employee_id` equal to the caller, `punch_time` with timezone `Asia/Kolkata`, shift start and end, and one `attendance_day` for that local date. ATT-006 expects one attendance date (the shift start) and 480 worked minutes for 22:00–06:00. ATT-007 expects a null out time and no invented out punch.

Payroll cases in batch 7 must record the run status, the line amounts, the period start and end, `computed_by_user_id` different from `approved_by_user_id`, one line per employee after PAY-010, and the audit action name from the service (`PAYROLL_PAY_RUN_APPROVED` on approve). Salary data is the synthetic 30000.00 structure. No real bank is called on PAY-008.

## Evidence for every executed case

One file per case. Fields: case id, environment id (the `hrms_qa_*` name), git branch, git commit, dirty-tree note, start time with timezone, command or URL, opening state, steps actually performed, expected result copied from the catalogue before the run, actual result, status (`PASS`, `FAIL`, `BLOCKED`, `INCONCLUSIVE`, `NOT_RUN`), paths to response, log, and screenshot, defect id, cleanup outcome.

A harness crash, a timeout, or an isolation failure is `INCONCLUSIVE` or `BLOCKED`, never `PASS`. Do not edit the catalogue's expected result after seeing the actual result.

Pass count uses only `PASS`. The denominator for a pass rate, if one is printed, is `PASS + FAIL`. The other three statuses are listed separately.

## UI, mobile, and external effects

Playwright is not added. If no browser runner is already installed, every case whose type is `UI` is `BLOCKED` with that reason. API cases in the same batch may still run. Mobile cases stay `BLOCKED` until `flutter` is on `PATH`. Email stays on the logging provider. Payments and webhooks stay disabled.

## Out of scope

Performance sweeps, the full regression suite, face recognition, production data, defect fixes, grant changes, and schema changes.
