import { describe, expect, it } from "vitest";

import { preDisbursalChecklist } from "./checklist";

const base = {
  inputs_locked_at: null,
  computed_at: null,
  error_count: 0,
  variance_open_count: 0,
  approved_at: null,
  status: "DRAFT" as const,
};

describe("preDisbursalChecklist", () => {
  it("is all pending for a fresh draft", () => {
    expect(preDisbursalChecklist(base).every((i) => !i.done)).toBe(true);
  });

  it("does not count errors or open variances as done", () => {
    const items = preDisbursalChecklist({
      ...base,
      inputs_locked_at: "x",
      computed_at: "x",
      error_count: 2,
      variance_open_count: 1,
    });
    expect(items.map((i) => i.done)).toEqual([true, false, false, false]);
  });

  it("is fully done once approved with no issues", () => {
    const items = preDisbursalChecklist({ ...base, inputs_locked_at: "x", computed_at: "x", approved_at: "x" });
    expect(items.every((i) => i.done)).toBe(true);
  });
});
