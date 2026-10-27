# 03 — User journeys

Executable copies are JRN-001 through JRN-010 in `10_JOURNEY_CASES.md` and `TEST_CASES.csv`. This file is the business sequence a reviewer walks. All of them are `NOT_RUN`.

Shared preconditions for every journey: disposable database, disposable Redis database number, disposable bucket, captured email sender, no SMTP egress, clock and timezone stated in the evidence, git commit recorded without changing git.

## Journey 1 — New company setup (JRN-001)

1. Founder registers QA Foundry and verifies through captured mail.
2. Admin creates branch North, department Engineering, designation Engineer, and a Mon–Fri calendar with Saturday and Sunday as weekly off.
3. Admin publishes casual leave: entitlement 12.00, max consecutive 5, half day on, sandwich on, reserve off, negative off, chain MANAGER.
4. Admin creates Alice, joining 2026-04-01, reporting to Maya once Maya exists, placed in North.
5. Evidence: each screen after reload, `role_permission` for the five roles, calendar resolution for 2026-06-06, Alice's opening balance.

Database: one company id on every new row. Cleanup: keep as tenant A.

## Journey 2 — Onboarding (JRN-002)

1. HR creates a case for new.hire@qa.invalid.
2. The capture file contains one link.
3. The candidate completes the public wizard and signs in.
4. Profile shows company A. Grade, manager, shift, and salary stay empty because activation does not copy them.
5. The same link fails on second use (ONB-002). A parallel submit creates one user (ONB-003). A forced mail failure leaves the case unsent (ONB-004).

## Journey 3 — Normal attendance day (JRN-003)

1. Alice signs in.
2. Punch in 09:05 and out 18:10 local.
3. Maya sees those times. Alice sees the same times. Bob does not see Alice.
4. A repeated punch in does not open a second interval (ATT-002).

## Journey 4 — Attendance correction (JRN-004)

1. Alice has an in punch and no out punch.
2. She requests 18:00 out with reason "forgot".
3. Bob cannot approve. Maya can, once.
4. The day shows one out punch. A locked period would have rejected the original punch (ATT-009).

## Journey 5 — Leave through completion (JRN-005)

Opening balance 10.00. One future working day. Reserve off. Chain MANAGER.

1. Alice reads 10.00.
2. She submits. Status SUBMITTED. Ledger still 10.00.
3. Maya approves. Status APPROVED. Ledger 9.00. Attendance day shows leave.
4. Alice, the leave page, and the API all show 9.00.

Variants, each as its own case: rejection with no debit (LEV-C26), cancel before start restores 10.00 (LEV-C32), one day over balance rejected (LEV-C11), overlap rejected (LEV-C15), two approvers debit once (LEV-C28).

## Journey 6 — Payroll (JRN-006)

1. HR sets Alice's basic to 30000.00. Alice cannot.
2. HR computes June 2026. Net is the engine result for that input, written down before the comparison.
3. HR cannot approve. The admin, who did not compute it, approves and finalises.
4. Alice's payslip matches the line. Bob's request for her slip is 404.
5. Mark paid does not call a bank (PAY-008). One unpaid day changes the net by the engine's one-day amount (PAY-009).

## Journey 7 — Lifecycle (JRN-007)

1. Bob has a past approved leave day.
2. HR terminates him.
3. Bob cannot sign in.
4. HR can still open the historical day.
5. Changing Alice's manager while a request is pending does not move the approver (EMP-007).

Rehire is EMP-006 and is allowed to come back BLOCKED if the product has no rehire operation.

## Journey 8 — Documents (JRN-008)

Synthetic file `qa.txt` with contents `synthetic-document`. Owner can download the same bytes. A colleague cannot. A closed storage port leaves no metadata row (DOC-002). A terminated owner cannot download (DOC-003).

## Journey 9 — Two tenants (JRN-009)

Repeat journey 1 for a second company with different marker names. Each admin's lists contain only their marker. Each foreign UUID read and write returns 404 and changes nothing.

## Journey 10 — Failure and recovery (JRN-010)

Force the mail sender to fail and point storage at a closed port. Invite and upload both fail with no new user and no new document. Restore the doubles and retry once. Exactly one user and one document appear.

Stop the batch if any write lands in the other tenant.
