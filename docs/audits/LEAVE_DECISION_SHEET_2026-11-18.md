# Leave decision sheet: what to decide before a real year-end or payroll

18 November 2026. For the product owner. Planning only: no code, data or server was changed.

**What this is.** The 16 Nov leave audit (`LEAVE_MANAGEMENT_AUDIT_2026-11-16.md`) found 13 bugs and asked for 15
policy decisions (PD-01 to PD-15), five of them **blocking**. The attendance register adds a few leave rules
nobody has signed (L-02, L-07, L-10, L-12). This sheet turns all of that into questions you can answer with a
tick: **yes (my recommendation), no (an alternative), or change it.** It is the leave session of the pilot plan.
The attendance equivalent is `ATTENDANCE_DECISION_SHEET_GROUP_A_2026-11-18.md`.

**Why now.** There is no real company data yet (test data only; last checked 5 Nov, so re-check). Year-end and
payroll are the two moments leave mistakes become money. Deciding before the pilot is the cheapest moment.

**How the work splits.**
- **Part 1, five real decisions (about 45 minutes).** The blocking ones: PD-01, PD-03, PD-04 (now smaller),
  PD-07, PD-08. Each is a full page below.
- **Part 2, quick confirmations (about 15 minutes).** 14 rows, mostly "keep as built", on one tick-list.
- **Bugs.** 13 bugs need no decision from you. They are fixed regardless; the table below says which still exist.

**What I checked on 18 Nov** (the audit is dated 16 Nov, and a large leave and attendance commit landed on
17 Nov), so I looked at the current code before trusting each line:

| Finding | State on 18 Nov |
|---|---|
| LV-04 pending leave at month close | **Built.** `PENDING_LEAVE` blocker exists in the period-close check. PD-10 becomes "confirm what's built". |
| LV-01 year-end uses the all-time balance | **Still open.** Year-end still reads the all-time balance. |
| LV-06 comp-off expiry removes new comp-off | **Still open.** Same "only if the balance still covers it" rule. |
| LV-07 yearly accrual ignores the probation switch | **Still open.** The yearly branch never reads it. |
| LV-02, LV-03, LV-05, LV-08 to LV-13 | Not re-checked. Treat them as open, as the audit states. |
| Holiday added or removed inside **approved** leave | **Built and approved by you** (P-E, 16 Nov): automatic refund or debit. This shrinks PD-04. |

Every other "Today" line in this sheet (for example that a pending request's charged days are fixed at
submission, PD-04) comes from the 16 Nov audit and was **not re-run** against the code. The worked examples use
the audit's own reproduced scenarios (Appendix A there) or are illustrations built from its descriptions.

**About the money.** "One day of leave" below is a day of balance. Where a rupee figure helps I use **₹1,000 a
day as an illustration only**; the real figure depends on the payroll divisor (a payroll decision).

**How to answer.** Tick one box per question. "Recommended" is my engineering suggestion, not an approval. Every
answer goes into the table at the end with a date and your name, then into the decision register. An answer that
changes the system becomes a ticket; nothing is changed on the spot.

---

## At a glance

Effect is for the employee if you choose my recommendation. Size is my own rough estimate (S = hours, M = a day
or two, L = several days including tests).

| # | ID | Question in one line | Recommended | Effect | Size |
|---|---|---|---|---|---|
| **Part 1: decide** | | | | | |
| 1 | PD-01 | Yearly leave for people who join mid-year | Pro-rata on joining | Up for joiners | M |
| 2 | PD-03 | Which year pays for leave across 31 Dec | Split by date | Down in some cases | L |
| 3 | PD-04 | Pending leave when the calendar changes | Re-count at approval | Neutral; right charge | M |
| 4 | PD-07 | Leave touching a closed month: shorten it | Allow it, open days only | Fixes wrong balances | M |
| 5 | PD-08 | Leave balance when someone leaves | Settle with final pay | Money owed either way | L |
| **Part 2: confirm** | | | | | |
| 6 to 19 | PD-02, 05, 06, 09, 10, 11, 12, 13, 14, 15 and L-02, 07, 10, 12 | See the tick-list | Mostly "keep" | None or small | S each |

---

# Part 1: decide

## 1. PD-01: Yearly leave for people who join mid-year

