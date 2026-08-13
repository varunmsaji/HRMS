import type { Department } from "@/lib/department/types";

export interface DepartmentFormValues {
  name: string;
  code: string;
  branchId: string;
  parentId: string;
}

export type DepartmentFormErrors = Partial<Record<keyof DepartmentFormValues, string>>;

export const EMPTY_DEPARTMENT_FORM_VALUES: DepartmentFormValues = {
  name: "",
  code: "",
  branchId: "",
  parentId: "",
};

export function departmentToFormValues(department: Department): DepartmentFormValues {
  return {
    name: department.name,
    code: department.code ?? "",
    branchId: department.branch_id ?? "",
    parentId: department.parent_id ?? "",
  };
}

/** Full payload for `POST /departments` — every field the form collects. */
export function buildCreatePayload(values: DepartmentFormValues): Record<string, unknown> {
  return {
    name: values.name.trim(),
    code: values.code.trim() || null,
    branch_id: values.branchId || null,
    parent_id: values.parentId || null,
  };
}

/** Diff-only payload for `PATCH /departments/{id}` — mirrors `buildUpdatePatch` for Branch. */
export function buildUpdatePatch(
  values: DepartmentFormValues,
  department: Department,
): Record<string, unknown> {
  const patch: Record<string, unknown> = {};

  if (values.name.trim() !== department.name) patch.name = values.name.trim();

  const currentCode = department.code ?? "";
  if (values.code.trim() !== currentCode) patch.code = values.code.trim() || null;

  const currentBranchId = department.branch_id ?? "";
  if (values.branchId !== currentBranchId) patch.branch_id = values.branchId || null;

  const currentParentId = department.parent_id ?? "";
  if (values.parentId !== currentParentId) patch.parent_id = values.parentId || null;

  return patch;
}

export function validateDepartmentForm(values: DepartmentFormValues): DepartmentFormErrors {
  const errors: DepartmentFormErrors = {};

  if (!values.name.trim()) {
    errors.name = "Department name is required.";
  }

  return errors;
}

/**
 * Ids of `departmentId` and every department transitively parented under it, computed from
 * the flat department list already loaded client-side (no `/tree` endpoint this slice).
 * Used to exclude a department's own descendants from its "parent department" picker —
 * matches the exclusion rule named in the Sprint 3 plan's Department tree UI, applied here
 * to a flat picker instead of a tree combobox.
 */
export function descendantIds(departments: Department[], departmentId: string): Set<string> {
  const childrenByParent = new Map<string, string[]>();
  for (const department of departments) {
    if (!department.parent_id) continue;
    const siblings = childrenByParent.get(department.parent_id) ?? [];
    siblings.push(department.id);
    childrenByParent.set(department.parent_id, siblings);
  }

  const result = new Set<string>([departmentId]);
  const queue = [departmentId];
  while (queue.length > 0) {
    const current = queue.shift();
    if (current === undefined) break;
    for (const childId of childrenByParent.get(current) ?? []) {
      if (!result.has(childId)) {
        result.add(childId);
        queue.push(childId);
      }
    }
  }
  return result;
}
