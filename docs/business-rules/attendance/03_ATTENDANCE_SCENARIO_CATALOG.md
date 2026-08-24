# 03 — Attendance Scenario Catalog

Each scenario: **INPUT → RULES → PRECEDENCE → CALCULATION → FINAL → EMPLOYEE VIEW → HR VIEW → PAYROLL FACT → CORRECTION**.  
Behaviour is **current implementation** unless marked FUTURE.

---

### S01 — Normal 9–6 employee
**INPUT:** WORKING; FIXED 09:00–18:00; unpaid break matched 60m; IN 09:00 OUT 18:00; policy PRESENT≥480m.  
**RULES:** Calendar WORKING; shift FIXED; hour band PRESENT.  
**PRECEDENCE:** Standard path.  
**CALCULATION:** Worked ≈ scheduled; late 0; OT 0.  
**FINAL:** PRESENT; paid 1.00; lop 0.  
**EMPLOYEE:** Present day. **HR:** Present. **PAYROLL:** 1 paid day. **CORRECTION:** Reg if needed while open.

### S02 — 10 min late within grace (grace 15)
**INPUT:** IN 09:10.  
**CALCULATION:** late_raw 10 − 15 → late 0.  
**FINAL:** PRESENT (if hours ok); not late.  
**PAYROLL:** 1.00.

### S03 — 40 min late (grace 15; late band 30+ → HALF_DAY)
**INPUT:** IN 09:40.  
**CALCULATION:** late 25 → band HALF_DAY.  
**FINAL:** HALF_DAY; paid 0.50; lop 0.50 (if hours not ABSENT).  
**CORRECTION:** Regularization MISSING/WRONG punch or FULL_DAY.

### S04 — Early departure
**INPUT:** OUT 17:00; grace_out 10; early band → FLAG only.  
**CALCULATION:** early 50.  
**FINAL:** PRESENT + is_early_out (unless band forces HALF/ABSENT).  
**PAYROLL:** per status.

### S05 — Missing OUT
**INPUT:** IN only; missing_punch=INCOMPLETE.  
**FINAL:** INCOMPLETE; paid/lop 0 until lock TREAT_*.  
**EMPLOYEE:** Incomplete / needs regularization. **HR:** Same; blocks finalize if KEEP_INCOMPLETE.

### S06 — Multiple punches IN/OUT/IN/OUT
**INPUT:** PAIR_ALL.  
**CALCULATION:** Sum pair intervals; gaps → breaks.  
**FINAL:** Per worked minutes + bands.

### S07 — Night shift (cross-midnight)
**INPUT:** 22:00–06:00; attendance_date = start date; IN/OUT spanning midnight.  
**FINAL:** Evaluated on start date.  
**OT day_class:** Often NORMAL under default night_ot_mode=SHIFT_FLAG (gap).

### S08 — Cross-midnight ownership
**INPUT:** Work into next civil date.  
**RULE:** All facts on shift-start date.  
**PAYROLL:** One AttendanceDay for start date.

### S09 — Split shift
**INPUT:** Blocks 06–10 and 14–18; punches cover both.  
**FINAL:** PRESENT if hours/bands ok; late/early 0.  
**Missed afternoon block + behaviour HALF_DAY:** HALF_DAY.

### S10 — Weekly-off, no work
**INPUT:** WEEKLY_OFF; no operates; no punches.  
**FINAL:** NOT_EXPECTED; paid 1.00.

### S11 — Holiday, no work
**INPUT:** HOLIDAY; no operate; no punches.  
**FINAL:** NOT_EXPECTED; paid 1.00.

### S12 — Holiday on weekly-off
**INPUT:** Hard holiday Sunday + WO Sunday.  
**FINAL:** calendar WEEKLY_OFF; holiday_on_weekly_off=true; NOT_EXPECTED if no work.

### S13 — Holiday work + OT
**INPUT:** HOLIDAY; operates or roster holiday working; worked > scheduled; OT eligible.  
**CALCULATION:** worked_on_holiday; day_class HOLIDAY; OT detect.  
**FINAL:** PRESENT (typical) + OT PENDING/AUTO.  
**PAYROLL:** paid day + OT minutes/comp-off facts after approval.

### S14 — Paid full-day leave
**INPUT:** Projection fraction 1.00 is_paid true; no punches.  
**FINAL:** LEAVE; paid 1.00; lop 0.  
**Calendar:** unchanged.

### S15 — Unpaid full-day leave
**INPUT:** is_paid false.  
**FINAL:** LEAVE; paid 0; lop 1.00.

### S16 — Half-day leave + half work
**INPUT:** 0.50 paid leave; punches with worked_minutes>0.  
**FINAL:** HALF_DAY; paid ≈ 1.00 if leave paid + work half; lop from unpaid leave only.  
**Note:** Flat 0.50 overlay, not minute-level half-shift.

### S17 — Leave + punches (KEEP_LEAVE)
**INPUT:** Full leave + punches.  
**FINAL:** LEAVE; late cleared; worked_minutes may still show on row.  
**Hint mode:** punch status kept + work_on_leave_flagged.