**Question.** A leave type credited once a year (for example 12 days of earned leave on 1 January) has nothing
for someone who joins after that date. Should they get a share?

**Today.** **Nothing** until the next leave-year start. An earlier decision (LD-21, point 3) built it this way; the
audit asks you to reconsider it. Monthly leave is different: it is prorated by calendar days employed.

**Example.** Policy: 12 days of earned leave, credited 1 January. Sana joins on 1 July. Today she has **0 days**
until 1 January next year: six months with no leave, and HR hand-credits every joiner to get around it.

**Recommended.** **Pro-rata on joining**: 6 of 12 months left means **6 days**, credited on her joining date.

**Alternatives.** (b) The full 12 days on joining. (c) None, as today (and HR credits by hand).

**You must also answer** (only if you choose the recommendation):
- Count by  ☐ whole months left  ☐ calendar days left (the same rule monthly leave already uses)
- Round to  ☐ the nearest half day  ☐ down to a whole day  ☐ leave as a fraction

**Separate bug, fixed regardless (LV-07).** The yearly credit also ignores the "accrue during probation" switch:
a policy set to give nothing during probation still credits 12 days to someone on probation.

**Build.** A credit on the joining date for yearly policies, and the probation fix.

☐ **Recommended** (pro-rata)  ☐ **(b)** full on joining  ☐ **(c)** none  ☐ **Change:** ______________

## 2. PD-03: Which leave year pays for leave that crosses 31 December

**Question.** A leave runs across the year boundary, or is approved late for days that were in the old year. Which
year's balance should be charged?

**Today.** The **old year pays for everything**, because the whole request is debited on its start date (this is
a side effect, bug LV-03, not a chosen rule).

**Example A: leave across the boundary.** Policy LAPSE (unused days disappear at year end). Dev has 20 days and
takes 30 December to 2 January, four charged days. Today all four come out of the old year, so the year-end run
lapses the remaining **16** and he starts the new year at **0**. The two January days cost him nothing from the new
year. With a **split by date**, the two December days come from the old year (18 lapse) and the two January days
from the new year: he starts the new year **2 days lower**.

**Example B: leave approved after year-end (bug LV-02).** Balance 20, carry-forward cap 5. Year-end runs and
lapses 15, leaving 5. Then HR approves 3 backdated days for 29 to 31 December. Those days should have come out of
the old year's 20 (so 17 left, cap 5: still 5). Today they come out of the capped 5, leaving **2**. Dev loses 3
days he should have kept.

**Recommended.** **Split by date**: each day is charged to the leave year it falls in, and old-year leave approved
late is charged to the old year, re-crediting exactly what year-end lapsed.
**Note:** for LAPSE policies this is **stricter for employees** than today (Example A).

**Alternatives.** (b) The old year pays everything, as today (simple, generous). (c) The new year pays everything.

**You must also answer.** If the excess was **encashed** (paid out as money) rather than lapsed, and late old-year
leave is then approved, what happens? I have no strong recommendation; encashment is rare in a first pilot.
☐ refuse the approval automatically and HR adjusts by hand  ☐ re-credit the days and net the cash against the next
pay  ☐ other: ______________

**Bugs fixed regardless.** LV-01 (the lapse is computed from the wrong balance, so someone who has already booked
January leave keeps 3 extra days: balance 20, cap 5, 3 days booked 5 to 7 Jan, ends at 5 instead of 2). It needs
no decision; it is a correction.

**Build.** Debits split by leave year; a closed-year rule for late debits; the LV-01 correction. The largest item
in Part 1.

☐ **Recommended** (split by date)  ☐ **(b)** old year  ☐ **(c)** new year  ☐ **Change:** ______________

## 3. PD-04: Pending leave when the calendar changes (narrowed)

**What you already decided.** On 16 Nov you approved P-E: when a holiday is **added** inside *approved* leave, the
balance is refunded automatically; when one is **removed**, the day is debited automatically (or becomes a
shortfall for HR if the balance is short). That is built. Roster, shift and weekly-off pattern changes are the
separate question L-06 in the attendance sheet.

**What is left.** A leave request that is **still pending** has its charged days fixed on the day it was submitted
and not refreshed when it is approved. Reconciliation only looks at approved leave.

