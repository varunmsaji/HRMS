import { describe, expect, it } from "vitest";

import type { Grade } from "@/lib/grade/types";
import {
  EMPTY_GRADE_FORM_VALUES,
  buildCreatePayload,
  buildUpdatePatch,
  gradeToFormValues,
  validateGradeForm,
} from "@/lib/grade/validate-grade";

const grade: Grade = {
  id: "grade-1",
  company_id: "company-1",
  code: "L5",
  name: "Senior Engineer",
  level: 5,
  min_ctc: null,
  max_ctc: null,
  notice_period_days: null,
  probation_days: null,
  approval_limit: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateGradeForm", () => {
  it("requires a code and a name", () => {
    const errors = validateGradeForm(EMPTY_GRADE_FORM_VALUES);
    expect(errors.code).toBeDefined();
    expect(errors.name).toBeDefined();
  });

  it("treats blank optional fields as valid", () => {
    const errors = validateGradeForm({ ...EMPTY_GRADE_FORM_VALUES, code: "L5", name: "Senior Engineer" });
    expect(errors).toEqual({});
  });

  it("rejects max CTC below min CTC", () => {
    const errors = validateGradeForm({
      ...EMPTY_GRADE_FORM_VALUES,
      code: "L5",
      name: "Senior Engineer",
      minCtc: "20000",
      maxCtc: "10000",
    });
    expect(errors.maxCtc).toBeDefined();
  });

  it("allows equal min and max CTC", () => {
    const errors = validateGradeForm({
      ...EMPTY_GRADE_FORM_VALUES,
      code: "L5",
      name: "Senior Engineer",
      minCtc: "10000",
      maxCtc: "10000",
    });
    expect(errors).toEqual({});
  });
});

describe("gradeToFormValues / buildCreatePayload", () => {
  it("round-trips code/name and nulls other optional fields", () => {
    const values = gradeToFormValues(grade);
    expect(values.code).toBe("L5");
    expect(values.name).toBe("Senior Engineer");
    expect(values.level).toBe("5");
    expect(values.minCtc).toBe("");

    const payload = buildCreatePayload(values);
    expect(payload).toEqual({
      code: "L5",
      name: "Senior Engineer",
      level: 5,
      min_ctc: null,
      max_ctc: null,
      notice_period_days: null,
      probation_days: null,
      approval_limit: null,
    });
  });

  it("converts whole-rupee CTC input into minor units", () => {
    const values = { ...gradeToFormValues(grade), minCtc: "1000000", maxCtc: "2000000" };
    const payload = buildCreatePayload(values);
    expect(payload.min_ctc).toBe(100_000_000);
    expect(payload.max_ctc).toBe(200_000_000);
  });
});

describe("buildUpdatePatch", () => {
  it("returns an empty patch when nothing changed", () => {
    const values = gradeToFormValues(grade);
    expect(buildUpdatePatch(values, grade)).toEqual({});
  });

  it("includes only changed fields", () => {
    const values = gradeToFormValues(grade);
    values.level = "6";
    const patch = buildUpdatePatch(values, grade);
    expect(patch).toEqual({ level: 6 });
  });

  it("round-trips a minor-units value back to the same rupee display", () => {
    const withCtc: Grade = { ...grade, min_ctc: 100_000_000 };
    const values = gradeToFormValues(withCtc);
    expect(values.minCtc).toBe("1000000");
    expect(buildUpdatePatch(values, withCtc)).toEqual({});
  });

  it("nulls out a cleared field", () => {
    const withLevel: Grade = { ...grade, level: 5 };
    const values = gradeToFormValues(withLevel);
    values.level = "";
    const patch = buildUpdatePatch(values, withLevel);
    expect(patch).toEqual({ level: null });
  });
});
