# Open business rules

These are not defects yet. A case that depends on one of them stays worded as written. If the run cannot proceed, the result is `BLOCKED` and the question remains open. Do not edit the expected result to match whatever the system happened to do.

| ID | Question | Why it is open | Cases |
|---|---|---|---|
| BR-01 | Should a two-day weekend between two leave days be charged? | Code charges a non-working day only when both immediate neighbours in the same request are consuming. Friday–Monday therefore charges 2.00, not 4.00. | LEV-C05, LEV-C06 |
| BR-02 | May an employee submit a request that can only be saved by marking the shortfall as loss of pay, or is loss of pay decided only at approval? | Submit balance checks and the approval LOP branch both exist. Which one wins for a 2.00 request against a 1.00 balance is the thing LEV-C12 must observe. | LEV-C12 |
| BR-03 | Which encashment rows does payroll pay? | A comment says system-written rows only. `list_encashments_between` is broader. | LEV-C42 |
| BR-04 | Which stored attendance-policy fields actually change a day's status? | Gap G-A2 says several are stored and not evaluated. Late behaviour must not be invented. | ATT-005 |
| BR-05 | Are employee emails unique case-insensitively? | The catalogue expects one person per mailbox. The constraint has to be confirmed against the schema during execution. | EMP-002 |
| BR-06 | For a tenant created before migration `20261020090000`, does the employee role have punch grants? | Current `register_company` grants them. The older gap note G-A1 says it does not. Fresh tenants follow the code. Old tenants need a check before that migration is assumed. | ATT-012 |
| BR-07 | What employee status should termination write? | G-E1: `ON_NOTICE` and `EXITED` appear unused. Sign-in must still stop. | EMP-005 |
| BR-08 | Is onboarding cancel a supported action? | `ONBOARDING.CANCEL` is unused in the gap review. | ONB-005 |
| BR-09 | Will companies be able to define their own roles? | No editor exists. The matrix covers the five seeded roles only. | ORG-004 |
| BR-10 | Is monthly accrual intentionally limited to the first five days, with no backfill for a late joiner? | G-L4 describes that window. | LEV-C41 |
| BR-11 | What payroll behaviour is required for tax beyond the limited TDS currently coded? | Statutory TDS is not a full tax engine. Cases use a fixture with statutory either off or fully specified. | PAY-002 |
| BR-12 | Should any manager be department-scoped? | The RBAC decision defers DEPARTMENT scope. | matrix |
| BR-13 | Is rehire a supported operation with a second employment span? | No confirmed rehire API was treated as fact. | EMP-006 |
| BR-14 | Should encashment, carry-forward expiry, and compensatory leave expiry create employee notifications? | There is no in-app notification product. Mail is captured only where a sender already exists. | leave reporting cases |

## Contradictions kept visible

- Gap register G-A1 versus current employee attendance grants. Code wins for a newly registered company. BR-06 covers old data.
- Encashment comment versus query. BR-03. Neither side was chosen.
- Web navigation shows pages the role cannot use. Enforcement is the API. SEC-003.