### S18 — WFH day
**INPUT:** Desire WFH status.  
**CURRENT:** Engine never emits WFH. Regularization type WFH only helps if punches/shift supplied.  
**FUTURE:** Day overlay WD-17.

### S19 — On-duty day
Same as S18 for ON_DUTY.

### S20 — Roster changes shift A→B
**INPUT:** Assignment A; published roster B.  
**PRECEDENCE:** Schedule B.  
**POLICY quirk:** SHIFT-scoped attendance policy still keyed off assignment shift A.

### S21 — Employee requests regularization (missing OUT)
**INPUT:** Type MISSING_PUNCH; within backdate; allowed.  
**FINAL:** SUBMITTED; pending blocks period close.

### S22 — Manager approves regularization
**INPUT:** MANAGER chain; matching reporting_manager_id.  
**CALCULATION:** Synthetic OUT + recalculate → e.g. PRESENT.  
**AUDIT:** RegularizationAction + punch audit + day recompute.

### S23 — HR rejects regularization
**INPUT:** Reject with comment.  
**FINAL:** REJECTED; day unchanged; another request may be allowed per rules.

### S24 — OT requires manager approval
**INPUT:** requires_post_approval + MANAGER; excess OT.  
**FINAL:** OvertimeRecord PENDING; day ot_pending; blocks finalize.

### S25 — OT auto-approved
**INPUT:** approval_chain AUTO or requires_post_approval false.  
**FINAL:** AUTO_APPROVED; minutes_approved = detected.

### S26 — OT rejected
**INPUT:** Reject.  
**FINAL:** REJECTED; frozen; day OT approved minutes 0 path per sync rules.

### S27 — Comp-off earned
**INPUT:** comp_off_instead_of_pay true; OT approved/auto.  
**FINAL:** comp_off_minutes (+ expiry date); Leave redemption FUTURE.

### S28 — Period finalized
**INPUT:** Validation READY.  
**FINAL:** CLOSED; days locked; summaries frozen.  
**CORRECTION:** Not via normal paths; reopen + manual recompute or FUTURE adjustment.

### S29 — Late correction after period close
**INPUT:** Punch/reg after CLOSED.  
**FINAL:** Refused.  
**FUTURE:** AttendanceAdjustment / arrears.

### S30 — Leave arrives after attendance calculation
**INPUT:** Sync projection on open day.  
**FINAL:** Recalculate → LEAVE/HALF_DAY overlay.  
**If locked:** Sync refused.

### S31 — Employee changes department
**INPUT:** New assignment from D.  
**RULES:** Policy resolution uses new dept from D; prior days use old assignment as-of.

### S32 — Branch transfer (timezone)
**INPUT:** New branch TZ.  
**RULES:** TZ from branch unless shift version TZ set; day boundaries follow resolved TZ.

### S33 — Terminated employee
**INPUT:** Date after LWD.  
**FINAL:** EXITED; paid 0; lop 1.

### S34 — Rehired employee
**INPUT:** Gap then new employment.  
**FINAL:** Gap EXITED/NOT_JOINED as applicable; new spell ACTIVE.

### S35 — No assigned shift
**INPUT:** shift_id null; no roster; no punches; missing_shift=INCOMPLETE.  
**FINAL:** INCOMPLETE (or ABSENT if configured).

### S36 — Configuration missing (no calendar/policy)
**FINAL:** CONFIG_ERROR; blocks finalize.

### S37 — Policy change effective next month
**INPUT:** Version A until Aug 31; Version B from Sep 1.  
**RULES:** Each date uses covering published version; unlocked recalc uses current covering version.

### S38 — Holiday calendar changes after calc
**INPUT:** New holiday added; day unlocked.  
**RULES:** Recalc picks new classification. Locked: unchanged until reopen+recalc.

### S39 — Shift version changes
**INPUT:** New published version closes prior effective_to.  
**RULES:** Dates use version covering them; unlocked recalc updates.

### S40 — Employee-specific policy overrides company
**INPUT:** EMPLOYEE scope attendance policy.  
**PRECEDENCE:** Employee wins WD-09.  
**FINAL:** Employee bands/grace apply.

---

## Additional quick scenarios

| ID | Case | Final (typical) |
|---|---|---|
| S41 | Roster week-off on Wednesday | NOT_EXPECTED |
| S42 | SPECIAL_WORKING Sunday | Expected; evaluate punches |
| S43 | SHUTDOWN | NOT_EXPECTED unless forced work |
| S44 | IN IN OUT pairing | Orphan first IN; may INCOMPLETE |
| S45 | Duplicate device IN within 60s | Collapsed |
| S46 | Weekly OT cap exhausted | Detected OT clipped by remaining |
| S47 | Split OT | Uses required_minutes baseline |
| S48 | Finalize with TREAT_ABSENT incompletes | Status INCOMPLETE; paid 0 lop 1; locked |
| S49 | Optional holiday flag false | WORKING |
| S50 | WORKING_HOLIDAY | WORKING + name; expected |
