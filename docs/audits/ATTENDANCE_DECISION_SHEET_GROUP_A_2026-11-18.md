# Attendance decision sheet: the 17 decisions that block everything else

18 November 2026. For the product owner. Planning only: no code, data or server was changed.

**What this is.** `ATTENDANCE_OWNER_DECISIONS_REQUIRED.md` lists 17 "Group A" attendance decisions that must be
made before engineers can change the attendance rules. This sheet turns each one into a short question you can
answer with a tick: **yes (my recommendation), no (an alternative), or change it**. It follows the order the
register recommends (its section 7) and splits the 17 into three 45-minute sessions.

**Why now.** As far as I know there is no real company data in the system yet (test data only; last checked
5 Nov, so re-check). Changing a rule today costs nothing in back-pay. Once a pilot company has locked months,
every change needs an impact report on those locked days. Deciding before the pilot is the cheapest moment.

**What I checked.** The "today" lines come from `ATTENDANCE_POLICY_DECISION_REGISTER.md` (16 Nov), which was
re-run by a second independent pass and not contradicted. The attendance engine is still version 16
(`calculation.py`, `ENGINE_VERSION = 16`), and no attendance engine change has landed since the register was
written (last change 17 Nov, a punch-lock fix). So the lines are current. Probe ids (G1, IP2, L7 ...) refer to
`ATTENDANCE_CROSS_MODULE_SCENARIO_MATRIX.md`.

