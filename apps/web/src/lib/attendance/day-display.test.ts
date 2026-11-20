import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { BUCKET_GLYPHS, BUCKET_LABELS, DAY_BUCKETS, bucketOf } from "@/lib/attendance/dashboard";
import type { AttendanceDay } from "@/lib/attendance/types";

// The API's display table, committed as a fixture (R-B02). Web and mobile both check against it.
const table = JSON.parse(
  readFileSync(
    path.resolve(process.cwd(), "../api/tests/fixtures/day_display_table.json"),
    "utf-8",
  ),
) as Record<string, { label: string; tone: string; glyph: string }>;

const day = (over: Record<string, unknown>) => ({ attendance_status: "ABSENT", ...over }) as unknown as AttendanceDay;

describe("day display vocabulary", () => {
  it("has the same label and glyph as the API for every bucket", () => {
    for (const bucket of DAY_BUCKETS) {
      expect(table[bucket], bucket).toBeDefined();
      expect(BUCKET_LABELS[bucket], bucket).toBe(table[bucket].label);
      expect(BUCKET_GLYPHS[bucket], bucket).toBe(table[bucket].glyph);
    }
  });

  it("reads the bucket from the API's display code", () => {
    const display = { code: "HOLIDAY", label: "Holiday", tone: "holiday", glyph: "H", provisional: false };
    expect(bucketOf(day({ attendance_status: "NOT_EXPECTED", display }))).toBe("HOLIDAY");
  });

  it("falls back to the status for a row without display (older API)", () => {
    expect(bucketOf(day({ attendance_status: "NOT_EXPECTED", calendar_day_type: "HOLIDAY" }))).toBe("HOLIDAY");
    expect(bucketOf(day({ attendance_status: "WFH" }))).toBe("REMOTE");
  });

  it("ignores a display code this client does not know", () => {
    const display = { code: "FUTURE_CODE", label: "x", tone: "neutral", glyph: "x", provisional: false };
    expect(bucketOf(day({ attendance_status: "PRESENT", display }))).toBe("PRESENT");
  });
});
