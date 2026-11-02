import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CalendarGrid } from "@/components/attendance/hr-calendar/calendar-grid";
import { buildHrCalendar, monthDates } from "@/lib/attendance/hr-calendar";
import type { AttendanceDay } from "@/lib/attendance/types";

const dates = monthDates("2026-10");
const day = (over: Partial<AttendanceDay>): AttendanceDay =>
  ({
    id: "d1",
    employee_id: "a",
    attendance_date: "2026-10-05",
    timezone: "Asia/Kolkata",
    attendance_status: "PRESENT",
    is_late: false,
    worked_minutes: 480,
    actual_first_in: "2026-10-05T03:45:00Z",
    actual_last_out: "2026-10-05T12:45:00Z",
    ...over,
  }) as AttendanceDay;

describe("CalendarGrid", () => {
  const rows = buildHrCalendar(
    [day({}), day({ id: "d2", attendance_date: "2026-10-06", attendance_status: "ABSENT", actual_first_in: null, actual_last_out: null })],
    [
      { id: "a", first_name: "Asha", last_name: "Rao", employee_code: "E1" },
      { id: "b", first_name: "Ben", last_name: null, employee_code: "E2" },
    ],
    dates,
  );

  it("shows everyone, with a status box per recorded day and totals", () => {
    render(<CalendarGrid rows={rows} dates={dates} today="2026-10-20" onPickDay={vi.fn()} onPickEmployee={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Asha Rao" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Ben" })).toBeInTheDocument(); // no records, still listed
    expect(screen.getByRole("button", { name: /Asha Rao, 05 Oct: Present/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Asha Rao, 06 Oct: Absent/ })).toBeInTheDocument();
  });

  it("reports which day or person was clicked", async () => {
    const onPickDay = vi.fn();
    const onPickEmployee = vi.fn();
    const user = userEvent.setup();
    render(<CalendarGrid rows={rows} dates={dates} today="2026-10-20" onPickDay={onPickDay} onPickEmployee={onPickEmployee} />);
    await user.click(screen.getByRole("button", { name: /05 Oct: Present/ }));
    expect(onPickDay.mock.calls[0][0].employeeId).toBe("a");
    expect(onPickDay.mock.calls[0][1].id).toBe("d1");
    await user.click(screen.getByRole("button", { name: "Asha Rao" }));
    expect(onPickEmployee.mock.calls[0][0].employeeId).toBe("a");
  });
});
