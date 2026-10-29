import { describe, expect, it } from "vitest";

import {
  DEFAULT_COMPANY_DATE_FORMAT,
  formatCompanyDate,
  formatCompanyDateInZone,
} from "@/lib/dates/company-date";

describe("formatCompanyDate", () => {
  it("defaults to the product date format DD/MM/YYYY", () => {
    expect(DEFAULT_COMPANY_DATE_FORMAT).toBe("DD/MM/YYYY");
    expect(formatCompanyDate("2000-01-01")).toBe("01/01/2000");
    expect(formatCompanyDate("2026-11-15")).toBe("15/11/2026");
    expect(formatCompanyDate("2026-10-01")).toBe("01/10/2026");
  });

  it.each([
    ["MM/DD/YYYY", "10/01/2026"],
    ["YYYY-MM-DD", "2026-10-01"],
    ["DD-MM-YYYY", "01-10-2026"],
    ["YYYY/MM/DD", "2026/10/01"],
    ["dd/mm/yyyy", "01/10/2026"],
  ])("applies the supported pattern %s", (pattern, expected) => {
    expect(formatCompanyDate("2026-10-01", pattern)).toBe(expected);
  });

  it("falls back to DD/MM/YYYY when the stored pattern is not a DD/MM/YYYY token pattern", () => {
    expect(formatCompanyDate("2026-10-01", "DD-MMM-YYYY")).toBe("01/10/2026");
    expect(formatCompanyDate("2026-10-01", "pretty")).toBe("01/10/2026");
    expect(formatCompanyDate("2026-10-01", "")).toBe("01/10/2026");
    expect(formatCompanyDate("2026-10-01", null)).toBe("01/10/2026");
  });

  it("does not parse a date-only value as a UTC instant, so the day cannot move", () => {
    const original = process.env.TZ;
    try {
      for (const tz of ["Pacific/Kiritimati", "America/New_York", "UTC", "Asia/Kolkata"]) {
        process.env.TZ = tz;
        expect(formatCompanyDate("2026-10-01")).toBe("01/10/2026");
      }
    } finally {
      process.env.TZ = original;
    }
  });

  it("returns an em dash for blank, invalid and non-date values", () => {
    expect(formatCompanyDate(null)).toBe("—");
    expect(formatCompanyDate(undefined)).toBe("—");
    expect(formatCompanyDate("")).toBe("—");
    expect(formatCompanyDate("   ")).toBe("—");
    expect(formatCompanyDate("not-a-date")).toBe("—");
    expect(formatCompanyDate("2026-13-01")).toBe("—");
    expect(formatCompanyDate("2026-02-31")).toBe("—");
    expect(formatCompanyDate("2026-00-10")).toBe("—");
    // Instants are not date-only. Taking the UTC date would be wrong west of UTC.
    expect(formatCompanyDate("2026-10-01T00:00:00Z")).toBe("—");
  });
});

describe("formatCompanyDateInZone", () => {
  it("uses the company calendar date at the IST midnight boundary, not the UTC date", () => {
    // 00:30 IST on 1 Oct is still 30 Sep in UTC.
    expect(formatCompanyDateInZone("2026-09-30T19:00:00Z", "Asia/Kolkata")).toBe("01/10/2026");
    expect(formatCompanyDateInZone("2026-09-30T19:00:00Z", "UTC")).toBe("30/09/2026");
    expect(formatCompanyDateInZone("2026-09-30T19:00:00Z", "America/New_York", "MM/DD/YYYY")).toBe(
      "09/30/2026",
    );
  });

  it("returns an em dash for a missing or unparseable instant", () => {
    expect(formatCompanyDateInZone(null, "Asia/Kolkata")).toBe("—");
    expect(formatCompanyDateInZone("yesterday", "Asia/Kolkata")).toBe("—");
  });
});
