import { describe, expect, it } from "vitest";

import type { AttendancePeriod, AttendancePeriodSummaryRow } from "@/lib/attendance-period/types";
import type { OvertimeRecord } from "@/lib/overtime/types";
import type { RegularizationRequest } from "@/lib/regularization/types";

import {
  DEFAULT_FILTERS,
  addDays,
  applyDrillFilters,
  applyPopulationFilters,
  bucketOf,
  buildAttentionItems,
  buildMuster,
  buildTrend,
  dailyHours,
  employeeName,
  employeesWithoutRecord,
  eachDate,
  formatPct,
  hasActiveFilters,
  indexEmployees,
  isEmployedOn,
  monthGrid,
  musterDates,
  parseFilters,
  pct,
  pickDefaultPeriod,
  presenceOf,
  repeatAbsences,
  resolveRange,
  serializeFilters,
  sumPeriodSummary,
  summarizeMonth,
  summarizeOvertime,
  summarizeWorkHours,
  weekStart,
  windowRange,
  type EmployeeLite,
} from "./dashboard";
import { makeAbsentDay, makeDay } from "./__fixtures__/day";
import { makeSummaryDay } from "./__fixtures__/summary";

const TODAY = "2026-10-07"; // a Wednesday

describe("date helpers", () => {
  it("adds days across month boundaries without timezone drift", () => {
    expect(addDays("2026-10-31", 1)).toBe("2026-11-01");
    expect(addDays("2026-03-01", -1)).toBe("2026-02-28");
  });

  it("finds the Monday of the week", () => {
    expect(weekStart("2026-10-07")).toBe("2026-10-05");
    expect(weekStart("2026-10-11")).toBe("2026-10-05"); // Sunday belongs to the Monday before
    expect(weekStart("2026-10-05")).toBe("2026-10-05");
  });

  it("enumerates an inclusive date range", () => {
    expect(eachDate("2026-10-01", "2026-10-03")).toEqual(["2026-10-01", "2026-10-02", "2026-10-03"]);
  });

  it("never fabricates a percentage from a zero denominator", () => {
    expect(pct(3, 0)).toBeNull();
    expect(formatPct(pct(3, 0))).toBe("—");
    expect(formatPct(pct(184, 200))).toBe("92.0%");
  });
});

