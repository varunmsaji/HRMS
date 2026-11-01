import { describe, expect, it } from "vitest";

import { relativeTime, safeActionPath } from "./format";

describe("relativeTime", () => {
  const now = new Date("2026-11-01T12:00:00Z");
  it("formats recent times", () => {
    expect(relativeTime("2026-11-01T11:59:40Z", now)).toBe("just now");
    expect(relativeTime("2026-11-01T11:55:00Z", now)).toBe("5m ago");
    expect(relativeTime("2026-11-01T09:00:00Z", now)).toBe("3h ago");
    expect(relativeTime("2026-10-30T12:00:00Z", now)).toBe("2d ago");
  });
});

describe("safeActionPath", () => {
  it("allows app-relative paths only", () => {
    expect(safeActionPath("/app/attendance/face-setup")).toBe("/app/attendance/face-setup");
    expect(safeActionPath("https://evil.example/x")).toBeNull();
    expect(safeActionPath("//evil.example")).toBeNull();
    expect(safeActionPath("javascript:alert(1)")).toBeNull();
    expect(safeActionPath(null)).toBeNull();
  });
});
