# Attendance UI/UX improvement plan

19 November 2026. Planning only; nothing was changed. Finding ids (AUD-xx) are in
`ATTENDANCE_COMPLETE_AUDIT_REPORT.md`; task ids (R-xx) in `ATTENDANCE_IMPLEMENTATION_ROADMAP.md`.

## 1. Current assessment in one paragraph

The HR side has improved a lot in the last week. The Attendance page is now exception-first, with fixes on
each row, a typeahead, bulk mark and a List/Grid switch, and mobile follows it closely. The weak side is
**the result itself**. A day's status is a single word with no reason. A person who is working can be shown
as "Incomplete" or "Absent". Totals that look alike come from four different calculations. And the one fact
that costs money, that an unfixed day becomes unpaid at month close, is never said. The plan below fixes
the result before it touches layout.

## 2. Principles

1. **One vocabulary, set by the backend.** Every screen shows the same word, colour and icon for the same day
   (AUD-01, AUD-10, AUD-11).
2. **Verdicts only when the day is over.** Before shift end, show progress, not a status (AUD-03, AUD-05).
3. **Every verdict has a reason a non-expert can read** (AUD-06).
4. **Money is visible.** Paid, unpaid and overtime figures are the payroll ones, labelled as such
   (AUD-07, AUD-09, AUD-14).
5. **Say how fresh the numbers are** (AUD-15).

## 3. Attendance calendar

### 3.1 Cell design (web month calendar, mobile My calendar, both HR grids)

| Layer | Shows | Rule |
|---|---|---|
| Fill colour | The day's display status (one of ≈9, from the backend) | Same palette on web and mobile; colour is never the only signal |
| Centre glyph / letter | Same status as a letter (P, A, ½, L, H, W, OD, ?, !) | Already exists; keep |
| Split fill | Half-day leave or half weekly off | Top half / bottom half, so "½ leave + ½ worked" is visible (AUD-09) |
| Corner dot, top right | Needs action: missing punch, incomplete, pending correction, unresolved work-on-leave | Red if it will become unpaid at close, amber otherwise (AUD-07) |
| Corner mark, bottom right | One of: late, left early, overtime | Priority late > early > OT; the rest in the tooltip / day sheet |
| Lock icon | Day locked for payroll | Small, muted |
| Outline only | Today (in progress) | No verdict colour until the shift ends (AUD-03) |
| Hatched / empty | Future | Distinct from "No record" (AUD-12) |
| Dashed with "?" | No record for a past working day | Says "not calculated", an HR problem, not the employee's |

Legend: always show the full legend (collapsed on mobile), not only the statuses used this month, so people
learn the system once.

### 3.2 Selecting a day

Tapping a cell opens a **day sheet** (side drawer on web, bottom sheet on mobile) instead of navigating away:
status and reason line, punch timeline, worked vs required, late / early, overtime split, pay effect, and
"Request correction" if allowed. "Open full day" goes to the existing page.

### 3.3 Month header

Above the grid, four figures that match payroll (from the period summary or the same backend function,
R-B03): **Paid days · Unpaid (LOP) days · Leave days · Overtime approved**. Then a second line: late count,
days needing action, "Month closes on <date>".

### 3.4 HR grid

- Row totals use the same paid / LOP / leave figures (today they use a third method, AUD-09).
- Keep the new "needs a look first" sort (uncommitted on mobile; add to web).
- Column header per day shows the day's company-wide rate on hover.

## 4. "Why this result" (transparency system)

### 4.1 Backend contract (R-C01)

The day read gains an `explanation` object built from the snapshot and the policy version in force. The
clients render it; they never derive it.

```
explanation: {
  verdict:    { status, label, tone },
  reason:     "Worked 3 h 50 m. A full day needs 6 h under the Standard policy; 4 h to 6 h is a half day.",
  facts: [
    { key: "scheduled",  label: "Shift",           value: "09:30 – 18:30 (8 h after a 1 h unpaid break)" },
    { key: "first_in",   label: "First in",        value: "10:05" },
    { key: "grace",      label: "Grace",           value: "15 min" },
    { key: "late",       label: "Late by",         value: "20 min beyond grace" },
    { key: "required",   label: "Full day needs",  value: "6 h" },
    { key: "worked",     label: "Worked",          value: "3 h 50 m" },
    { key: "breaks",     label: "Breaks",          value: "45 min (30 min unpaid)" }
  ],
  rules_applied: [ "hour_band:HALF_DAY", "late_band:mark" ],
  pay: { paid: "0.5 day", unpaid: "0.5 day", leave: null, label: "Half day paid" },
  overtime: { found_min, approved_min, pending_min, class_label },
  action: { kind: "REQUEST_CORRECTION", deadline: "2026-11-30", consequence: "Counts as absent (unpaid) if not fixed" } | null,
  provisional: true | false
}
```