**About the money.** "One day's pay" below means whatever one day of pay is, which depends on the payroll
divisor (a payroll decision, not this sheet's). Where a rupee figure helps, I use **₹1,000 a day as an
illustration only**, not a real salary.

**How to answer.** Tick one box per item. "Recommended" is my engineering suggestion, not an approval. Every
answer is recorded with the date and your name in the table at the end, then copied into the decision
register. **An answer that changes the engine becomes a ticket; nothing is changed on the spot.**

---

## At a glance

Direction of the pay effect is for the employee, if you choose my recommendation. "Size" is my own rough
estimate from the implementation notes in the register (S = a few hours, M = a day or two, L = several days
including an impact report).

| # | ID | The question in one line | Recommended | Pay effect | Size |
|---|---|---|---|---|---|
| **Session 1: what counts as a day worked** | | | | | |
| 1 | H-02 | Someone never punched: incomplete or absent? | Absent once the day is over | Down for no-shows | M |
| 2 | H-01 | A day whose minutes no hour band covers | Refuse such bands; call it a config error | Down for gappy policies | M |
| 3 | H-04 | Which shift governs a rostered day off? | The shift on that date's assignment | None; more overtime counted | M |
| 4 | H-03 | Comp-off when the overtime behind it changes | Credit follows the record | Balances correct down | M |
| 5 | P-05 | Hour bands for short and long shifts | Bands as a share of the shift | Up for part-time | L |
| 6 | P-04 | Work before a fixed shift's start | Count it toward the day | Up for early starters | M |
| **Session 2: marks, grace and half-day leave** | | | | | |
| 7 | D-01a / D-01b / R-2 | How much may a late or early "mark" excuse? | Measure beyond grace; one ceiling per day | Mixed | M |
| 8 | H-05 | Does grace also lower the half-day / absent line? | Only where the miss is within grace | Down at band edges | M |
| 9 | H-07 + H-08 | Half-day leave plus no punches; half-day leave on a day off | Treat like a no-show; nothing to lose on a day off | H-07 down, H-08 up | S |
| 10 | H-29 | Lateness in the worked half of a half-day leave | Judge that half by hours only | Up (a quarter day back) | S |
| **Session 3: approvals, calendars, leave balances** | | | | | |
| 11 | O-19 + NF-1 | A stalled manager approval | HR may reassign and decide | None; removes a close blocker | M |
| 12 | L-06 | Roster / shift change after leave is approved | Keep HR reconciling, give HR the screen | None | S |
| 13 | L-09 | Does accrual clear a leave shortfall? | Yes, any credit does | None to pay; fewer blockers | S |
| 14 | H-30 | Deactivating a calendar or weekly-off pattern | Refuse while linked | None; stops a silent mistake | S |

That is 14 questions covering the 17 IDs (D-01a, D-01b and R-2 are asked as one block; H-07 and H-08 together;
O-19 with its regularization twin NF-1). Not in this sheet: the Group B and C rows (about 100 more rules built
as defaults) and the leave and payroll registers. See "What comes next" at the end.

---

# Session 1: what counts as a day worked

## 1. H-02: Someone never punched: incomplete or absent?

**Question.** An employee has a working day and does not punch at all. What is that day?

**Today.** The day shows **Incomplete**. At month-end lock it depends on the company's setting:
- `TREAT_PRESENT`: **paid in full** (a no-show is paid; verified, probe IP2)
- `TREAT_ABSENT`: one day of loss of pay
- `KEEP_INCOMPLETE`: blocks closing the month until HR resolves it

**Example (₹1,000 a day).** Ravi does not turn up and nobody records anything. Under `TREAT_PRESENT` he is paid
₹1,000 for the day. Under `TREAT_ABSENT` he loses ₹1,000.

**Recommended.** Zero punches on an expected day is a no-show: **Absent** once that day's punch window has
closed. `TREAT_PRESENT` then applies only where at least one punch exists.

**Alternatives.** (b) Leave as is, but remove `TREAT_PRESENT` from the screens. (c) Keep it, and add a
close-blocker for zero-punch days under `TREAT_PRESENT`, so it is no longer silent.

**What it means.** Days a missing employee used to be paid for become loss of pay, so payroll goes down for any
company using `TREAT_PRESENT`. (b) and (c) keep today's pay but stop it being silent.

**Build.** Engine and lock resolution, the wording of the setting on screen, and an impact report of locked
days (nothing to report while there is no real data).

☐ **Recommended** (absent after the punch window)  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________
Also decide: should `TREAT_PRESENT` stay on offer at all?  ☐ yes  ☐ no

## 2. H-01: A day whose minutes no hour band covers

**Question.** A policy's hour bands can start above zero or leave gaps, and publishing accepts that. What should
a day be worth when the minutes worked fall in a gap?

**Today.** **Present, paid in full** (probes 1 and 3).

**Example.** A hand-built policy has bands starting at 2 hours. Priya works 30 minutes and leaves. She gets a
full day (₹1,000). That is what the system does today.

**Recommended.** Refuse such bands when the policy is published (they must start at 0, with no gaps), and treat
"no band" as a **configuration error** that blocks close until fixed.

**Alternatives.** (b) Keep Present but warn at publish. (c) Treat the uncovered minutes as the band below.

**What it means.** Existing hand-built policies with gaps stop paying full days for short work. They must be
republished, or their days become configuration errors that block close. The shipped templates start at 0 and
are not affected.

**Build.** Publish validation (no migration), an engine config-error case, and a list of existing published
versions with gaps first. Two small PRs.

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________

## 3. H-04: Which shift governs a rostered day off?

**Question.** On a day the roster gives an employee off, which shift's calendar and policies apply?

**Today.** None. A calendar or policy tied to a shift does not resolve, so the day is a **configuration error**
that blocks close (probe IP3). A shift-scoped overtime policy gives no overtime on that day.

**Example.** Meera's roster gives her Wednesday off, and her company has shift-specific policies. Wednesday
shows as a configuration error until someone intervenes.

**Recommended.** The shift on the employee's assignment for that date.

**Alternatives.** (b) The previous working day's shift. (c) Company-level policy only on days off.

**What it means.** Removes a class of close-blockers. Overtime worked on a roster day off starts being counted,
which is a (small) pay increase for those who do it.

**Build.** The scope-resolution order in the engine.

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________

## 4. H-03: Comp-off when the overtime behind it changes

**Question.** Comp-off (a day off earned by overtime) is credited as soon as overtime is approved. What should
happen to the credit when the overtime behind it is later corrected, removed or re-detected?

**Today.** The credit is never reduced, and a re-detected record earns a second credit. Reproduced (probe IP10):
- 180 minutes of overtime credits **0.38** day (180 of a 480-minute shift)
- the overtime is removed: the credit stays **0.38**
- 30 minutes are re-detected: **+0.06**
- balance: **0.44 days**, from at most 30 minutes of real overtime. It should be 0.06.

**Recommended.** Credit follows the record: reduced or reversed on a cap, a reopen, a withdrawal or a deletion;
one credit per source record.

**Alternatives.** (b) Credit only at period close. (c) Allow a negative balance after a reversal. (d) Freeze
credit once any leave has been taken against it.

**You must also answer.** If the employee has *already taken* comp-off leave and the credit is then reversed,
what happens to the balance below zero?  ☐ goes negative and is recovered later  ☐ stays at zero and HR is told
☐ other: ______________

**What it means.** Existing balances may be larger than the overtime behind them (an impact report would show
by how much).

**Build.** Comp-off service, a ledger entry for reversals, an integrity report, and a notice to the employee.

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **(d)**  ☐ **Change:** ______________

## 5. P-05: Hour bands for short and long shifts

**Question.** Hour bands are fixed minutes (for example "half day below 240 minutes"). A part-time employee on a
4-hour shift is judged by the same minutes as someone on 8 hours. Should bands scale with the shift?

**Today.** Fixed minutes. A 4-hour shift worked **in full is a half day** (probe O20): 0.50 loss of pay.

**Example.** Anil works his whole 4-hour part-time shift every day. Each day is a half day, so he loses ₹500 a
day on a standard policy, for working exactly what he was rostered.

**Recommended.** Bands as a **share of the shift's net minutes**.

**Alternatives.** (b) One policy per shift length, enforced when assigning. (c) Leave it and document it.

**What it means.** (a) corrects it for part-time staff everywhere. (b) leaves the work to HR and only validates.

**Build.** (a) changes the band format (percent bands) and the engine: the largest item in this sheet. (b) is
validation only.

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________

## 6. P-04: Work before a fixed shift's start

**Question.** An employee works before the shift begins. Does that time count?

**Today.** Never. A session wholly before the start counts **zero** minutes. Worked 04:30 to 08:30 on a 09:00
shift is **Absent** (probe IP7c). Flexible shifts do count it.

**Example.** Kavya's shift starts at 09:00. She comes in early for an urgent job, works 04:30 to 08:30, and
then goes home. She did four real hours, but none fall inside the shift, so her day is Absent and she loses
₹1,000.

**Recommended.** Count it toward the day (not as overtime) when the employee did not also work the shift. This
needs a rule written down.

**Alternatives.** (b) Keep as is and refuse such punches. (c) Make it a per-policy choice.

**What it means.** Removes a full day of loss of pay for early starters.

**Build.** The shift-start clamp and its overtime interaction.

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________

---

# Session 2: marks, grace and half-day leave

D-01a, D-01b, R-2, H-05 and P-04 together decide the shape of the late/early rules, so they are asked together
and built as one engine change (engine 17).

## 7. D-01a / D-01b / R-2: How much may a late or early "mark" excuse?

**Background.** A "mark" is a minor lateness or early exit that is recorded but should not cost pay. The engine
lets a mark excuse **up to 59 minutes per end**, measured from the shift's start (grace included). That 59 is a
hidden constant in the code (`MARK_CREDIT_CEILING_MINUTES`) that nobody has approved (R-2).

**Today, two surprises.**
- **D-01a.** With 10 minutes' grace, arriving **50 to 59 minutes after the start costs half a day** on the
  standard template, even though the template's own text says marks are "not deducted" (probe G1). With 30
  minutes' grace it starts from 30.
- **D-01b.** A late mark and an early mark **together excuse up to about two hours**. Arriving 59 minutes late
  and leaving 59 minutes early, **362 of 480 minutes** is still a full **Present** day (probe G1).

**Recommended.**
- D-01a: measure the 59 minutes **beyond grace**, so the template text is true.
- D-01b: **one combined ceiling per day**, not one per end.
- R-2: keep a ceiling of 59, but make it a **visible policy value** instead of a hidden constant.

**Alternatives.** Keep as is and change the template text to match. Or make the ceiling a per-policy setting.

**What it means.** Mixed: fewer half-days for people who arrive up to 59 minutes after grace, but a day with both
a late and an early mark is no longer excused in full, so it is judged by the hour bands instead. Keeping
today's behaviour means more half-days than the screen promises.

**Build.** The grace-credit calculation, the template wording on web and mobile, and possibly a policy field.

D-01a (measure beyond grace):  ☐ **Recommended**  ☐ keep, change the text  ☐ **Change:** ____________
D-01b (one combined ceiling):  ☐ **Recommended**  ☐ keep (two ends)  ☐ **Change:** ____________
R-2 (the ceiling itself):  ☐ 59, as a visible policy value  ☐ no ceiling  ☐ per policy  ☐ **Change:** ______

## 8. H-05: Does grace also lower the half-day and absent lines?

**Question.** Grace (for example 10 minutes) exists so a slightly late arrival is not marked late. Today it also
quietly lowers the half-day and absent thresholds.

**Today.** Yes, by up to grace-in plus grace-out. **239 minutes worked is a Half day** under an "absent below
240" band (probe H3). On the standard template a person who worked 230 is a Half day too.

**Example.** Deepak works 235 minutes and the band says "absent below 240". Today grace lifts him over the line
and he gets a half day (₹500). Under the recommendation, if he simply worked fewer hours (rather than missing
a few minutes inside grace) that day would be Absent (₹0).

**Recommended.** Credit grace **only where the miss at that end is within grace**.

**Alternatives.** (b) Keep, and document it. (c) A per-policy switch.

**What it means.** Up to 20 minutes' difference at each band edge on the standard template (60 on the flexible
one). **This recommendation is stricter for employees**, not looser.

