# Defect register

No new defect was executed in this design phase. The rows below are existing findings that the catalogue must keep visible. Severity is the earlier review's, not a fresh reproduction.

| ID | Severity | Status | Summary | Evidence | Catalogue |
|---|---|---|---|---|---|
| K-1 / ATT-15 | Critical | Open | The runtime database role can UPDATE and DELETE punch rows. Decision D11 deferred the fix. | `docs/testing/qa_live_2026-10-25/register.csv` row ATT-15, status FAIL | ATT-011. Expected result stays "update is denied". A successful update is a fail |
| DEF-02 | High | Fixed, not re-proven here | Celery task event-loop failures | QA report 2026-10-25 | PLT-003 |
| DEF-03 | Medium | Fixed, not re-proven here | Non-UTF-8 employee CSV returned 500 | QA report 2026-10-25 | PLT-002 |
| DEF-04 | Low | Fixed in that report | mypy failure | QA report 2026-10-25 | No functional case |
| G-W1 | Medium | Open as a product gap | Web navigation is not filtered by permission. API must still deny | functional gap register | SEC-003, ORG-002 |
| G-A2 | Medium | Open | Attendance policy fields stored and not evaluated | functional gap register | ATT-005, BR-04 |
| G-A1 | Info | Stale against current register_company | Older note said employees have no attendance grants. Current code grants punch, view, and regularisation request | `organisation/service.py` | ATT-012, BR-06 |
| G-E1 | Medium | Open | Termination may not set ON_NOTICE or EXITED | functional gap register | EMP-005, BR-07 |
| G-ON1 | Low | Open | Onboarding cancel permission unused | functional gap register | ONB-005 |
| G-L3 | High | Open contradiction | Encashment comment and payroll query disagree | leave and payroll code | BR-03, LEV-C42 |
| G-L4 | Medium | Open | Monthly accrual only in the first five days, no backfill | functional gap register | LEV-C41 |
| G-PAY4 | Medium | Open | Approve, finalise, and mark paid share one permission. Maker-checker still blocks the computer | payroll service | PAY-003 |
| EMP-003 watch | High if reproduced | Not run | Create without an idempotency key may insert two employees | employee create path | EMP-003 |

Face attendance is not listed as a defect. It is unfinished and excluded from execution.

Do not close any open row from this document. Closing requires a later execution that records PASS against the original expected result.
