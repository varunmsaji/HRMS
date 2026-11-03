import { describe, expect, it } from "vitest";

import type { Department } from "@/lib/department/types";
import {
  EMPTY_DEPARTMENT_FORM_VALUES,
  buildCreatePayload,
  buildUpdatePatch,
  departmentToFormValues,
  descendantIds,
  validateDepartmentForm,
} from "@/lib/department/validate-department";

const department: Department = {
  id: "dept-1",
  company_id: "company-1",
  branch_id: null,
  parent_id: null,
  name: "Engineering",
  code: null,
  head_employee_id: null,
  is_active: true,
  version: 1,
  created_at: "2026-08-01T00:00:00Z",
  updated_at: "2026-08-01T00:00:00Z",
};

describe("validateDepartmentForm", () => {
  it("requires a name", () => {
    const errors = validateDepartmentForm(EMPTY_DEPARTMENT_FORM_VALUES);
    expect(errors.name).toBeDefined();
  });

  it("treats blank optional fields as valid", () => {
    const errors = validateDepartmentForm({ ...EMPTY_DEPARTMENT_FORM_VALUES, name: "Engineering" });
    expect(errors).toEqual({});
  });
});

describe("departmentToFormValues / buildCreatePayload", () => {
  it("round-trips name and nulls other optional fields", () => {
    const values = departmentToFormValues(department);
    expect(values.name).toBe("Engineering");
    expect(values.branchId).toBe("");
    expect(values.parentId).toBe("");

    const payload = buildCreatePayload(values);
    expect(payload).toEqual({
      name: "Engineering",
      branch_id: null,
      parent_id: null,
      head_employee_id: null,
    });
  });

  it("includes branch_id and parent_id when set", () => {
    const values = { ...departmentToFormValues(department), branchId: "branch-1", parentId: "dept-2" };
    const payload = buildCreatePayload(values);
    expect(payload.branch_id).toBe("branch-1");
    expect(payload.parent_id).toBe("dept-2");
  });
});

describe("buildUpdatePatch", () => {
  it("returns an empty patch when nothing changed", () => {
    const values = departmentToFormValues(department);
    expect(buildUpdatePatch(values, department)).toEqual({});
  });

  it("includes only changed fields", () => {
    const values = departmentToFormValues(department);
    values.name = "Platform Engineering";
    const patch = buildUpdatePatch(values, department);
    expect(patch).toEqual({ name: "Platform Engineering" });
  });

  it("nulls out a branch that was cleared", () => {
    const withBranch: Department = { ...department, branch_id: "branch-1" };
    const values = departmentToFormValues(withBranch);
    values.branchId = "";
    const patch = buildUpdatePatch(values, withBranch);
    expect(patch).toEqual({ branch_id: null });
  });

  it("includes a changed parent_id", () => {
    const values = departmentToFormValues(department);
    values.parentId = "dept-2";
    const patch = buildUpdatePatch(values, department);
    expect(patch).toEqual({ parent_id: "dept-2" });
  });
});

describe("descendantIds", () => {
  const tree: Department[] = [
    { ...department, id: "root", parent_id: null, name: "Root" },
    { ...department, id: "child-1", parent_id: "root", name: "Child 1" },
    { ...department, id: "child-2", parent_id: "root", name: "Child 2" },
    { ...department, id: "grandchild", parent_id: "child-1", name: "Grandchild" },
    { ...department, id: "unrelated", parent_id: null, name: "Unrelated" },
  ];

  it("includes the node itself and every transitive descendant", () => {
    const result = descendantIds(tree, "root");
    expect(result).toEqual(new Set(["root", "child-1", "child-2", "grandchild"]));
  });

  it("excludes unrelated nodes and ancestors", () => {
    const result = descendantIds(tree, "child-1");
    expect(result).toEqual(new Set(["child-1", "grandchild"]));
    expect(result.has("root")).toBe(false);
    expect(result.has("unrelated")).toBe(false);
  });

  it("returns just the node itself when it has no children", () => {
    const result = descendantIds(tree, "grandchild");
    expect(result).toEqual(new Set(["grandchild"]));
  });
});