**Example.** Meena submits 22 to 26 December on 10 December. On 15 December HR declares 24 December a company
holiday. The manager approves on 18 December. Her request still charges 24 December as leave. The mismatch
is caught at month close (it blocks closing), and HR has to fix it then.

**Recommended.** **Re-count the days at approval**, so the debit is right from the start.

**Alternatives.** (b) Keep, and rely on the close blocker. (c) Re-count when the calendar changes, for pending
requests too.

**Build.** One re-count inside final approval.

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________

## 4. PD-07: Leave that touches a closed month: can it be shortened?

**Question.** An approved leave spans a month that has since been closed. The person comes back early. Today the
whole request must be cancelled, and it is refused outright if *any* day falls in a closed month.

**Example.** Raj has approved leave 29 November to 3 December. November is closed on 30 November. He returns on
1 December. HR cannot cancel the leave, because 29 and 30 November are in a closed month. So the 1 to 3 December
days stay charged to his balance and shown as leave although he worked them.

**Recommended.** Add **"shorten / cancel remaining days"** for approved leave: only the open (not yet closed)
days are released, with the usual refund and attendance recalculation. Days in a closed month are never touched.

**Alternatives.** (b) Keep, and fix it by hand each time (a balance adjustment plus an attendance correction).

**Build.** A new action on an approved application, with the refund, the projection cancellation and tests.

☐ **Recommended**  ☐ **(b)** keep, by hand  ☐ **Change:** ______________

## 5. PD-08: What happens to leave balance when someone leaves

**Question.** An employee leaves the company with leave in their balance, or with a negative balance. What
should happen?

**Today.** **Nothing.** No encashment, no recovery of a negative balance, no lapse. The balance just sits there.

**Example.** Priya leaves on 31 October with 8 days of earned leave. If your policy lets that leave be encashed, she
is owed about ₹8,000 on the illustration. Nothing triggers it, so HR must remember. Raj leaves with a balance
of minus 3 (he took leave he had not yet earned): about ₹3,000 over-taken. Nothing recovers it either.

**Recommended.** **Build it into final settlement**: encash positive balances where the leave type allows it, and
show negative balances for a decision.

**You must also answer.**
- Positive balance, leave types allowed to be encashed:  ☐ the types already marked "encashment allowed"
  ☐ all paid types  ☐ none; HR settles by hand
- Negative balance:  ☐ recover from final pay  ☐ write off  ☐ show HR and decide case by case

**Alternatives.** (b) Leave it manual for the pilot (HR does a balance adjustment and a note to payroll).

**Build.** A leave step in final settlement, which depends on payroll's own decisions (see the payroll sheet).

☐ **Recommended**  ☐ **(b)** manual for the pilot  ☐ **Change:** ______________

---

# Part 2: quick confirmations

For each row tick **✓ keep / accept the recommendation** or **✎ change** and write it down. Most are "the system
already does this"; the risk column says what would go wrong if the answer is no. These are not blocking, but each
is a rule nobody has signed.

