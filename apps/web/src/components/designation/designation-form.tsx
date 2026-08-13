import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { Department } from "@/lib/department/types";
import type { DesignationFormErrors, DesignationFormValues } from "@/lib/designation/validate-designation";
import type { Grade } from "@/lib/grade/types";

interface DesignationFormProps {
  values: DesignationFormValues;
  errors: DesignationFormErrors;
  onChange: (values: DesignationFormValues) => void;
  departments: Department[];
  grades: Grade[];
  idPrefix?: string;
}

export function DesignationForm({
  values,
  errors,
  onChange,
  departments,
  grades,
  idPrefix = "",
}: DesignationFormProps) {
  function update<K extends keyof DesignationFormValues>(key: K, value: DesignationFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Identity</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("title")} label="Designation title" required error={errors.title}>
            <Input value={values.title} onChange={(e) => update("title", e.target.value)} />
          </FormField>
          <FormField id={id("code")} label="Designation code" error={errors.code}>
            <Input value={values.code} onChange={(e) => update("code", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Department &amp; grade</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Both are optional. A designation doesn&apos;t need to belong to a department — for
          example, a company-wide role like &quot;CEO&quot; — and can exist before a
          compensation grade is decided.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("departmentId")} label="Department" error={errors.departmentId}>
            <NativeSelect
              value={values.departmentId}
              onChange={(e) => update("departmentId", e.target.value)}
            >
              <option value="">No department</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("gradeId")} label="Grade" error={errors.gradeId}>
            <NativeSelect value={values.gradeId} onChange={(e) => update("gradeId", e.target.value)}>
              <option value="">No grade</option>
              {grades.map((grade) => (
                <option key={grade.id} value={grade.id}>
                  {grade.name} ({grade.code})
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>
    </div>
  );
}