**Build.** The same grace-credit calculation as item 7.

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________

## 9. H-07 and H-08: Half-day leave and the other half

**H-07. Half-day leave, no punches in the other half.**
- **Today.** The other half becomes loss of pay **immediately** (0.50 leave, 0.50 loss of pay), unlike a
  full-day no-show, which waits as "Incomplete" (probe L11).
- **Example.** Sana has approved half-day leave and does not turn up for the other half: ₹500 is withheld at
  once, while a full no-show on another day would have waited.
- **Recommended.** Treat it like any no-show, so it follows your answer to item 1 (H-02).
- ☐ **Recommended (follow H-02)**  ☐ keep as is  ☐ **Change:** ______________

**H-08. Half-day leave on a day that is, or has become, a day off.**
- **Today.** **0.50 loss of pay** until reconciled (probes L1 to L3, IP8), although there is nothing to lose on a
  day off. This is a wrong deduction.
- **Recommended.** Nothing to lose on a day off. This is a fix, not a policy trade-off.
- ☐ **Confirm the fix**  ☐ **Change:** ______________

## 10. H-29: Lateness in the worked half of a half-day leave

**Question.** Half-day leave plus arriving late in the half that *is* worked. What does the lateness cost?

**Today.** It depends on whether the policy has late bands. With **no late bands**, the lateness cliff applies to
the worked half and **costs a quarter day** (probe L7: in at 14:11, 0.75 paid, 0.25 loss of pay). With late
bands, the same case pays **1.00** (probe L8). The same lateness is treated differently by policy.

