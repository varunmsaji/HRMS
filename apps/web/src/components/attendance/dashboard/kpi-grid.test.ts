import { describe, expect, it } from "vitest";

import { buildKpis } from "@/components/attendance/dashboard/kpi-grid";
import { DEFAULT_FILTERS } from "@/lib/attendance/dashboard";
import { makeKpis } from "@/lib/attendance/__fixtures__/summary";
import { toKpiSet } from "@/lib/attendance/summary";
import { SELECTABLE_REGULARIZATION_TYPES } from "@/lib/regularization/types";

describe("work from home (R-B05)", () => {
  it("shows no Remote tile while nobody worked from home", () => {
    const { primary } = buildKpis(toKpiSet(makeKpis({ remote: 0 })), DEFAULT_FILTERS, "Today");
    expect(primary.map((k) => k.key)).not.toContain("remote");
  });

  it("still shows the Remote tile when the engine did record such days", () => {
    const { primary } = buildKpis(toKpiSet(makeKpis({ remote: 2, present: 5 })), DEFAULT_FILTERS, "Today");
    expect(primary.map((k) => k.key)).toContain("remote");
  });

  it("does not offer work from home when asking for a correction", () => {
    expect(SELECTABLE_REGULARIZATION_TYPES).not.toContain("WFH");
    expect(SELECTABLE_REGULARIZATION_TYPES).toContain("MISSING_PUNCH");
  });
});