describe("range + URL filters", () => {
  it("resolves the presets against 'today'", () => {
    expect(resolveRange({ ...DEFAULT_FILTERS, preset: "today" }, TODAY)).toEqual({ from: TODAY, to: TODAY });
    expect(resolveRange({ ...DEFAULT_FILTERS, preset: "week" }, TODAY)).toEqual({ from: "2026-10-05", to: TODAY });
    expect(resolveRange({ ...DEFAULT_FILTERS, preset: "month" }, TODAY)).toEqual({ from: "2026-10-01", to: TODAY });
  });

  it("clamps a custom range: no future dates, inverted ranges collapse, and the span is capped", () => {
    const base = { ...DEFAULT_FILTERS, preset: "custom" as const };
    expect(resolveRange({ ...base, from: "2026-10-01", to: "2026-12-31" }, TODAY).to).toBe(TODAY);
    expect(resolveRange({ ...base, from: "2026-10-06", to: "2026-10-02" }, TODAY)).toEqual({ from: "2026-10-02", to: "2026-10-02" });
    const wide = resolveRange({ ...base, from: "2025-01-01", to: TODAY }, TODAY);
    expect(wide.to).toBe(TODAY);
    expect(eachDate(wide.from, wide.to)).toHaveLength(92);
  });

  it("falls back to today for an invalid custom range", () => {
    expect(resolveRange({ ...DEFAULT_FILTERS, preset: "custom", from: "nope", to: "" }, TODAY)).toEqual({ from: TODAY, to: TODAY });
  });

  it("widens the fetch window to at least 14 days of context", () => {
    expect(windowRange({ from: TODAY, to: TODAY })).toEqual({ from: addDays(TODAY, -13), to: TODAY });
    const month = { from: "2026-09-01", to: "2026-09-30" };
    expect(windowRange(month)).toEqual(month);
  });

  it("round-trips filters through the URL and omits defaults", () => {
    expect(serializeFilters(DEFAULT_FILTERS).toString()).toBe("");
    const filters = {
      ...DEFAULT_FILTERS,
      preset: "custom" as const,
      from: "2026-10-01",
      to: "2026-10-05",
      employeeId: "emp-9",
      bucket: "ABSENT" as const,
      flag: "late" as const,
      shiftId: "shift-1",
      employeeStatus: "ACTIVE",
      legalEntityId: "le-1",
    };
    const qs = serializeFilters(filters);
    expect(parseFilters(qs)).toEqual(filters);
  });

  // F5-1: the Needs Attention "View all" drill must be distinguishable from every focus-date
  // drill (KPI card, status chart, toolbar select) sharing the same bucket/flag, so it is its own
  // URL-serialisable filter field, defaulting to "" (focus-date, every pre-existing drill source).
  it("round-trips the Needs Attention range-scope flag and omits it when unset", () => {
    expect(serializeFilters(DEFAULT_FILTERS).toString()).not.toContain("scope");
    const filters = { ...DEFAULT_FILTERS, flag: "missing_punch" as const, scope: "range" as const };
    const qs = serializeFilters(filters);
    expect(qs.get("scope")).toBe("range");
    expect(parseFilters(qs)).toEqual(filters);
    expect(parseFilters(new URLSearchParams("scope=bogus")).scope).toBe("");
  });

  it("ignores unknown / tampered query values instead of trusting them", () => {
    const parsed = parseFilters(new URLSearchParams("range=forever&bucket=DROP_TABLE&flag=nope"));
    expect(parsed.preset).toBe("today");
    expect(parsed.bucket).toBe("");
    expect(parsed.flag).toBe("");
    expect(hasActiveFilters(parsed)).toBe(false);
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, employeeId: "x" })).toBe(true);
  });
});

describe("bucketOf", () => {
  it("maps the backend status model onto mutually exclusive buckets", () => {
    expect(bucketOf(makeDay())).toBe("PRESENT");
    expect(bucketOf(makeDay({ attendance_status: "WFH" }))).toBe("REMOTE");
    expect(bucketOf(makeDay({ attendance_status: "ON_DUTY" }))).toBe("ON_DUTY");
    expect(bucketOf(makeDay({ attendance_status: "LEAVE" }))).toBe("LEAVE");
    expect(bucketOf(makeDay({ attendance_status: "NOT_JOINED" }))).toBe("NOT_EMPLOYED");
    expect(bucketOf(makeDay({ attendance_status: "EXITED" }))).toBe("NOT_EMPLOYED");
  });

  it("splits NOT_EXPECTED by the calendar day type", () => {
    expect(bucketOf(makeDay({ attendance_status: "NOT_EXPECTED", calendar_day_type: "HOLIDAY" }))).toBe("HOLIDAY");
    expect(bucketOf(makeDay({ attendance_status: "NOT_EXPECTED", calendar_day_type: "WEEKLY_OFF" }))).toBe("WEEKLY_OFF");
    expect(bucketOf(makeDay({ attendance_status: "NOT_EXPECTED", calendar_day_type: "SHUTDOWN" }))).toBe("NON_WORKING");
  });
});