**Recommended.** Judge the worked half **by hours only**, or apply the same mark rule as a full day.

**Alternatives.** Keep as is.

**What it means.** The quarter-day deduction (₹250 on ₹1,000 a day) goes away for policies without late bands.

**Build.** The leave overlay's worked-half verdict. Depends on item 7 if the mark rule is chosen.

☐ **Recommended (hours only)**  ☐ same mark rule as a full day  ☐ keep  ☐ **Change:** ______________

---

# Session 3: approvals, calendars, leave balances

None of these four changes what anyone is paid. They decide how HR gets unstuck.

## 11. O-19 and NF-1: A stalled manager approval

**Question.** Overtime and regularization requests wait for the employee's manager. If that manager leaves, who
can decide?

**Today.** Only the manager recorded when the request was first created can act. There is **no reassignment and
no HR override**. If that manager leaves, the request stays pending and **blocks closing the month**. The only
way out today is HR changing the policy's approval chain for *everyone* and recalculating. (Leave already has a
reassignment path.)

**Recommended.** HR (company scope) may **reassign** the request, as leave does, and may also **decide at any
stage**. Every such action is audit-logged.

**Alternatives.** (b) HR may only reassign. (c) Auto-escalate to HR after N days (you would choose N: ______).

**Build.** A new endpoint or a relaxed reviewability check, an audit entry and tests.

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________

## 12. L-06 ("policy A"): Roster, pattern or shift changes after leave is approved

**Question.** HR changes a roster, a weekly-off pattern or a shift after someone's leave was already approved.
Should the leave be rewritten automatically?

