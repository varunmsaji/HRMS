import { describe, expect, it } from "vitest";

import { buildHrCalendar, filterRows, monthDates, shiftMonth } from "./hr-calendar";
import type { AttendanceDay } from "./types";

const day = (employee_id: string, attendance_date: string, over: Partial<AttendanceDay> = {}): AttendanceDay =>
  ({ id: `${employee_id}-${attendance_date}`, employee_id, attendance_date, attendance_status: "PRESENT", is_late: false, ...over }) as AttendanceDay;

describe("monthDates / shiftMonth", () => {
  it("lists every date of the month", () => {
    expect(monthDates("2026-02")).toHaveLength(28);
    expect(monthDates("2026-10")[30]).toBe("2026-10-31");
  });
  it("moves across year boundaries", () => {
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
  });
});

describe("buildHrCalendar", () => {
  const dates = monthDates("2026-10");
  const emps = [
    { id: "a", first_name: "Asha", last_name: "Rao", employee_code: "E1" },
    { id: "b", first_name: "Ben", last_name: null, employee_code: "E2" },
  ];

  it("counts present, absent, leave and late per person and keeps people with no records", () => {
    const rows = buildHrCalendar(
      [
        day("a", "2026-10-01"),
        day("a", "2026-10-02", { is_late: true }),
        day("a", "2026-10-03", { attendance_status: "ABSENT" }),
        day("a", "2026-10-04", { attendance_status: "LEAVE" }),
        day("a", "2026-10-05", { attendance_status: "HALF_DAY" }),
        day("a", "2026-09-30"),
      ],
      emps,
      dates,
    );
    const a = rows.find((r) => r.employeeId === "a")!;
    expect(a).toMatchObject({ present: 2.5, absent: 1, leave: 1, late: 1 });
    expect(a.cells.size).toBe(5); // the September row is outside the month
    expect(rows.find((r) => r.employeeId === "b")?.cells.size).toBe(0);
  });

  it("filters by name or code", () => {
    const rows = buildHrCalendar([], emps, dates);
    expect(filterRows(rows, "e2").map((r) => r.employeeId)).toEqual(["b"]);
    expect(filterRows(rows, "asha")).toHaveLength(1);
  });
});