describe("isEmployedOn (F-1 — employment-date coverage)", () => {
  it("covers joined-before, joined-on, joins-after, LWD-on, LWD-before, open-ended, no-employment-data", () => {
    const ongoing = { id: "a", first_name: "A", last_name: null, employee_code: "A", employment_joining_date: "2026-01-10", employment_last_working_day: null };
    expect(isEmployedOn(ongoing, "2026-01-09")).toBe(false); // before joining
    expect(isEmployedOn(ongoing, "2026-01-10")).toBe(true); // on joining day
    expect(isEmployedOn(ongoing, "2026-12-31")).toBe(true); // still open-ended

    const terminated = { id: "b", first_name: "B", last_name: null, employee_code: "B", employment_joining_date: "2026-01-10", employment_last_working_day: "2026-06-30" };
    expect(isEmployedOn(terminated, "2026-06-30")).toBe(true); // LWD itself still counts
    expect(isEmployedOn(terminated, "2026-07-01")).toBe(false); // day after LWD excluded

    const preJoining = { id: "c", first_name: "C", last_name: null, employee_code: "C" };
    expect(isEmployedOn(preJoining, "2026-01-01")).toBe(false); // no employment row at all
  });

  it("for multiple employment spells, only the governing (latest) spell is carried by EmployeeLite", () => {
    // EmployeeLite only ever carries ONE spell (the latest, per the backend's
    // `list_latest_employments`) — a rehire's earlier, already-ended spell is irrelevant to any
    // date at or after the new spell's own joining date, since spells never overlap.
    const rehired = { id: "d", first_name: "D", last_name: null, employee_code: "D", employment_joining_date: "2026-08-01", employment_last_working_day: null };
    expect(isEmployedOn(rehired, "2026-03-01")).toBe(false); // during the old, superseded spell's gap
    expect(isEmployedOn(rehired, "2026-08-01")).toBe(true); // from the new spell's joining date
  });
});

