import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import { descendantIds } from "@/lib/department/validate-department";
import type { DepartmentFormErrors, DepartmentFormValues } from "@/lib/department/validate-department";

interface DepartmentFormProps {
  values: DepartmentFormValues;
  errors: DepartmentFormErrors;
  onChange: (values: DepartmentFormValues) => void;
  branches: Branch[];
  departments: Department[];
  /** The department being edited, if any — excluded (with its descendants) from the parent picker. */
  excludeDepartmentId?: string;
  idPrefix?: string;
}

export function DepartmentForm({
  values,
  errors,
  onChange,
  branches,
  departments,
  excludeDepartmentId,
  idPrefix = "",
}: DepartmentFormProps) {
  function update<K extends keyof DepartmentFormValues>(key: K, value: DepartmentFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  const excluded = excludeDepartmentId ? descendantIds(departments, excludeDepartmentId) : null;
  const parentOptions = excluded
    ? departments.filter((department) => !excluded.has(department.id))
    : departments;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Identity</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("name")} label="Department name" required error={errors.name}>
            <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
          </FormField>
          <FormField id={id("code")} label="Department code" error={errors.code}>
            <Input value={values.code} onChange={(e) => update("code", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Hierarchy</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Both are optional. A department doesn&apos;t need to belong to a branch, and can
          stand on its own without a parent department.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("branchId")} label="Branch" error={errors.branchId}>
            <NativeSelect value={values.branchId} onChange={(e) => update("branchId", e.target.value)}>
              <option value="">No branch</option>
              {branches.map((branch) => (
                <option key={branch.id} value={branch.id}>
                  {branch.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("parentId")} label="Parent department" error={errors.parentId}>
            <NativeSelect value={values.parentId} onChange={(e) => update("parentId", e.target.value)}>
              <option value="">No parent (top-level)</option>
              {parentOptions.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>
    </div>
  );
}
