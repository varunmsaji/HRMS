import { afterEach, describe, expect, it } from "vitest";

import {
  attendanceHref,
  DISTRIBUTION_BUCKETS,
  initialQueryValue,
  share,
  type AttendanceBuckets,
} from "@/lib/dashboard/overview";

describe("attendanceHref", () => {
  it("drills today's cards into the attendance screen's own bucket filter", () => {
    expect(attendanceHref("present", "2026-10-30", "2026-10-30")).toBe("/app/attendance?bucket=PRESENT");
    expect(attendanceHref("on_leave", "2026-10-30", "2026-10-30")).toBe("/app/attendance?bucket=LEAVE");
  });

  it("pins a historical date as a one-day custom range so the drill matches the card", () => {
    const href = attendanceHref("absent", "2026-10-28", "2026-10-30");
    expect(href).toContain("range=custom");
    expect(href).toContain("from=2026-10-28");
    expect(href).toContain("to=2026-10-28");
    expect(href).toContain("bucket=ABSENT");
  });

  it("uses a flag for overlays and opens unfiltered where the screen has no matching filter", () => {
    expect(attendanceHref("late", "2026-10-30", "2026-10-30")).toBe("/app/attendance?flag=late");
    expect(attendanceHref("not_checked_in", "2026-10-30", "2026-10-30")).toBe(
      "/app/attendance?flag=not_checked_in",
    );
    expect(attendanceHref("total", "2026-10-30", "2026-10-30")).toBe("/app/attendance");
  });
});

describe("share", () => {
  it("is null rather than 0% when there is nothing to divide by", () => {
    expect(share(0, 0)).toBeNull();
    expect(share(1, 4)).toBe(25);
  });
});

describe("DISTRIBUTION_BUCKETS", () => {
  it("lists every primary bucket exactly once so the bar can add up to the total", () => {
    const keys = DISTRIBUTION_BUCKETS.map((b) => b.key).sort();
    const expected: Array<keyof AttendanceBuckets> = [
      "absent", "incomplete", "no_record", "not_checked_in", "not_expected",
      "on_duty", "on_leave", "present", "remote_work",
    ];
    expect(keys).toEqual(expected.sort());
  });
});

describe("initialQueryValue", () => {
  afterEach(() => window.history.replaceState({}, "", "/"));

  it("returns an allow-listed value and ignores anything else", () => {
    window.history.replaceState({}, "", "/x?status=SUBMITTED");
    expect(initialQueryValue("status", ["SUBMITTED", "APPROVED"] as const)).toBe("SUBMITTED");
    window.history.replaceState({}, "", "/x?status=<script>");
    expect(initialQueryValue("status", ["SUBMITTED"] as const)).toBe("");
    window.history.replaceState({}, "", "/x");
    expect(initialQueryValue("status", ["SUBMITTED"] as const)).toBe("");
  });
});