describe("filters", () => {
  const emp: EmployeeLite[] = [
    {
      id: "e1",
      first_name: "Asha",
      last_name: "Rao",
      employee_code: "E-1",
      status: "ACTIVE",
      is_active: true,
      employment_joining_date: "2026-01-01",
      employment_last_working_day: null,
    },
    {
      id: "e2",
      first_name: "Ben",
      last_name: null,
      employee_code: "E-2",
      status: "PROBATION",
      is_active: true,
      employment_joining_date: "2026-01-01",
      employment_last_working_day: null,
    },
    {
      id: "e3",
      first_name: "Cy",
      last_name: null,
      employee_code: "E-3",
      status: "ACTIVE",
      is_active: false,
      employment_joining_date: "2026-01-01",
      employment_last_working_day: null,
    },
  ];
  const byId = indexEmployees(emp);
  const rows = [
    makeDay({ employee_id: "e1", shift_id: "s1" }),
    makeDay({ employee_id: "e2", shift_id: "s2" }),
  ];

  it("applies population filters (employee, shift, employment status)", () => {
    expect(applyPopulationFilters(rows, { ...DEFAULT_FILTERS, employeeId: "e2" }, byId)).toHaveLength(1);
    expect(applyPopulationFilters(rows, { ...DEFAULT_FILTERS, shiftId: "s1" }, byId).map((d) => d.employee_id)).toEqual(["e1"]);
    expect(applyPopulationFilters(rows, { ...DEFAULT_FILTERS, employeeStatus: "PROBATION" }, byId).map((d) => d.employee_id)).toEqual(["e2"]);
  });

  it("drill filters narrow by bucket and by flag", () => {
    const mixed = [makeDay({ employee_id: "e1", is_late: true }), makeAbsentDay({ employee_id: "e2" })];
    expect(applyDrillFilters(mixed, { ...DEFAULT_FILTERS, bucket: "ABSENT" }).map((d) => d.employee_id)).toEqual(["e2"]);
    expect(applyDrillFilters(mixed, { ...DEFAULT_FILTERS, flag: "late" }).map((d) => d.employee_id)).toEqual(["e1"]);
  });

  it("lists active employees with no row on the focus date, honouring filters", () => {
    const focusDate = "2026-08-10"; // matches makeDay's default attendance_date
    const result = employeesWithoutRecord([makeDay({ employee_id: "e1" })], emp, DEFAULT_FILTERS, focusDate);
    expect(result.map((e) => e.id)).toEqual(["e2"]); // e3 is inactive, e1 has a row
    expect(employeesWithoutRecord([], emp, { ...DEFAULT_FILTERS, shiftId: "s1" }, focusDate)).toEqual([]);
  });

  it("excludes a terminated employee from 'no record yet' once their last working day has passed (F-1)", () => {
    const terminated: EmployeeLite = {
      id: "e4",
      first_name: "Meera",
      last_name: "Rao",
      employee_code: "E-4",
      status: "PROBATION", // deliberately not kept in sync with employment status (D-1) —
      is_active: true, //   is_active/status alone must not be trusted for this decision.
      employment_joining_date: "2026-01-01",
      employment_last_working_day: "2026-09-20",
    };
    const population = [...emp, terminated];
    // Viewed "today" = 2026-10-05, over two weeks after her last working day.
    const result = employeesWithoutRecord([], population, DEFAULT_FILTERS, "2026-10-05");
    expect(result.map((e) => e.id)).not.toContain("e4");
  });

  it("includes a genuinely active employee with no row yet, regardless of wall-clock date (F-1)", () => {
    const active: EmployeeLite = {
      id: "e5",
      first_name: "Nina",
      last_name: "Shah",
      employee_code: "E-5",
      status: "ACTIVE",
      is_active: true,
      employment_joining_date: "2026-01-01",
      employment_last_working_day: null,
    };
    // Same calculation, two different "today"s one day apart — same inputs, same result.
    const resultOnDay1 = employeesWithoutRecord([], [active], DEFAULT_FILTERS, "2026-10-04");
    const resultOnDay2 = employeesWithoutRecord([], [active], DEFAULT_FILTERS, "2026-10-04");
    expect(resultOnDay1.map((e) => e.id)).toEqual(["e5"]);
    expect(resultOnDay2.map((e) => e.id)).toEqual(resultOnDay1.map((e) => e.id));
  });

  it("excludes an employee before their joining date and includes them on it (F-1)", () => {
    const joiner: EmployeeLite = {
      id: "e6",
      first_name: "Omar",
      last_name: "Khan",
      employee_code: "E-6",
      status: "ACTIVE",
      is_active: true,
      employment_joining_date: "2026-09-15",
      employment_last_working_day: null,
    };
    expect(employeesWithoutRecord([], [joiner], DEFAULT_FILTERS, "2026-09-14").map((e) => e.id)).toEqual([]);
    expect(employeesWithoutRecord([], [joiner], DEFAULT_FILTERS, "2026-09-15").map((e) => e.id)).toEqual(["e6"]);
  });

  it("includes an employee whose last working day equals the focus date (F-1)", () => {
    const lastDay: EmployeeLite = {
      id: "e7",
      first_name: "Priya",
      last_name: "Nair",
      employee_code: "E-7",
      status: "ACTIVE",
      is_active: true,
      employment_joining_date: "2026-01-01",
      employment_last_working_day: "2026-09-20",
    };
    expect(employeesWithoutRecord([], [lastDay], DEFAULT_FILTERS, "2026-09-20").map((e) => e.id)).toEqual(["e7"]);
    expect(employeesWithoutRecord([], [lastDay], DEFAULT_FILTERS, "2026-09-21").map((e) => e.id)).toEqual([]);
  });

  it("falls back to a short id when an employee isn't in the directory", () => {
    expect(employeeName(undefined, "abcdef1234")).toBe("Employee abcdef12");
    expect(employeeName(emp[0], "e1")).toBe("Asha Rao");
  });
});

