import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { bucketOf } from "@/lib/attendance/dashboard";
import { overtimeTotals, tallyByEmployee, type EmployeeTally } from "@/lib/attendance/report-basis";
import type { AttendanceDay } from "@/lib/attendance/types";
import type { OvertimeRecord } from "@/lib/overtime/types";

// The shared parity fixture: mobile (`test/metrics_parity_test.dart`) and the API's export tally
// (`tests/unit/modules/attendance/test_report_parity.py`) load the same file and must agree.
interface Fixture {
  days: AttendanceDay[];
  overtime: OvertimeRecord[];
  expected: {
    buckets: Record<string, string>;
    tallies: Record<string, Omit<EmployeeTally, "id">>;
    late_early_day_ids: string[];
    late_day_ids: string[];
    overtime_totals: { found: number; approved: number; pending: number };
  };
}

const fixture = JSON.parse(
  readFileSync(path.resolve(process.cwd(), "../api/tests/fixtures/attendance_metrics_parity.json"), "utf-8"),
) as Fixture;

describe("attendance metrics parity (shared with mobile and the API)", () => {
  it("puts each day in the same bucket", () => {
    for (const day of fixture.days) expect(bucketOf(day), day.id).toBe(fixture.expected.buckets[day.id]);
  });

  it("gives the same Present / absent and Work hours rows", () => {
    const got = Object.fromEntries(tallyByEmployee(fixture.days).map(({ id, ...t }) => [id, t]));
    expect(got).toEqual(fixture.expected.tallies);
  });

  it("lists the same late / early days, and reads late from the flag", () => {
    expect(fixture.days.filter((d) => d.is_late || d.is_early_out).map((d) => d.id)).toEqual(fixture.expected.late_early_day_ids);
    expect(fixture.days.filter((d) => d.is_late).map((d) => d.id)).toEqual(fixture.expected.late_day_ids);
  });

  it("adds overtime the same way", () => {
    expect(overtimeTotals(fixture.overtime)).toEqual(fixture.expected.overtime_totals);
  });
});
