import { afterEach, describe, expect, it, vi } from "vitest";

import {
  businessToday,
  formatClockTime,
  formatDateTime,
  nowInZoneForDatetimeLocal,
  wallTimeToUtcIso,
  zoneLabel,
} from "@/lib/attendance/format";

describe("businessToday", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it.each([
    // `TZ-06`/`NEW-02` (execution gate §4, §9) — the deleted `todayIso()` returned the UTC
    // calendar date unconditionally. For any instant between 00:00 and 05:29 IST, that is one
    // day BEHIND the correct India business date.
    ["2026-10-01T00:00:00Z", "2026-10-01"], // 05:30 IST — UTC date already rolled over
    ["2026-09-30T23:59:00Z", "2026-10-01"], // 05:29 IST — UTC date still 30 Sep
    ["2026-09-30T21:30:00Z", "2026-10-01"], // 03:00 IST
    ["2026-09-30T19:00:00Z", "2026-10-01"], // 00:30 IST
    ["2026-09-30T12:00:00Z", "2026-09-30"], // 17:30 IST — ordinary daytime, no skew
  ])("returns the IST calendar date for %s -> %s", (utcInstant, expectedIstDate) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date(utcInstant));
    expect(businessToday("Asia/Kolkata")).toBe(expectedIstDate);
  });

  it("matches the naive UTC-date derivation for a UTC-configured tenant (regression guard)", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T23:59:00Z"));
    expect(businessToday("UTC")).toBe("2026-09-30");
  });

  it("is independent of the viewer's own browser/OS timezone", () => {
    // The test runner's own TZ (set via CI for exactly this reason, execution gate §13/Phase 6)
    // must not leak into the result — `businessToday` takes the zone explicitly rather than
    // reading `Intl.DateTimeFormat().resolvedOptions().timeZone`.
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-30T19:00:00Z")); // 00:30 IST, 1 Oct; 15:00 EDT, 30 Sep
    expect(businessToday("Asia/Kolkata")).toBe("2026-10-01");
    expect(businessToday("America/New_York")).toBe("2026-09-30");
  });
});

describe("zoneLabel", () => {
  it("labels Asia/Kolkata and its legacy alias as IST", () => {
    expect(zoneLabel("Asia/Kolkata")).toBe("IST");
    expect(zoneLabel("Asia/Calcutta")).toBe("IST");
  });

  it("falls back to the IANA identifier for any other zone, never a guess", () => {
    expect(zoneLabel("UTC")).toBe("UTC");
    expect(zoneLabel("America/New_York")).toBe("America/New_York");
  });
});

describe("formatClockTime / formatDateTime", () => {
  // `TZ-07` (execution gate §13) — a fixed instant renders `09:05 IST` regardless of the
  // viewer's own browser/OS timezone. No `vi.useFakeTimers()` needed: both functions take the
  // instant directly as an ISO string argument, never read the "current" clock.
  const instant = "2026-08-10T03:35:00Z"; // 09:05 IST

  it("renders a fixed instant as 09:05 IST, independent of the runner's own TZ", () => {
    expect(formatClockTime(instant, "Asia/Kolkata")).toBe("09:05 am IST");
  });

  it("renders the full date+time with the IST label", () => {
    expect(formatDateTime(instant, "Asia/Kolkata")).toContain("IST");
    expect(formatDateTime(instant, "Asia/Kolkata")).toContain("9:05");
  });

  it("never falls back to the viewer's own browser timezone", () => {
    // The test runner's TZ (CI: `America/New_York`) must not change the result — the same
    // instant renders identically regardless of which zone this test process happens to run in,
    // as long as the explicit `tz` argument is the same.
    expect(formatClockTime(instant, "Asia/Kolkata")).toBe("09:05 am IST");
  });

  it("renders a non-India zone with its own IANA identifier as the label", () => {
    // 03:35 UTC in America/New_York (EDT, -4) is 23:35 the previous day.
    expect(formatClockTime(instant, "America/New_York")).toBe("11:35 pm America/New_York");
  });

  it("returns an em dash for a null or undefined instant", () => {
    expect(formatClockTime(null, "Asia/Kolkata")).toBe("—");
    expect(formatClockTime(undefined, "Asia/Kolkata")).toBe("—");
    expect(formatDateTime(null, "Asia/Kolkata")).toBe("—");
  });
});