describe("buildTrend", () => {
  const range = { from: "2026-10-05", to: "2026-10-07" };
  // The summary's per-day counts (9 hours worked per checked-in day).
  const rows = [
    makeSummaryDay("2026-10-05", { expected: 2, present: 1, absent: 1, checked_in: 1, worked_minutes: 540 }),
    makeSummaryDay("2026-10-06", { expected: 2, present: 2, late: 1, checked_in: 2, worked_minutes: 1080 }),
    // 2026-10-07: only a weekly off → nobody expected
    makeSummaryDay("2026-10-07"),
  ];

  it("computes present % over employees expected to work", () => {
    const points = buildTrend(rows, range, "present_pct", "daily");
    expect(points.map((p) => p.value)).toEqual([50, 100, null]);
  });

  it("leaves a gap (null) instead of a fabricated 0 when nobody was expected", () => {
    const last = buildTrend(rows, range, "present_pct", "daily")[2];
    expect(last.value).toBeNull();
    expect(last.denominator).toBe(0);
  });

  it("computes late % over checked-in employees and average hours", () => {
    expect(buildTrend(rows, range, "late_pct", "daily")[1].value).toBe(50);
    expect(buildTrend(rows, range, "avg_hours", "daily")[0].value).toBe(9);
  });

  it("aggregates weekly from the same days by summing numerators and denominators", () => {
    const weekly = buildTrend(rows, range, "present_pct", "weekly");
    expect(weekly).toHaveLength(1);
    expect(weekly[0].numerator).toBe(3);
    expect(weekly[0].denominator).toBe(4);
    expect(weekly[0].value).toBe(75);
  });
});

describe("work hours + overtime", () => {
  it("summarises hours from the backend's own minutes", () => {
    const rows = [
      makeDay({ worked_minutes: 480, scheduled_minutes: 540 }), // short, complete day
      makeDay({ employee_id: "e2", worked_minutes: 600, scheduled_minutes: 540, ot_minutes_detected: 60, ot_minutes_approved: 30 }),
      makeAbsentDay({ employee_id: "e3" }),
    ];
    const s = summarizeWorkHours(rows);
    expect(s.totalMinutes).toBe(1080);
    expect(s.checkedInDays).toBe(2);
    expect(s.avgMinutes).toBe(540);
    expect(s.expectedMinutes).toBe(1080);
    expect(s.deviationMinutes).toBe(0);
    expect(s.underTimeMinutes).toBe(60);
    expect(s.otDetectedMinutes).toBe(60);
    expect(s.otApprovedMinutes).toBe(30);
  });

  it("does not count leave or absent days toward expected hours", () => {
    const s = summarizeWorkHours([makeDay({ attendance_status: "LEAVE", actual_first_in: null, worked_minutes: 0 })]);
    expect(s.expectedMinutes).toBe(0);
    expect(s.avgMinutes).toBeNull();
  });

  it("builds a per-day series covering every date in the range", () => {
    const series = dailyHours([makeDay({ attendance_date: "2026-10-05" })], { from: "2026-10-05", to: "2026-10-06" });
    expect(series.map((d) => d.workedMinutes)).toEqual([540, 0]);
    expect(series[0].scheduledMinutes).toBe(540);
  });

  it("summarises overtime records: totals, status split, day class and trend", () => {
    const base = {
      company_id: "c",
      attendance_day_id: "d",
      overtime_policy_version_id: "p",
      classification_code: null,
      configured_multiplier: null,
    };
    const records = [
      { ...base, id: "1", employee_id: "e1", attendance_date: "2026-10-05", day_class: "NORMAL", minutes_detected: 60, minutes_approved: 60, status: "APPROVED" },
      { ...base, id: "2", employee_id: "e2", attendance_date: "2026-10-05", day_class: "HOLIDAY", minutes_detected: 120, minutes_approved: 0, status: "PENDING" },
      { ...base, id: "3", employee_id: "e1", attendance_date: "2026-10-06", day_class: "NORMAL", minutes_detected: 30, minutes_approved: 0, status: "REJECTED" },
    ] as unknown as OvertimeRecord[];
    const s = summarizeOvertime(records, { from: "2026-10-05", to: "2026-10-06" });
    expect(s.totalDetectedMinutes).toBe(210);
    expect(s.totalApprovedMinutes).toBe(60);
    expect(s.employees).toBe(2);
    expect(s.avgDetectedPerEmployee).toBe(105);
    expect(s.pendingCount).toBe(1);
    expect(s.pendingMinutes).toBe(120);
    expect(s.approvedCount).toBe(1);
    expect(s.rejectedCount).toBe(1);
    expect(s.byDayClass[0]).toEqual({ dayClass: "HOLIDAY", minutes: 120 });
    expect(s.trend.map((t) => t.minutes)).toEqual([180, 30]);
  });
});

