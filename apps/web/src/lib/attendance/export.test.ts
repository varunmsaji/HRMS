import { describe, expect, it } from "vitest";

import { csvCell, exportFileName, exportWindowError, musterRegisterPath, reportExportPath, toCsv } from "@/lib/attendance/export";

describe("csvCell", () => {
  it("quotes commas, quotes and line breaks", () => {
    expect(csvCell('Rao, "Sam"')).toBe('"Rao, ""Sam"""');
    expect(csvCell("a\nb")).toBe('"a\nb"');
  });
  it("defuses a leading formula character in text but leaves numbers alone", () => {
    expect(csvCell("=SUM(A1)")).toBe("'=SUM(A1)");
    expect(csvCell("-cmd")).toBe("'-cmd");
    expect(csvCell(-5)).toBe("-5");
  });
  it("writes null and undefined as empty", () => {
    expect(csvCell(null)).toBe("");
    expect(csvCell(undefined)).toBe("");
  });
});

describe("toCsv", () => {
  it("starts with a BOM and uses CRLF", () => {
    expect(toCsv(["a", "b"], [[1, "x"]])).toBe("﻿a,b\r\n1,x\r\n");
  });
});

describe("exportFileName", () => {
  it("keeps only safe characters", () => {
    expect(exportFileName("Daily attendance", "1 Nov – 30 Nov 2026")).toBe("daily-attendance_1-nov-30-nov-2026.csv");
  });
});

describe("musterRegisterPath", () => {
  it("carries the window and filters as the query", () => {
    expect(musterRegisterPath({ date_from: "2026-11-01", date_to: "2026-11-30", department_id: "d1" })).toBe(
      "/attendance/export/muster?date_from=2026-11-01&date_to=2026-11-30&department_id=d1",
    );
  });
});

describe("reportExportPath", () => {
  it("names the report and carries the period and filters", () => {
    expect(reportExportPath("late-early", { date_from: "2026-01-01", date_to: "2026-12-31", branch_id: "b1" })).toBe(
      "/attendance/reports/late-early/export?date_from=2026-01-01&date_to=2026-12-31&branch_id=b1",
    );
  });
});

describe("exportWindowError", () => {
  const today = "2026-11-24";
  it("accepts a period of up to a year ending today", () => {
    expect(exportWindowError("2025-11-24", today, today)).toBeNull(); // 366 days
    expect(exportWindowError(today, today, today)).toBeNull();
  });
  it("refuses an empty, reversed, future or over-long period", () => {
    expect(exportWindowError("", today, today)).toMatch(/both dates/i);
    expect(exportWindowError("2026-11-10", "2026-11-01", today)).toMatch(/on or before/i);
    expect(exportWindowError("2026-11-01", "2026-11-25", today)).toMatch(/future/i);
    expect(exportWindowError("2025-11-23", today, today)).toMatch(/at most 366/i);
  });
});
