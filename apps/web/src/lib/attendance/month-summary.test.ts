import { describe, expect, it } from "vitest";

import type { CalendarRow } from "@/lib/attendance/hr-calendar";
import { withPayrollTotals } from "@/lib/attendance/hr-calendar";
import {
  approvedOvertimeMinutes,
  formatPayrollDays,
  monthSummaryPath,
  type MonthSummaryRow,
} from "@/lib/attendance/month-summary";

const payroll = (over: Partial<MonthSummaryRow>): MonthSummaryRow => ({
  employee_id: "e1",
  present_days: "0.00",
  absent_days: "0.00",
  leave_days: "0.00",
  holiday_days: "0.00",
  weekly_off_days: "0.00",
  half_days: "0.00",
  lop_days: "0.00",
  on_duty_days: "0.00",
  paid_days: "0.00",
  payable_days: "0.00",
  late_count: 0,
  ot_minutes_normal: 0,
  ot_minutes_weekly_off: 0,
  ot_minutes_holiday: 0,
  ot_minutes_night: 0,
  frozen: false,
  ...over,
});

const row = (employeeId: string): CalendarRow => ({
  employeeId,
  name: employeeId,
  code: null,
  cells: new Map(),
  present: 99,
  absent: 99,
  leave: 99,
  late: 99,
});

describe("month summary helpers", () => {
  it("builds one request for many employees", () => {
    expect(monthSummaryPath("2026-09", ["a", "b"])).toBe("/attendance/month-summary?month=2026-09&employee_id=a&employee_id=b");
  });

  it("shows days without trailing zeros", () => {
    expect(formatPayrollDays("1.50")).toBe("1.5");
    expect(formatPayrollDays("21.00")).toBe("21");
    expect(formatPayrollDays(null)).toBe("–");
  });

  it("adds approved overtime across classes", () => {
    expect(approvedOvertimeMinutes(payroll({ ot_minutes_normal: 30, ot_minutes_night: 15, ot_minutes_holiday: 5 }))).toBe(50);
  });

  it("replaces a row's totals with the payroll figures (half-day leave is half leave, half present)", () => {
    const rows = withPayrollTotals(
      [row("e1"), row("e2")],
      [payroll({ present_days: "1.50", leave_days: "1.50", half_days: "1.00", absent_days: "1.00", late_count: 2 })],
    );
    expect(rows[0]).toMatchObject({ present: 2, leave: 1.5, absent: 1, late: 2 });
    // No payroll entry for e2: its own totals stay.
    expect(rows[1]).toMatchObject({ present: 99, leave: 99 });
  });
});