describe("buildAttentionItems", () => {
  const regs = [{ id: "r1", employee_id: "e1" }, { id: "r2", employee_id: "e2" }] as unknown as RegularizationRequest[];
  const blocked = [{ id: "p1", status: "OPEN", last_validation_status: "BLOCKED" }] as unknown as AttendancePeriod[];

  it("returns nothing when there is nothing to act on", () => {
    expect(buildAttentionItems({ rows: [makeDay()], pendingRegularizations: [], pendingOvertimeCount: 0, blockedPeriods: [] })).toEqual([]);
  });

  it("orders by severity, carries counts and affected employees, and only links real destinations", () => {
    const rows = [
      makeDay({ employee_id: "e1", attendance_status: "CONFIG_ERROR" }),
      makeDay({ employee_id: "e2", missing_punch: true }),
      makeDay({ employee_id: "e2", attendance_date: "2026-08-11", missing_punch: true }),
      makeDay({ employee_id: "e3", is_late: true }),
      makeDay({ employee_id: "e4", is_early_out: true }),
      makeDay({ employee_id: "e5", work_on_leave_flagged: true }),
      makeDay({ employee_id: "e6", work_on_leave_flagged: true, work_on_leave_resolution: "KEEP_LEAVE" }), // resolved → not an issue
    ];
    const items = buildAttentionItems({ rows, pendingRegularizations: regs, pendingOvertimeCount: 4, blockedPeriods: blocked });
    expect(items.map((i) => i.key)).toEqual([
      "config_error",
      "period_blocked",
      "missing_punch",
      "pending_regularization",
      "work_on_leave",
      "pending_overtime",
      "late",
      "early_out",
    ]);
    const missing = items.find((i) => i.key === "missing_punch");
    expect(missing).toMatchObject({ count: 2, employees: 1, flag: "missing_punch" });
    expect(items.find((i) => i.key === "work_on_leave")?.count).toBe(1);
    expect(items.find((i) => i.key === "pending_regularization")).toMatchObject({ count: 2, employees: 2, href: "/app/regularizations" });
    expect(items.find((i) => i.key === "period_blocked")?.href).toBe("/app/attendance-periods/p1");
  });

  it("skips sources that failed to load (null) rather than reporting zero", () => {
    const items = buildAttentionItems({ rows: [], pendingRegularizations: null, pendingOvertimeCount: null, blockedPeriods: null });
    expect(items).toEqual([]);
  });
});

