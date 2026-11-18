import { describe, expect, it } from "vitest";

import { makeAbsentDay, makeDay } from "@/lib/attendance/__fixtures__/day";
import { isoToDatetimeLocal } from "@/lib/attendance/format";
import { mismatchOf } from "@/lib/attendance/mismatch";

describe("mismatchOf", () => {
  it("is null for a fine day, and for flags that only inform (late, early out, overtime)", () => {
    expect(mismatchOf(makeDay())).toBeNull();
    expect(mismatchOf(makeDay({ is_late: true, late_minutes: 20, is_early_out: true, is_overtime: true }))).toBeNull();
    expect(mismatchOf(makeAbsentDay())).toBeNull(); // nothing punched is a "not checked in" case, handled by Mark present
  });

  it("names a check-in with no check-out", () => {
    expect(mismatchOf(makeDay({ attendance_status: "INCOMPLETE", missing_punch: true, actual_last_out: null }))).toEqual({
      kind: "missing_out",
      reason: "Checked in but never checked out.",
    });
  });

  it("names a check-out with no check-in", () => {
    expect(mismatchOf(makeDay({ attendance_status: "INCOMPLETE", missing_punch: true, actual_first_in: null }))?.kind).toBe("missing_in");
  });

  it("calls an incomplete day with odd punches incomplete", () => {
    expect(mismatchOf(makeDay({ attendance_status: "INCOMPLETE" }))?.kind).toBe("incomplete");
  });

  it("says nothing was punched when an incomplete day has no punches at all", () => {
    expect(mismatchOf(makeDay({ attendance_status: "INCOMPLETE", missing_punch: true, actual_first_in: null, actual_last_out: null }))).toEqual({
      kind: "no_punches",
      reason: "Nothing was punched on a working day.",
    });
  });

  it("flags work on approved leave only until HR has decided", () => {
    expect(mismatchOf(makeDay({ work_on_leave_flagged: true, work_on_leave_resolution: null }))?.kind).toBe("work_on_leave");
    expect(mismatchOf(makeDay({ work_on_leave_flagged: true, work_on_leave_resolution: "KEEP_LEAVE" }))).toBeNull();
  });

  it("flags a config error and a day waiting on approval", () => {
    expect(mismatchOf(makeDay({ attendance_status: "CONFIG_ERROR" }))?.kind).toBe("config_error");
    expect(mismatchOf(makeDay({ is_pending_approval: true }))?.kind).toBe("pending_approval");
  });

  it("puts what blocks calculation ahead of the punches", () => {
    const day = makeDay({ attendance_status: "CONFIG_ERROR", missing_punch: true, actual_last_out: null });
    expect(mismatchOf(day)?.kind).toBe("config_error");
  });
});

describe("isoToDatetimeLocal", () => {
  it("reads a UTC instant as wall-clock time in the business zone, not the browser's", () => {
    expect(isoToDatetimeLocal("2026-11-18T04:00:00Z", "Asia/Kolkata")).toBe("2026-11-18T09:30");
    expect(isoToDatetimeLocal("2026-11-18T22:00:00Z", "Asia/Kolkata")).toBe("2026-11-19T03:30");
    expect(isoToDatetimeLocal("2026-11-18T04:00:00Z", "UTC")).toBe("2026-11-18T04:00");
  });
});
