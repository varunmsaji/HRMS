# 06 — Attendance Indian HR Scenarios

Documents realistic Indian HRMS needs against **current** W1–W9 support.  
Unsupported items are marked **FUTURE / NOT CURRENTLY IMPLEMENTED**.

---

## Supported today (with configuration)

### I1 — Monday–Saturday working week
Configure weekly-off Sunday only (FIXED weekday). Calendar WORKING Mon–Sat. **Supported (A/B).**

### I2 — Alternate Saturdays off
WeeklyOffRule: Saturday + cycle_start_date + week_parity. **Supported (A/B).**

### I3 — 1st/3rd/5th Saturday off
nth_in_month 1 and 3 (and 5 when exists) on Saturday rules. **Supported (A/B).** Last Saturday: nth=-1.

### I4 — State / company holiday calendars
Multiple HolidayCalendars composed into WorkCalendars; PolicyAssignment per branch/employee. **Supported (A/B).**

### I5 — Kerala vs Maharashtra calendars
Two HolidayCalendars + two WorkCalendars assigned by BRANCH or EMPLOYEE. **Supported (A/B).** No built-in statutory pack — HR loads dates.

### I6 — Night / manufacturing shifts
FIXED cross-midnight ShiftVersion; roster for rotating crews. **Schedule supported.** Night OT classification incomplete (see gaps).

### I7 — IT flex schedules
FLEXIBLE shift_type + required_minutes + window. **Partial:** core-hours breach unused.

### I8 — Grace late coming / early going
Attendance policy grace + bands. **Supported.**

### I9 — Half-day by hours
Hour bands (e.g. 240–479 → HALF_DAY). **Supported.** half_day_boundary_minutes unused.

### I10 — LOP
lop_fraction on ABSENT/HALF_DAY/unpaid leave; lock TREAT_ABSENT. **Supported as fractions.** Payroll money **FUTURE (E).**

### I11 — Holiday / weekly-off OT
Work with operate/roster + OT policy rate rows day_class HOLIDAY/WEEKLY_OFF. **Detection + classification supported.** Pay multiplier not applied as money (ADR-0006).

### I12 — Comp-off fact
OT policy comp_off_instead_of_pay + expiry days. **Fact supported.** Balance/ledger/redemption **FUTURE Leave (E).**

### I13 — Half-day leave
LeaveDayProjection 0.50 + half FIRST/SECOND. **Projection supported**; FIRST/SECOND not used to split shift minutes (flat overlay).

### I14 — Multiple / biometric punches
Punch source DEVICE/IMPORT; duplicate window; PAIR_ALL. **Supported.** Full device gateway **FUTURE (E / ADR-0007).**

### I15 — Manager approvals
Local chains for regularization and OT. **Supported (WD-08).** Generic workflow engine **FUTURE.**

### I16 — Payroll period closing
AttendancePeriod finalize + summaries. **Supported at attendance grain.** Payroll import **FUTURE (E).**

### I17 — WFH / Hybrid placement
Assignment work_location_type exists. **Not attendance status.** Auto WFH **NOT IMPLEMENTED (D: PD-WFH-1).**

### I18 — On-duty / outdoor duty
Regularization type exists; status ON_DUTY **not emitted**. **NOT FULLY IMPLEMENTED.**

### I19 — Holiday substitute when festival on Sunday
Manual CalendarException SUBSTITUTE_HOLIDAY (+ CANCEL optional). **Supported manually.** Auto-substitute **NOT IMPLEMENTED (D: PD-CAL-2).**

### I20 — Optional / restricted holidays
Soft holidays default working; flag or Leave later. **Partial:** Leave application UX **FUTURE.**

---

## Explicitly NOT currently implemented

| Need | Status |
|---|---|
| Statutory OT wage calculation (2x etc. hardcoded) | Forbidden (ADR-0006/0011); multipliers informational only |
| PF/ESI/professional tax from attendance | E Payroll/Statutory |
| Leave balances, sandwich leave rules, CL/SL/PL ledgers | E Leave |
| Encashment | E |
| Geo-fencing enforcement on punch | Fields on branch exist historically; attendance punch geofence **not W4 behaviour** |
| Face/biometric vendor connectors | E Device |
| Arrears after payroll lock | E AttendanceAdjustment |
| Shift rotation auto-generator | C/W11 |
| Intra-day shift change | D: PD-SHIFT-1 not supported |
| Late-count → half-day (N lates/month) | Stored fields unused |
| Punch time rounding to nearest 15 min | Stored unused |

---

## Example month (India-flavoured)

Company: Mon–Fri + 1st/3rd Saturday off; Maharashtra holiday calendar; FIXED 09:30–18:30; grace 15; OT post-approval manager; period calendar month.

| Date | Event | Expected system |
|---|---|---|
| Working Tue | Normal punches | PRESENT |
| 1st Sat | WO rule | NOT_EXPECTED |
| Ganesh Chaturthi | HOLIDAY | NOT_EXPECTED |
| Festival on Sunday | WO + holiday flag | WEEKLY_OFF; HR adds Monday SUBSTITUTE if policy |
| Engineer flex | FLEXIBLE version | Hours vs required_minutes / window |
| Plant night | Cross-midnight | Day on start date |
| OT Diwali week | Caps + PENDING | Finalize blocked until approve |
| Month end | Finalize | Summaries frozen for payroll handoff |