describe("absence, muster, month and period helpers", () => {
  it("flags repeat absence only at the threshold", () => {
    const rows = [
      ...["05", "06", "07"].map((d) => makeAbsentDay({ employee_id: "e1", attendance_date: `2026-10-${d}` })),
      makeAbsentDay({ employee_id: "e2", attendance_date: "2026-10-05" }),
    ];
    expect(repeatAbsences(rows).map((r) => r.employeeId)).toEqual(["e1"]);
  });

  it("builds a muster sorted by name over the visible dates only", () => {
    const byId = indexEmployees([
      { id: "e1", first_name: "Zed", last_name: null, employee_code: null },
      { id: "e2", first_name: "Amy", last_name: null, employee_code: null },
    ]);
    const dates = ["2026-10-05", "2026-10-06"];
    const muster = buildMuster(
      [makeDay({ employee_id: "e1", attendance_date: "2026-10-05" }), makeDay({ employee_id: "e2", attendance_date: "2026-10-06" }), makeDay({ employee_id: "e2", attendance_date: "2026-09-01" })],
      dates,
      byId,
    );
    expect(muster.rows.map((r) => r.name)).toEqual(["Amy", "Zed"]);
    expect(muster.rows[0].cells.size).toBe(1);
  });

  it("limits the muster to the last 31 days", () => {
    expect(musterDates({ from: "2026-01-01", to: "2026-03-31" })).toHaveLength(31);
    expect(musterDates({ from: "2026-03-30", to: "2026-03-31" })).toHaveLength(2);
  });

  it("lays a month into Monday-first weeks", () => {
    const grid = monthGrid("2026-10", new Map());
    expect(grid.every((w) => w.length === 7)).toBe(true);
    expect(grid[0].slice(0, 3)).toEqual([null, null, null]); // 1 Oct 2026 is a Thursday
    expect(grid.flat().filter(Boolean)).toHaveLength(31);
  });

  it("summarises a month for one employee", () => {
    const s = summarizeMonth([
      makeDay({ attendance_date: "2026-10-01", is_late: true, ot_minutes_detected: 30 }),
      makeAbsentDay({ attendance_date: "2026-10-02" }),
      makeDay({ attendance_date: "2026-10-03", attendance_status: "LEAVE", actual_first_in: null, worked_minutes: 0 }),
    ]);
    expect(s.counts.PRESENT).toBe(1);
    expect(s.counts.ABSENT).toBe(1);
    expect(s.counts.LEAVE).toBe(1);
    expect(s.late).toBe(1);
    expect(s.otDetectedMinutes).toBe(30);
    expect(s.workedMinutes).toBe(540);
  });

  it("derives presence from punches and open breaks", () => {
    expect(presenceOf(makeDay())).toBe("CHECKED_OUT");
    expect(presenceOf(makeDay({ actual_last_out: null }))).toBe("WORKING");
    expect(
      presenceOf(
        makeDay({ actual_last_out: null, breaks: [{ id: "b", attendance_day_id: "d", shift_break_id: null, break_start: "2026-08-10T13:00:00Z", break_end: null, minutes: 0, is_paid: false, is_excess: false }] }),
      ),
    ).toBe("ON_BREAK");
    expect(presenceOf(makeAbsentDay())).toBe("NOT_CHECKED_IN");
  });

  it("sums the period summary, treating pre-PAY-002 nulls honestly", () => {
    const row = (over: Partial<AttendancePeriodSummaryRow>): AttendancePeriodSummaryRow => ({
      employee_id: "e",
      present_days: "20",
      absent_days: "1",
      leave_days: "2",
      holiday_days: "1",
      weekly_off_days: "4",
      half_days: "1",
      lop_days: "0.5",
      on_duty_days: null,
      incomplete_days: null,
      not_employed_days: null,
      unpaid_off_days: null,
      paid_days: "29.5",
      payable_days: "29.5",
      ot_minutes_normal: 60,
      ot_minutes_weekly_off: 30,
      ot_minutes_holiday: 0,
      ot_minutes_night: 15,
      comp_off_minutes_earned: 0,
      late_count: 2,
      worked_minutes_total: 9000,
      generated_at: "2026-10-01T00:00:00Z",
      frozen: true,
      ...over,
    });
    const totals = sumPeriodSummary([row({}), row({ employee_id: "e2", on_duty_days: "2" })]);
    expect(totals.employees).toBe(2);
    expect(totals.presentDays).toBe(40);
    expect(totals.lopDays).toBe(1);
    expect(totals.payableDays).toBe(59);
    expect(totals.onDutyDays).toBe(2); // only one row reports it
    expect(totals.incompleteDays).toBeNull(); // nobody reports it → unknown, not 0
    expect(totals.otMinutes).toBe(210);
    expect(totals.frozen).toBe(true);
    expect(sumPeriodSummary([row({}), row({ frozen: false })]).frozen).toBe(false);
  });

  it("picks the period covering today, else the most recent", () => {
    const p = (id: string, start: string, end: string) => ({ id, period_start: start, period_end: end }) as AttendancePeriod;
    const periods = [p("sep", "2026-09-01", "2026-09-30"), p("oct", "2026-10-01", "2026-10-31")];
    expect(pickDefaultPeriod(periods, "2026-10-07")?.id).toBe("oct");
    expect(pickDefaultPeriod(periods, "2026-12-01")?.id).toBe("oct");
    expect(pickDefaultPeriod([], "2026-10-07")).toBeNull();
  });
});

