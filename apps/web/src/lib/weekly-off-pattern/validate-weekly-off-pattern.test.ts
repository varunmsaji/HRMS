import { describe, expect, it } from "vitest";

import {
  EMPTY_RULE,
  EMPTY_WEEKLY_OFF_PATTERN_FORM_VALUES,
  buildCreatePayload,
  validateWeeklyOffPatternForm,
} from "@/lib/weekly-off-pattern/validate-weekly-off-pattern";

describe("validateWeeklyOffPatternForm", () => {
  it("requires a name", () => {
    const errors = validateWeeklyOffPatternForm(EMPTY_WEEKLY_OFF_PATTERN_FORM_VALUES);
    expect(errors.name).toBeDefined();
  });

  it("requires an occurrence on every rule for NTH_WEEKDAY", () => {
    const errors = validateWeeklyOffPatternForm({
      name: "2nd Saturday",
      code: "",
      patternKind: "NTH_WEEKDAY",
      rules: [{ ...EMPTY_RULE, nthInMonth: "" }],
    });
    expect(errors.rules).toBeDefined();
  });

  it("requires a starting date on every rule for ALTERNATE", () => {
    const errors = validateWeeklyOffPatternForm({
      name: "Alternate Saturday",
      code: "",
      patternKind: "ALTERNATE",
      rules: [{ ...EMPTY_RULE, cycleStartDate: "" }],
    });
    expect(errors.rules).toBeDefined();
  });

  it("rejects an occurrence set on a FIXED_WEEKDAYS rule", () => {
    const errors = validateWeeklyOffPatternForm({
      name: "Sunday",
      code: "",
      patternKind: "FIXED_WEEKDAYS",
      rules: [{ ...EMPTY_RULE, nthInMonth: "2" }],
    });
    expect(errors.rules).toBeDefined();
  });

  it("accepts a well-formed fixed-weekday pattern", () => {
    const errors = validateWeeklyOffPatternForm({
      name: "Sunday Off",
      code: "",
      patternKind: "FIXED_WEEKDAYS",
      rules: [{ ...EMPTY_RULE }],
    });
    expect(errors).toEqual({});
  });
});

describe("buildCreatePayload", () => {
  it("maps rule form values onto the wire shape", () => {
    const payload = buildCreatePayload({
      name: "2nd & 4th Saturday",
      code: "",
      patternKind: "NTH_WEEKDAY",
      rules: [
        { weekday: 5, nthInMonth: "2", cycleStartDate: "", offFraction: "1.00", weekParity: "" },
      ],
    });
    expect(payload.rules).toEqual([
      { weekday: 5, nth_in_month: 2, cycle_start_date: null, off_fraction: "1.00", week_parity: null },
    ]);
  });
});
