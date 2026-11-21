import { describe, expect, it } from "vitest";

import { overtimePending, overtimeTotals, REPORT_BASIS } from "@/lib/attendance/report-basis";

const rec = (status: string, detected: number, approved: number) =>
  ({ status, minutes_detected: detected, minutes_approved: approved }) as never;

describe("overtime totals", () => {
  it("counts pending only on records still waiting for a decision", () => {
    expect(overtimePending(rec("PENDING", 105, 90))).toBe(15);
    expect(overtimePending(rec("APPROVED", 105, 105))).toBe(0);
    expect(overtimePending(rec("AUTO_APPROVED", 60, 60))).toBe(0);
    expect(overtimePending(rec("REJECTED", 105, 0))).toBe(0);
  });

  it("sums found, approved and pending the way payroll reads them", () => {
    const totals = overtimeTotals([rec("PENDING", 100, 0), rec("APPROVED", 60, 60), rec("REJECTED", 40, 0)] as never);
    expect(totals).toEqual({ found: 200, approved: 60, pending: 100 });
  });
});

describe("report basis", () => {
  it("states a basis for every report, and says payroll pays approved overtime", () => {
    for (const key of ["daily", "present_absent", "late_early", "hours", "overtime", "payroll"] as const) {
      expect(REPORT_BASIS[key].length).toBeGreaterThan(20);
    }
    expect(REPORT_BASIS.overtime).toMatch(/approved minutes only/);
    expect(REPORT_BASIS.payroll).toMatch(/0\.5 each/);
  });
});