| ID | Question | What happens today | Recommended | Risk if left unsigned | ✓ / ✎ |
|---|---|---|---|---|---|
| PD-02 | Monthly leave: usable in advance or in arrears? | Credited at month end, usable the month after | Keep (arrears) | A new joiner cannot take leave in their first month | |
| PD-05 | Sandwich rule across two different leave types | Applies to the same type only; not across types; not for a half day | Decide per client; default keep | People avoid the rule by using two leave types | |
| PD-06 | Half day at the start or end of a multi-day leave; hourly leave | Not supported (refused by the API and both apps) | Keep; add half-day ends later | People file two requests | |
| PD-09 | Comp-off in fractions; comp-off after the worked day is later regularized away | A fraction like 0.13 day cannot be spent; comp-off stays when the worked day is regularized away | Round down to half days; revoke on change. **Answer after attendance item 4 (H-03)**, which decides whether credit follows the record | Dead balances; unearned comp-off | |
| PD-10 | Leave request still pending when the month is closed | **Built:** close is blocked until pending leave is decided (LV-04) | Keep (block close) | Otherwise the days go to payroll as loss of pay and can no longer be approved | |
| PD-11 | Balance after a policy change or transfer | Stays with the leave type; if the new scope has no policy for that type it is stuck (unusable, never lapses) | Document it and add a report | Orphan balances | |
| PD-12 | Notice period, maximum advance booking, minimum length, eligibility by gender or tenure | None exist | Add notice and eligibility later. For the pilot HR's approval is the safeguard | Maternity leave could be requested by anyone (HR still has to approve) | |
| PD-13 | Worked half of a half-day leave falls short | The whole other half becomes loss of pay (all or nothing) | Confirm. **Answer together with attendance item 10 (H-29)** | Harsh loss of pay for leaving 30 minutes early | |
| PD-14 | HR adjustment taking the balance below zero | Allowed without limit, ignoring the policy's negative floor | Allow, with a warning on screen | An accidental negative balance | |
| PD-15 | Backdated leave | Unlimited unless the policy sets `max_backdated_days` (only the closed month stops it) | Default limit of **30 days** | Late retro leave feeds bug LV-02 | |
| L-02 | Half-day leave | Only for single-day applications | Keep | Same as PD-06 | |
| L-07 | A released loss-of-pay day that comes back | Restored as a normal debit | Keep | A returned day is charged the wrong way | |
| L-10 / D-07 | ON_DUTY on a day of leave | Full leave wins and is still charged; half leave plus ON_DUTY pays the day and still charges the leave | Keep | Leave charged on a day the person was on duty | |
| L-12 | Working during the leave half | A conflict only once it reaches half of that half; less is silently not credited | Keep | Small work in a leave half is ignored | |

**Related, not a decision.** L-13 (`work_on_leave_behaviour` is shown on mobile and has no effect) is removed;
LV-12 lists two other settings that do not do what they say. These need no answer.

---

# Answer record

Fill this in during the session. Copy each row into `ATTENDANCE_POLICY_DECISION_REGISTER.md` (leave section) the
same day and open a ticket for any answer that changes the system.

| # | ID | Answer (A = recommended, B, C, or the change) | Date | Approver | Ticket |
|---|---|---|---|---|---|
| 1 | PD-01 (+ months/days, rounding) | | | | |
| 2 | PD-03 (+ encashed case) | | | | |
| 3 | PD-04 | | | | |
| 4 | PD-07 | | | | |
| 5 | PD-08 (+ encash which types, negative balance) | | | | |
| 6 | PD-02 | | | | |
| 7 | PD-05 | | | | |
| 8 | PD-06 | | | | |
| 9 | PD-09 | | | | |
| 10 | PD-10 | | | | |
| 11 | PD-11 | | | | |
| 12 | PD-12 | | | | |
| 13 | PD-13 | | | | |
| 14 | PD-14 | | | | |
| 15 | PD-15 | | | | |
| 16 | L-02 | | | | |
| 17 | L-07 | | | | |
| 18 | L-10 / D-07 | | | | |
| 19 | L-12 | | | | |

# What happens after you answer

1. **Order of building** (from the audit): Phase 1, balance integrity before any real year-end: LV-01, then
   LV-02 and LV-03 (needs PD-03), LV-05, LV-06. Phase 2: PD-07, then PD-08 (needs payroll). Then yearly accrual
   (LV-07, PD-01), then PD-04 and the rest.
2. **Nothing should run a real year-end** until Phase 1 is done and PD-03 is answered. If the pilot starts before
   31 December, the year-end run is the date to protect: either Phase 1 ships first, or the pilot company uses a
   leave year that does not end soon (a financial year, for example).
3. **Related attendance answers.** PD-09 follows attendance item 4 (H-03). PD-13 follows attendance item 10
   (H-29). PD-04 and L-06 (attendance item 12) are the two halves of "what changes after leave is approved".
4. **Impact report.** Before any pay-changing or balance-changing item ships I produce a report of which
   employees' balances would change and by how much. With no real data it will be empty, which is the reason to
   decide now.

# What comes next

- **Payroll** (the third session of the pilot plan): C-01 to C-20 and the payroll business decisions. PD-08 depends
  on it. If payroll is not settled in time, the fallback is to pilot attendance and leave only and hide payroll.
- **Defaults built without sign-off** (about 60 rows): four keep-as-built tick-lists.
