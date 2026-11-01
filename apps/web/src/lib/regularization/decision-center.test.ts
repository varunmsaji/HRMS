import { describe, expect, it } from "vitest";

import { requestedTime, stageLabel } from "./decision-center";

describe("regularization decision helpers", () => {
  it("picks the earliest IN and latest OUT", () => {
    const punches = [
      { direction: "IN", time: "2026-10-05T09:00:00Z" },
      { direction: "IN", time: "2026-10-05T08:30:00Z" },
      { direction: "OUT", time: "2026-10-05T17:00:00Z" },
      { direction: "OUT", time: "2026-10-05T18:00:00Z" },
    ];
    expect(requestedTime(punches, "IN")).toBe("2026-10-05T08:30:00Z");
    expect(requestedTime(punches, "OUT")).toBe("2026-10-05T18:00:00Z");
    expect(requestedTime([], "IN")).toBeNull();
  });

  it("names the stage", () => {
    expect(stageLabel("HR")).toBe("Pending HR review");
    expect(stageLabel("MANAGER")).toBe("Pending manager review");
    expect(stageLabel(null)).toBe("Pending review");
  });
});