### 4.2 Templates by status (illustrative wording; the rule values come from the policy)

| Result | Reason line |
|---|---|
| Present | "Worked 8 h 10 m of 8 h. On time." |
| Half day (hours) | "Worked 3 h 50 m. A full day needs 6 h; 4 h to 6 h is a half day." |
| Half day (late) | "Arrived 10:50, 80 min late beyond the 15-min grace. Arrivals over 60 min late count as a half day." |
| Absent | "No punches on a working day." or "Worked 1 h 40 m; under 4 h counts as absent." |
| Incomplete | "Punched in at 09:12, no punch out. Fix by 30 Nov or this day counts as absent (unpaid)." |
| Holiday / weekly off | "Diwali (holiday). No work expected." |
| On leave | "Casual leave, full day (paid)." / "Half day sick leave (morning), worked the afternoon." |
| Config error | Employee: "We couldn't calculate this day. HR has been told." HR: the actual missing setup item. |
| Overtime | "Worked 1 h 45 m past shift end. 1 h 30 m approved, 15 m waiting for your manager." |

### 4.3 Who sees what

- Employee and manager: verdict, reason, facts, pay, action.
- HR: the same, plus "Technical details" (versions, snapshot), gated by `ATTENDANCE.RECOMPUTE` or a new view
  permission (AUD-06). Policy versions are shown by name and effective date, never as UUIDs.

## 5. Employee experience

### 5.1 Today card (web self view, mobile Attendance tab)

```
Working since 09:12            [Punch out]
3 h 20 m worked · 4 h 40 m left in shift (ends 18:30)
On time  ·  Break: 30 m taken of 60 m
```
- No status badge until shift end (AUD-03). After it: the verdict with its reason line.
- One worked figure, live while open (AUD-05); server figure once closed.
- Not a working day / on leave: as mobile does today, with "Punch anyway" kept.
- Web punch blocked by face or location policy: already explained by `58cc67e`; keep.

### 5.2 Needs attention

Each item: date, problem, **consequence and deadline**, one action. Sort by deadline. Include today once
the shift has ended.

### 5.3 This month

Header figures as in §3.3, then the calendar, then a list toggle (same rows as the calendar, for screen
readers and small phones).

### 5.4 Requests

Correction requests show their state on the day itself ("Correction requested 12 Nov, waiting for your manager") and
in a single "My requests" list with the history (submitted, approved / rejected, by whom, comment).

## 6. HR / admin experience

| Change | Why | Finding |
|---|---|---|
| Home dashboard and Attendance page read the same backend function | Numbers disagree today | AUD-01 |
| Half day counted at the agreed weight everywhere | Rate disagrees with calendar | AUD-02 |
| Before shift end, people are "Not in yet" or "Working", never Incomplete | Morning view looks broken | AUD-03 |
| Past dates show "Not calculated: N" with a Recalculate action | Missing rows vanish | AUD-08 |
| One "Needs attention" definition, the same count in banner, tile and list | Counts disagree | AUD-10 |
| "Calculated up to HH:MM" and the next sweep time | Staleness | AUD-15 |
| Close-readiness view: per employee, paid / LOP / incomplete-to-become-absent | Surprise LOP | AUD-07, AUD-09 |
| Disputed day: same "Why" panel as the employee, plus technical details | Investigation | AUD-06 |
| Keep AP-09 open: compare a partial morning only with the same time last week, or hide the delta | Misleading deltas | AP-09 |

## 7. Tables, cards and formatting

- Durations: `7 h 05 m` everywhere (no decimals, no "7.08"). Fractions never shown raw: "Half day", "0.5 day".
- Times: 12- or 24-hour per company setting, with the time zone shown only when it differs from the company's.
- Empty states say why ("No attendance yet: it appears when you punch in, or after 09:30").
- Error states say who can fix it (employee, HR, admin).
- Status chips always have text; tones meet contrast in light and dark themes (both apps already use tokens).

## 8. Mobile specifics

- Keep its better "provisional today" handling and make the web match (R-D02).
- Day sheet as a bottom sheet from My calendar (§3.2).
- Thumb-reach punch button stays sticky; show the reason when punching is blocked (face, location, outside
  shift) on the button itself, not only in a toast.
- Decide offline punching (AUD-16) before designing any offline UI.
- Run the existing golden tests on 320 / 360 / 390 for every calendar change; verify on a real device
  (`MOBILE_UX_NEXT_STEPS.md` notes none of phases 1–4 has been tried on a phone).

## 9. What not to build

- No live "who is in right now" view (decision D4, 18 Nov) until there is a live punch feed.
- No anomaly-detection or AI features before the numbers agree; they would amplify inconsistent inputs.
- No new dashboard cards. The work is to make existing figures agree and explain themselves.