**Today.** No. Approved leave is not rewritten, HR reconciles by hand, and **closing the month is blocked until
they do**. (Holiday and calendar changes are already automatic: you approved that on 16 Nov as P-E.)

**Recommended.** Keep it, because automatic changes move leave balances without a person, and give HR a proper
reconciliation screen (MA-36).

**Alternatives.** (b) Automatic for dated changes only. (c) Automatic for all.

**Build.** Nothing if kept (the screen only).

☐ **Recommended**  ☐ **(b)**  ☐ **(c)**  ☐ **Change:** ______________

## 13. L-09: Does accrual clear a leave shortfall?

**Question.** A shortfall is recorded when approved leave exceeds the balance. What clears it?

**Today.** Only an HR credit. Normal monthly accrual does not, so a shortfall keeps blocking close even after
the employee has earned the days back.

**Recommended.** **Any** credit (accrual, carry-forward, comp-off, adjustment) runs the shortfall check.

**Alternatives.** HR credit only, documented.

**Build.** One call after each credit path in the leave service.

☐ **Recommended**  ☐ **HR-only**  ☐ **Change:** ______________

## 14. H-30: Deactivating a calendar, work calendar or weekly-off pattern

**Question.** An administrator switches off a holiday calendar or weekly-off pattern. Should its holidays and
days off stop applying?

**Today.** Nothing changes. Its holidays and off days **still apply to every date and to leave counting**
(MA-28). Linking an inactive one is refused, but deactivating one that is linked is allowed. An administrator
can believe holidays are off while they still apply.

**Recommended.** **Refuse deactivation while linked**; deactivation takes effect only through an effective-dated
unlink.

**Alternatives.** Make "inactive" effective from a chosen date.

**Build.** Calendar setup validation and the reconciliation consequences. The screen must say which.

☐ **Recommended**  ☐ **Effective from a date**  ☐ **Change:** ______________

---

# Answer record

Fill this in during the sessions. Copy each row into `ATTENDANCE_POLICY_DECISION_REGISTER.md` the same day, and
open a ticket for any answer that changes the engine.

| # | ID | Answer (A = recommended, B, C, or the change) | Date | Approver | Ticket |
|---|---|---|---|---|---|
| 1 | H-02 | | | | |
| 2 | H-01 | | | | |
| 3 | H-04 | | | | |
| 4 | H-03 (+ below-zero rule) | | | | |
| 5 | P-05 | | | | |
| 6 | P-04 | | | | |
| 7 | D-01a | | | | |
| 7 | D-01b | | | | |
| 7 | R-2 | | | | |
| 8 | H-05 | | | | |
| 9 | H-07 | | | | |
| 9 | H-08 | | | | |
| 10 | H-29 | | | | |
| 11 | O-19 + NF-1 | | | | |
| 12 | L-06 | | | | |
| 13 | L-09 | | | | |
| 14 | H-30 | | | | |

# What happens after you answer

1. **Order of building** (from the register): H-02, H-01, H-04 and H-03 first, because they decide whether
   Phase 1 can start. Then P-05, D-01a/b, H-05 and P-04 as **one** engine change, so policies are republished
   once. Then H-07, H-08, H-29. The session-3 items are small and independent.
2. **Freeze.** After sign-off the attendance engine changes only through tickets from these answers or from the
   end-to-end rehearsal. Any engine change reopens the attendance and payroll regression tests.
3. **Impact report.** Before each pay-changing item ships, I produce a report of which locked days would change
   and by how much. With no real data yet it will be empty, which is the reason to decide now.
4. **Money check.** Items 1 to 10 change pay, overtime or balances (11 to 14 change none of them). I will show a worked example with
   the real divisor once payroll's own decision (the divisor) is settled.

# What comes next

This sheet covers **Group A** only. Still to prepare, in the pilot plan's order:
- **Leave** (session 2 of the plan): PD-01 to PD-15 from the 16 Nov leave audit.
- **Payroll** (session 3 of the plan): C-01 to C-20 from the policy decision map, and the payroll business
  decisions. If those are not settled in time, the fallback is to pilot attendance and leave only and hide
  payroll for pilot companies.
- **Group C** (about 60 defaults built without sign-off): the register suggests four batches, each answerable as
  "keep as built". I can prepare those as one-page tick lists.