// `D1` (staging validation report) — the on-behalf punch dialog's time field is labelled with
// the business timezone but used to be interpreted with `new Date(datetimeLocalValue)`, which
// reads the VIEWER's browser/OS zone, not the zone the label promises. `wallTimeToUtcIso` is the
// fix: it must produce the exact same UTC instant for the exact same form input regardless of
// which zone the code happens to be running in.
describe("wallTimeToUtcIso", () => {
  const PROCESS_TIMEZONES = ["Asia/Kolkata", "UTC", "America/New_York", "Pacific/Kiritimati"];

  function withProcessTimezone<T>(tz: string, fn: () => T): T {
    const original = process.env.TZ;
    process.env.TZ = tz;
    try {
      return fn();
    } finally {
      process.env.TZ = original;
    }
  }

  it("converts 2026-09-15 09:00 IST to the correct UTC instant, identically under every process timezone", () => {
    const results = PROCESS_TIMEZONES.map((tz) =>
      withProcessTimezone(tz, () => wallTimeToUtcIso("2026-09-15T09:00", "Asia/Kolkata")),
    );
    // Every process-timezone run produced the exact same result.
    expect(new Set(results).size).toBe(1);
    expect(results[0]).toBe("2026-09-15T03:30:00.000Z");
  });

  it("does not let the process/browser timezone move a near-midnight IST entry to the wrong India business date", () => {
    // 00:30 IST is 19:00 UTC the PREVIOUS calendar day — the exact boundary a naive
    // `new Date("2026-09-15T00:30")` would get right only by accident of the host's own zone.
    const results = PROCESS_TIMEZONES.map((tz) =>
      withProcessTimezone(tz, () => wallTimeToUtcIso("2026-09-15T00:30", "Asia/Kolkata")),
    );
    expect(new Set(results).size).toBe(1);
    const utcInstant = results[0];
    expect(utcInstant).toBe("2026-09-14T19:00:00.000Z");

    // Round-tripping the stored UTC instant back through the business timezone must land on
    // 15 Sept — the date the admin actually typed — not 14 Sept, under every process timezone.
    for (const tz of PROCESS_TIMEZONES) {
      withProcessTimezone(tz, () => {
        const istDate = new Intl.DateTimeFormat("en-CA", {
          timeZone: "Asia/Kolkata",
          year: "numeric",
          month: "2-digit",
          day: "2-digit",
        }).format(new Date(utcInstant));
        expect(istDate).toBe("2026-09-15");
      });
    }
  });

  it("round-trips through formatClockTime back to the exact wall time that was entered", () => {
    const utcInstant = wallTimeToUtcIso("2026-09-15T14:45", "Asia/Kolkata");
    expect(formatClockTime(utcInstant, "Asia/Kolkata")).toBe("02:45 pm IST");
  });

  it("rejects a value that is not a datetime-local string rather than silently misinterpreting it", () => {
    expect(() => wallTimeToUtcIso("2026-09-15", "Asia/Kolkata")).toThrow();
    expect(() => wallTimeToUtcIso("not-a-date", "Asia/Kolkata")).toThrow();
  });
});

describe("nowInZoneForDatetimeLocal", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("seeds the IST wall-clock time, not the host process's own zone", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-14T19:05:00Z")); // 00:35 IST, 15 Sept
    expect(nowInZoneForDatetimeLocal("Asia/Kolkata")).toBe("2026-09-15T00:35");
  });

  it("is identical across every process timezone for the same frozen instant", () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-09-14T19:05:00Z"));
    const original = process.env.TZ;
    try {
      const results = ["Asia/Kolkata", "UTC", "America/New_York", "Pacific/Kiritimati"].map((tz) => {
        process.env.TZ = tz;
        return nowInZoneForDatetimeLocal("Asia/Kolkata");
      });
      expect(new Set(results).size).toBe(1);
      expect(results[0]).toBe("2026-09-15T00:35");
    } finally {
      process.env.TZ = original;
    }
  });
});
