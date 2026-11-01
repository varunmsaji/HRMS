import { describe, expect, it } from "vitest";

import { buildTimeline, punchesForDay, summarizeDay } from "./day-detail";
import type { AttendanceDay, Punch } from "./types";

const day = (over: Partial<AttendanceDay> = {}): AttendanceDay =>
  ({
    attendance_status: "PRESENT",
    calendar_day_type: "WORKING",
    holiday_name: null,
    scheduled_start: "2026-08-10T09:00:00Z",
    scheduled_end: "2026-08-10T18:00:00Z",
    scheduled_minutes: 540,
    actual_first_in: "2026-08-10T09:25:00Z",
    actual_last_out: "2026-08-10T17:20:00Z",
    worked_minutes: 475,
    missing_punch: false,
    is_late: true,
    late_minutes: 25,
    is_early_out: true,
    early_departure_minutes: 40,
    is_overtime: false,
    ot_minutes_detected: 0,
    is_regularized: false,
    worked_on_holiday: false,
    worked_on_weekly_off: false,
    on_duty: false,
    is_locked: false,
    is_pending_approval: false,
    is_core_hours_breach: false,
    work_on_leave_flagged: false,
    work_on_leave_resolution: null,
    ...over,
  }) as AttendanceDay;

const punch = (id: string, time: string, direction: "IN" | "OUT", source = "WEB"): Punch =>
  ({ id, punch_time: time, direction, source }) as Punch;

describe("summarizeDay", () => {
  it("states worked vs scheduled and lists problems", () => {
    const s = summarizeDay(day());
    expect(s.headline).toBe("7h 55m worked of 9h 0m scheduled.");
    expect(s.problems).toEqual(["Late by 0h 25m", "Left 0h 40m early"]);
  });

  it("describes leave, weekly off and absent days", () => {
    expect(summarizeDay(day({ attendance_status: "LEAVE" })).headline).toBe("On approved leave.");
    expect(summarizeDay(day({ attendance_status: "NOT_EXPECTED", actual_first_in: null })).headline).toBe(
      "Weekly off — no work expected.",
    );
    expect(summarizeDay(day({ attendance_status: "ABSENT", actual_first_in: null, worked_minutes: 0 })).headline).toBe(
      "No attendance recorded for a scheduled day.",
    );
  });
});

describe("buildTimeline", () => {
  it("orders punches and break events and labels sources", () => {
    const items = buildTimeline(
      day(),
      [punch("2", "2026-08-10T17:20:00Z", "OUT", "MOBILE"), punch("1", "2026-08-10T09:25:00Z", "IN")],
      [{ id: "b1", event_type: "START", event_time: "2026-08-10T13:00:00Z", break_name: "Lunch", source: "WEB" }],
    );
    expect(items.map((i) => i.label)).toEqual(["Punched in", "Break started — Lunch", "Punched out"]);
    expect(items[2].source).toBe("Mobile app");
  });

  it("ends with a gap marker when the day is missing its punch-out", () => {
    const items = buildTimeline(day({ missing_punch: true }), [punch("1", "2026-08-10T09:25:00Z", "IN")], []);
    expect(items[items.length - 1].kind).toBe("MISSING_OUT");
  });

  it("drops punches far outside the day's window", () => {
    const kept = punchesForDay(
      [punch("1", "2026-08-10T09:00:00Z", "IN"), punch("2", "2026-08-12T09:00:00Z", "IN")],
      day(),
    );
    expect(kept.map((p) => p.id)).toEqual(["1"]);
  });
});

import { exceptionLabels, minutesSince, rangePresets } from "./day-detail";

describe("exceptionLabels", () => {
  it("lists each problem once and nothing for a clean day", () => {
    expect(exceptionLabels(day())).toEqual([]);
    expect(exceptionLabels(day({ missing_punch: true, attendance_status: "INCOMPLETE", is_pending_approval: true }))).toEqual([
      "Missing punch",
      "Pending approval",
    ]);
  });
});

describe("minutesSince", () => {
  it("counts whole minutes and rejects missing or future times", () => {
    const now = new Date("2026-08-10T12:30:30Z");
    expect(minutesSince("2026-08-10T09:25:00Z", now)).toBe(185);
    expect(minutesSince(null, now)).toBeNull();
    expect(minutesSince("2026-08-10T13:00:00Z", now)).toBeNull();
  });
});

describe("rangePresets", () => {
  it("is anchored to the business date", () => {
    const p = Object.fromEntries(rangePresets("2026-11-01").map((r) => [r.key, r]));
    expect(p["7d"]).toMatchObject({ from: "2026-10-26", to: "2026-11-01" });
    expect(p["month"]).toMatchObject({ from: "2026-11-01", to: "2026-11-01" });
    expect(p["last-month"]).toMatchObject({ from: "2026-10-01", to: "2026-10-31" });
  });
});
