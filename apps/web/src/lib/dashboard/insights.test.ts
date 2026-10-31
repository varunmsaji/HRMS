import { describe, expect, it } from "vitest";

import { birthdayLabel, initials, insightsPath, monthShort, relativeTime, type UpcomingBirthday } from "./insights";

const birthday = (over: Partial<UpcomingBirthday> = {}): UpcomingBirthday => ({
  employee_id: "e1",
  name: "Asha Rao",
  designation: null,
  photo_url: null,
  birthday: "2026-11-04",
  days_until: 4,
  ...over,
});

describe("dashboard insight helpers", () => {
  it("builds the company insights path from the controls", () => {
    expect(insightsPath(6, "month")).toBe("/dashboards/company/insights?growth_months=6&leave_scope=month");
    expect(insightsPath(12, "year")).toBe("/dashboards/company/insights?growth_months=12&leave_scope=year");
  });

  it("formats recent activity relative to now", () => {
    const now = new Date("2026-10-31T12:00:00Z");
    expect(relativeTime("2026-10-31T12:00:00Z", now)).toBe("just now");
    expect(relativeTime("2026-10-31T11:40:00Z", now)).toBe("20 mins ago");
    expect(relativeTime("2026-10-31T10:00:00Z", now)).toBe("2 hours ago");
    expect(relativeTime("2026-10-28T12:00:00Z", now)).toBe("3 days ago");
  });

  it("labels a birthday as today, tomorrow, or a date", () => {
    expect(birthdayLabel(birthday({ days_until: 0 }))).toBe("Today");
    expect(birthdayLabel(birthday({ days_until: 1 }))).toBe("Tomorrow");
    expect(birthdayLabel(birthday({ days_until: 4, birthday: "2026-11-04" }))).toBe("4 Nov");
  });

  it("shortens a trend month and builds initials", () => {
    expect(monthShort("2026-10")).toBe("Oct");
    expect(initials("Asha Rao")).toBe("AR");
    expect(initials("")).toBe("?");
  });
});
