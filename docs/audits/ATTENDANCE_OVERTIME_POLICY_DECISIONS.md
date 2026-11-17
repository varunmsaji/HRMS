# Attendance, Overtime and Leave — policy decisions (16 Nov 2026)

Source: `ATTENDANCE_CALENDAR_OVERTIME_AUDIT_2026-11-16.md` §7 and the remediation prompt.
"Implemented default" means the audit's recommendation was built as the working rule so the code
could be fixed. It is **not** a recorded owner approval; each is listed again under "Awaiting
confirmation" so the owner can overrule it.

| ID | Question | Implemented default | Status |
|---|---|---|---|
| P-A | Overtime on a half-day weekly off | (a) overtime starts after the net schedule of the working half. The policy does not say which half is off, so the **longer** half counts. | Implemented default, ships as engine 16 |
| P-B | Half-day / absent-by-band plus overtime | (b) a `HALF_DAY` or `ABSENT` day (by late band, early band or hour band) pays no overtime. Not applied on a half-day weekly off (P-A governs it). | Implemented default, ships as engine 16 |
| P-C | Correction after a human overtime decision | Human `APPROVED`: reopen as `PENDING` (HR) when detected minutes grow or the day class changes; cap at the new detected minutes when they only shrink. Human `REJECTED`: stays rejected unless detected minutes grow or the class changes, then reopens as `PENDING` — it never becomes an approval by itself. The earlier decision, its reviewer and time are kept in a `SUPERSEDED_BY_RECALCULATION` action and the audit log. | Implemented default |
| P-D | Non-OT-eligible shift on a day off | **Unchanged**: with `eligibility = SHIFT_FLAG` and a non-eligible shift, day-off work earns no overtime and no comp-off. | Not changed; policy screen wording **not** updated |
| P-E | Leave balance after a calendar change | **Approved by the owner, 16 Nov 2026.** Holiday added: automatic refund as a separate ledger entry. Holiday removed: automatic debit; a negative balance only where the leave policy allows it; otherwise a shortfall exception for HR, never automatic loss of pay, and period close is blocked. | Approved and implemented |
| AC-04 | Overtime on an `INCOMPLETE` day | Held `PENDING` for HR, never auto-approved. At lock: `TREAT_ABSENT` rejects it (system action); `TREAT_PRESENT` leaves it pending, which blocks close until HR decides; `KEEP_INCOMPLETE` blocks close. | Implemented default |
| AC-05 | Work inside a half-day-leave half | The day is flagged `work_on_leave_flagged` (blocks close like a full leave day with punches) and earns no overtime. Tolerance = the policy's grace at that end of the day. | Implemented default |

| R-2 | How much a late / early mark may credit towards a full day (independent pre-commit review, 16 Nov 2026) | A mark credits at most **59 minutes** per end (or the policy's grace if larger) to the hour-band lookup; beyond that the hours decide. Existing policy versions are not edited. Builds on D-01. | Implemented default; owner to confirm the figure or choose none / per-policy |
| R-3 | How HR resolves leave that disagrees with the roster, shift, weekly-off pattern or work calendar | HR runs `POST /v1/leave-reconciliation/preview` then `/apply` (company scope, `LEAVE.BALANCE_ADJUST`). Nothing is automatic for these changes (policy A is not retroactive); a shortfall stays an exception and is never loss of pay. | Implemented; the policy-A conflict (should pattern drift be reported at close at all?) is still open |

## Awaiting owner confirmation

1. **P-A** — which half of a half-day weekly off is the working half (the longer half is used).
2. **P-B** — option (b) versus (a)/(c).
3. **P-C** — reopen vs cap rules, and that a rejected decision reopens when overtime grows.
4. **P-D** — confirm "no overtime on a day off for a non-eligible shift" and show it on the policy screen.
5. ~~P-E / AC-03~~ — decided and implemented; see `ATTENDANCE_LEAVE_CALENDAR_RECONCILIATION.md`.
6. **AC-04 / `TREAT_PRESENT`** — whether held overtime on an incomplete day that is paid as present
   may be approved by HR (it can today) or must be recomputed from regularized punches only.
7. **AC-05 tolerance** — grace as the work-in-leave-half tolerance.
8. **R-2** — the 59-minute ceiling on what a late / early mark credits (or none, or per policy).
9. **R-3 / policy A** — whether a weekly-off pattern or work-calendar change should rewrite approved leave by default, or only on HR's explicit reconciliation as built.

## Carried over from the shift audit, not decided here

P-01, P-04, P-05, P-07, P-10, P-11, P-12, P-14. None blocked a fix in this work. **P-12** (a roster
change after leave is approved) is the roster form of AC-03: today it is covered only by the same
detector/blocker, because a roster week-off or "working this holiday" row changes the expected
breakdown. P-E now covers calendar changes; a roster change does not trigger reconciliation yet.