describe("department and branch filters", () => {
  const days = [
    makeDay({ employee_id: "a", attendance_date: TODAY }),
    makeDay({ employee_id: "b", attendance_date: TODAY }),
    makeDay({ employee_id: "c", attendance_date: TODAY }),
  ];
  const ENG = "11111111-1111-4111-8111-111111111111";
  const SALES = "22222222-2222-4222-8222-222222222222";
  const PUNE = "33333333-3333-4333-8333-333333333333";
  const directory = new Map([
    ["a", { department_id: ENG, branch_id: PUNE }],
    ["b", { department_id: SALES, branch_id: PUNE }],
    ["c", { department_id: null, branch_id: null }],
  ]);
  const none = new Map();

  it("round-trips ids (and \"unassigned\") through the URL under short names", () => {
    const filters = { ...DEFAULT_FILTERS, department: SALES, branch: "unassigned" };
    const params = serializeFilters(filters);
    expect(params.get("dept")).toBe(SALES);
    expect(params.get("branch")).toBe("unassigned");
    expect(parseFilters(params)).toEqual(filters);
    expect(parseFilters(new URLSearchParams())).toEqual(DEFAULT_FILTERS);
  });

  it("drops an old link that named the department instead of giving its id", () => {
    expect(parseFilters(new URLSearchParams("dept=Sales&branch=Pune"))).toEqual(DEFAULT_FILTERS);
  });

  it("keeps only the employees in that department or branch", () => {
    const ids = (f: Partial<typeof DEFAULT_FILTERS>) =>
      applyPopulationFilters(days, { ...DEFAULT_FILTERS, ...f }, none, directory).map((d) => d.employee_id);
    expect(ids({ department: ENG })).toEqual(["a"]);
    expect(ids({ branch: PUNE })).toEqual(["a", "b"]);
    expect(ids({ department: SALES, branch: PUNE })).toEqual(["b"]);
    expect(ids({ department: "unassigned" })).toEqual(["c"]);
  });

  it("skips the filter, rather than hiding everyone, when there is no directory yet", () => {
    expect(applyPopulationFilters(days, { ...DEFAULT_FILTERS, department: SALES }, none)).toHaveLength(3);
  });

  it("counts as an active filter", () => {
    expect(hasActiveFilters({ ...DEFAULT_FILTERS, department: SALES })).toBe(true);
  });

  it("does not bring filtered-out employees back as 'no record yet'", () => {
    const employees = [
      { id: "a", first_name: "A", last_name: null, employee_code: null, status: "ACTIVE", is_active: true, employment_joining_date: "2020-01-01", employment_last_working_day: null },
      { id: "b", first_name: "B", last_name: null, employee_code: null, status: "ACTIVE", is_active: true, employment_joining_date: "2020-01-01", employment_last_working_day: null },
    ];
    const filters = { ...DEFAULT_FILTERS, department: ENG };
    // Neither has a row yet; only A is in Engineering.
    const missing = employeesWithoutRecord([], employees, filters, TODAY, directory);
    expect(missing.map((e) => e.id)).toEqual(["a"]);
  });
});
