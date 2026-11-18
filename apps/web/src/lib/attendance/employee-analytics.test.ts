import { describe, expect, it } from "vitest";

import { makeDay } from "@/lib/attendance/__fixtures__/day";
import {
  formatCountdown,
  formatDayCount,
  monthRange,
  monthStats,
  monthWeeks,
  todayStatus,
} from "@/lib/attendance/employee-analytics";
import type { Punch } from "@/lib/attendance/types";

const d = (date: string, o: Parameters<typeof makeDay>[0] = {}) => makeDay({ attendance_date: date, ...o });

function punch(direction: "IN" | "OUT", at: string): Punch {
  return {
    id: `p-${direction}-${at}`,
    company_id: "c",
    employee_id: "emp-1",
    punch_time: at,
    direction,
    source: "WEB",
    idempotency_key: null,
    recorded_by_user_id: null,
    reference: null,
    created_at: at,
  };
}

describe("monthStats", () => {
  it("counts days worked, absences, leave and days off, ignoring the future", () => {
    const days = [
      d("2026-08-03"),
      d("2026-08-04", { attendance_status: "HALF_DAY", worked_minutes: 240 }),
      d("2026-08-05", { attendance_status: "ABSENT", actual_first_in: null, worked_minutes: 0 }),
      d("2026-08-06", { attendance_status: "LEAVE", actual_first_in: null, worked_minutes: 0 }),
      d("2026-08-08", { attendance_status: "NOT_EXPECTED", calendar_day_type: "WEEKLY_OFF", actual_first_in: null }),
      d("2026-08-20"), // after today
    ];
    const s = monthStats(days, "2026-08-10");
    expect(s.expectedDays).toBe(4);
    expect(s.daysWorked).toBe(1.5);
    expect(s.absent).toBe(1);
    expect(s.leave).toBe(1);
    expect(s.daysOff).toBe(1);
    expect(s.halfDays).toBe(1);
    expect(s.workedMinutes).toBe(780);
    expect(s.avgWorkedMinutes).toBe(390);
  });

  it("measures lateness, early exits, overtime and punctuality", () => {
    const days = [
      d("2026-08-03", { is_late: true, late_minutes: 20 }),
      d("2026-08-04", { is_early_out: true, early_departure_minutes: 30 }),
      d("2026-08-05", { ot_minutes_detected: 60, ot_minutes_approved: 45 }),
      d("2026-08-06", { missing_punch: true }),
    ];
    const s = monthStats(days, "2026-08-31");
    expect(s.lateDays).toBe(1);
    expect(s.lateMinutes).toBe(20);
    expect(s.earlyOutDays).toBe(1);
    expect(s.earlyOutMinutes).toBe(30);
    expect(s.otDetectedMinutes).toBe(60);
    expect(s.otApprovedMinutes).toBe(45);
    expect(s.punctuality).toBe(75);
    expect(s.missingPunch).toBe(1);
  });

  it("leaves averages and punctuality empty when nothing was worked", () => {
    const s = monthStats([], "2026-08-10");
    expect(s.avgWorkedMinutes).toBeNull();
    expect(s.punctuality).toBeNull();
    expect(s.expectedDays).toBe(0);
  });
});

describe("formatDayCount", () => {
  it("shows a decimal only for half days", () => {
    expect(formatDayCount(18)).toBe("18");
    expect(formatDayCount(17.5)).toBe("17.5");
  });
});

describe("monthWeeks", () => {
  it("lays the month out Monday-first and pads the edges", () => {
    // 1 Aug 2026 is a Saturday: five blanks before it.
    const weeks = monthWeeks("2026-08", [d("2026-08-03")], "2026-08-10");
    expect(weeks[0].slice(0, 5)).toEqual([null, null, null, null, null]);
    expect(weeks[0][5]?.dayOfMonth).toBe(1);
    expect(weeks.every((w) => w.length === 7)).toBe(true);
    const all = weeks.flat().filter(Boolean);
    expect(all).toHaveLength(31);
    const third = all.find((c) => c?.date === "2026-08-03");
    expect(third?.bucket).toBe("PRESENT");
    expect(all.find((c) => c?.date === "2026-08-10")?.isToday).toBe(true);
    expect(all.find((c) => c?.date === "2026-08-11")?.isFuture).toBe(true);
    expect(all.find((c) => c?.date === "2026-08-02")?.day).toBeNull();
  });

  it("knows the month's bounds", () => {
    expect(monthRange("2026-02")).toEqual({ from: "2026-02-01", to: "2026-02-28" });
  });
});

describe("todayStatus", () => {
  const now = new Date("2026-08-10T10:00:00Z");

  it("is working after an IN punch, with the time since check-in", () => {
    const s = todayStatus(d("2026-08-10"), [punch("IN", "2026-08-10T09:00:00Z")], now);
    expect(s.state).toBe("WORKING");
    expect(s.workedMinutes).toBe(60);
    expect(s.minutesToShiftEnd).toBe(480);
  });

  it("is on a break when a break has started and not ended", () => {
    const day = d("2026-08-10", {
      breaks: [
        {
          id: "b",
          attendance_day_id: "x",
          shift_break_id: null,
          break_start: "2026-08-10T09:50:00Z",
          break_end: null,
          minutes: 0,
          is_paid: false,
          is_excess: false,
        },
      ],
    });
    expect(todayStatus(day, [punch("IN", "2026-08-10T09:00:00Z")], now).state).toBe("ON_BREAK");
  });

  it("is checked out after an OUT punch", () => {
    const s = todayStatus(
      d("2026-08-10", { worked_minutes: 300 }),
      [punch("OUT", "2026-08-10T09:50:00Z"), punch("IN", "2026-08-10T04:50:00Z")],
      now,
    );
    expect(s.state).toBe("CHECKED_OUT");
    expect(s.workedMinutes).toBe(300);
  });

  it("is not started before the shift, and not checked in after it began", () => {
    const day = d("2026-08-10", { actual_first_in: null });
    expect(todayStatus(day, [], new Date("2026-08-10T08:00:00Z")).state).toBe("NOT_STARTED");
    expect(todayStatus(day, [], now).state).toBe("NOT_CHECKED_IN");
  });

  it("reads leave, holidays and weekly offs from the day", () => {
    const off = { actual_first_in: null, attendance_status: "NOT_EXPECTED" as const };
    expect(todayStatus(d("2026-08-10", { ...off, attendance_status: "LEAVE" }), [], now).state).toBe("ON_LEAVE");
    expect(
      todayStatus(d("2026-08-10", { ...off, calendar_day_type: "HOLIDAY", holiday_name: "Diwali" }), [], now),
    ).toMatchObject({ state: "HOLIDAY", holidayName: "Diwali" });
    expect(todayStatus(d("2026-08-10", { ...off, calendar_day_type: "WEEKLY_OFF" }), [], now).state).toBe(
      "WEEKLY_OFF",
    );
  });

  it("lets a punch beat the holiday, and says no shift with nothing to go on", () => {
    const hol = d("2026-08-10", { attendance_status: "NOT_EXPECTED", calendar_day_type: "HOLIDAY" });
    expect(todayStatus(hol, [punch("IN", "2026-08-10T09:00:00Z")], now).state).toBe("WORKING");
    expect(todayStatus(null, [], now).state).toBe("NO_SHIFT");
  });
});

describe("formatCountdown", () => {
  it("formats hours and minutes", () => {
    expect(formatCountdown(130)).toBe("2h 10m");
    expect(formatCountdown(45)).toBe("45m");
    expect(formatCountdown(120)).toBe("2h");
    expect(formatCountdown(-5)).toBe("0m");
  });
});
