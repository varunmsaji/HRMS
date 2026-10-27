# LV-28 replacement (not applied to the original script - audit evidence is preserved)

Original (docs/testing/qa_live_2026-10-25/j3_leave.py:61):

    T('LV-28','pending application has not yet debited balance',float(bal(B,e2))in(10.0,) or True,bal(B,e2))

Proposed replacement (same variables; needs the running QA API to validate):

    row = B['c'].get('/leave-balances',headers=H(B),params=dict(employee_id=e2)).json()['data'][0]
    T('LV-28','pending HR-chain application does not debit balance; it is shown as reserved',
      float(row['balance'])==10.0 and float(row['reserved_balance'])==2.0, row)

Basis: `LeaveBalanceRead` docstring (apps/api/src/hrms/modules/leave/schemas.py:515) - `balance` is not
reduced by a pending application unless `reserve_balance_on_submission` is enabled, and `reserved_balance`
is always shown; the existing integration test `test_reserved_balance_shown_but_not_enforced_by_default`
asserts the same contract. The application covers 2026-09-08..09 (Tue-Wed), i.e. 2 working days.
Open question: whether `reserved_balance` should count calendar or working days is a policy detail
(sandwich rule off in this fixture, Sunday weekly off) - if the first run reports a different number, record it
and ask rather than adjusting the expectation.
