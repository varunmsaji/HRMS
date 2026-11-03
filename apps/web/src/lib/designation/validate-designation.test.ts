import { describe, expect, it } from "vitest";

import type { Designation } from "@/lib/designation/types";
import {
  EMPTY_DESIGNATION_FORM_VALUES,
  buildCreatePayload,
  buildUpdatePatch,
  designationToFormValues,
  validateDesignationForm,
} from "@/lib/designation/validate-designation";

const designation: Designation = {
  id: "desig-1",
  company_id: "company-1",
  department_id: null,
  grade_id: null,
  title: "Software Engineer",
  code: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateDesignationForm", () => {
  it("requires a title", () => {
    const errors = validateDesignationForm(EMPTY_DESIGNATION_FORM_VALUES);
    expect(errors.title).toBeDefined();
  });

  it("treats blank optional fields as valid", () => {
    const errors = validateDesignationForm({
      ...EMPTY_DESIGNATION_FORM_VALUES,
      title: "Software Engineer",
    });
    expect(errors).toEqual({});
  });
});

describe("designationToFormValues / buildCreatePayload", () => {
  it("round-trips title and nulls other optional fields", () => {
    const values = designationToFormValues(designation);
    expect(values.title).toBe("Software Engineer");
    expect(values.departmentId).toBe("");
    expect(values.gradeId).toBe("");

    const payload = buildCreatePayload(values);
    expect(payload).toEqual({
      title: "Software Engineer",
      department_id: null,
      grade_id: null,
    });
  });

  it("includes department_id when set", () => {
    const values = { ...designationToFormValues(designation), departmentId: "dept-1" };
    const payload = buildCreatePayload(values);
    expect(payload.department_id).toBe("dept-1");
  });

  it("includes grade_id when set", () => {
    const values = { ...designationToFormValues(designation), gradeId: "grade-1" };
    const payload = buildCreatePayload(values);
    expect(payload.grade_id).toBe("grade-1");
  });
});

describe("buildUpdatePatch", () => {
  it("returns an empty patch when nothing changed", () => {
    const values = designationToFormValues(designation);
    expect(buildUpdatePatch(values, designation)).toEqual({});
  });

  it("includes only changed fields", () => {
    const values = designationToFormValues(designation);
    values.title = "Senior Software Engineer";
    const patch = buildUpdatePatch(values, designation);
    expect(patch).toEqual({ title: "Senior Software Engineer" });
  });

  it("nulls out a department that was cleared", () => {
    const withDepartment: Designation = { ...designation, department_id: "dept-1" };
    const values = designationToFormValues(withDepartment);
    values.departmentId = "";
    const patch = buildUpdatePatch(values, withDepartment);
    expect(patch).toEqual({ department_id: null });
  });

  it("includes a changed department_id", () => {
    const values = designationToFormValues(designation);
    values.departmentId = "dept-2";
    const patch = buildUpdatePatch(values, designation);
    expect(patch).toEqual({ department_id: "dept-2" });
  });

  it("nulls out a grade that was cleared", () => {
    const withGrade: Designation = { ...designation, grade_id: "grade-1" };
    const values = designationToFormValues(withGrade);
    values.gradeId = "";
    const patch = buildUpdatePatch(values, withGrade);
    expect(patch).toEqual({ grade_id: null });
  });

  it("includes a changed grade_id", () => {
    const values = designationToFormValues(designation);
    values.gradeId = "grade-2";
    const patch = buildUpdatePatch(values, designation);
    expect(patch).toEqual({ grade_id: "grade-2" });
  });
});
