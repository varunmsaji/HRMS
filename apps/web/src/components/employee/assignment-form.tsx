import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import { EmployeeSelect } from "@/components/employee/employee-select";
import type { AssignmentChangeType, WorkLocationType } from "@/lib/employee/types";
import type { EmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { ASSIGNMENT_CHANGE_TYPE_VALUES, WORK_LOCATION_TYPE_VALUES } from "@/lib/employee/types";
import {
  CHANGE_TYPE_LABELS,
  WORK_LOCATION_LABELS,
  type AssignmentFormErrors,
  type AssignmentFormValues,
} from "@/lib/employee/validate-assignment";
import type { Grade } from "@/lib/grade/types";
import type { Shift } from "@/lib/shift/types";

interface AssignmentFormProps {
  values: AssignmentFormValues;
  errors: AssignmentFormErrors;
  onChange: (values: AssignmentFormValues) => void;
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
  grades: Grade[];
  shifts: Shift[];
  /** Paginated employee directory for the manager pickers — see `EmployeeSelect`. */
  directory: EmployeeDirectory;
  currentEmployeeId: string;
  allowedChangeTypes: AssignmentChangeType[];
  idPrefix?: string;
}

export function AssignmentForm({
  values,
  errors,
  onChange,
  branches,
  departments,
  designations,
  grades,
  shifts,
  directory,
  currentEmployeeId,
  allowedChangeTypes,
  idPrefix = "",
}: AssignmentFormProps) {
  function update<K extends keyof AssignmentFormValues>(key: K, value: AssignmentFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Change details</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("changeType")} label="Change type" required error={errors.changeType}>
            <NativeSelect
              value={values.changeType}
              onChange={(e) => update("changeType", e.target.value as AssignmentChangeType | "")}
            >
              <option value="">Select a change type</option>
              {ASSIGNMENT_CHANGE_TYPE_VALUES.filter((type) => allowedChangeTypes.includes(type)).map((type) => (
                <option key={type} value={type}>
                  {CHANGE_TYPE_LABELS[type]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("effectiveFrom")} label="Effective from" required error={errors.effectiveFrom}>
            <Input
              type="date"
              value={values.effectiveFrom}
              onChange={(e) => update("effectiveFrom", e.target.value)}
            />
          </FormField>
          <FormField
            id={id("changeReason")}
            label="Change reason"
            error={errors.changeReason}
            className="sm:col-span-2"
          >
            <Input value={values.changeReason} onChange={(e) => update("changeReason", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Placement</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Leave a field blank to carry forward its current value — only set the fields this change
          actually affects.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("branchId")} label="Branch" error={errors.branchId}>
            <NativeSelect value={values.branchId} onChange={(e) => update("branchId", e.target.value)}>
              <option value="">No change</option>
              {branches.map((branch) => (
                <option key={branch.id} value={branch.id}>
                  {branch.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("departmentId")} label="Department" error={errors.departmentId}>
            <NativeSelect value={values.departmentId} onChange={(e) => update("departmentId", e.target.value)}>
              <option value="">No change</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("designationId")} label="Designation" error={errors.designationId}>
            <NativeSelect value={values.designationId} onChange={(e) => update("designationId", e.target.value)}>
              <option value="">No change</option>
              {designations.map((designation) => (
                <option key={designation.id} value={designation.id}>
                  {designation.title}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("gradeId")} label="Grade" error={errors.gradeId}>
            <NativeSelect value={values.gradeId} onChange={(e) => update("gradeId", e.target.value)}>
              <option value="">No change</option>
              {grades.map((grade) => (
                <option key={grade.id} value={grade.id}>
                  {grade.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("workLocationType")} label="Work location" error={errors.workLocationType}>
            <NativeSelect
              value={values.workLocationType}
              onChange={(e) => update("workLocationType", e.target.value as WorkLocationType | "")}
            >
              <option value="">No change</option>
              {WORK_LOCATION_TYPE_VALUES.map((type) => (
                <option key={type} value={type}>
                  {WORK_LOCATION_LABELS[type]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("costCentreId")} label="Cost centre ID" error={errors.costCentreId}>
            <Input
              value={values.costCentreId}
              onChange={(e) => update("costCentreId", e.target.value)}
              placeholder="No cost centre directory exists yet — enter the ID directly"
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Reporting</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id={id("reportingManagerId")}
            label="Reporting manager"
            error={errors.reportingManagerId}
          >
            <EmployeeSelect
              directory={directory}
              value={values.reportingManagerId}
              emptyLabel="No change"
              excludeId={currentEmployeeId}
              onChange={(employeeId) => update("reportingManagerId", employeeId)}
            />
          </FormField>
          <FormField
            id={id("dottedLineManagerId")}
            label="Dotted-line manager"
            error={errors.dottedLineManagerId}
          >
            <EmployeeSelect
              directory={directory}
              value={values.dottedLineManagerId}
              emptyLabel="No change"
              excludeId={currentEmployeeId}
              onChange={(employeeId) => update("dottedLineManagerId", employeeId)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Shift</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("shiftId")} label="Shift" error={errors.shiftId}>
            <NativeSelect value={values.shiftId} onChange={(e) => update("shiftId", e.target.value)}>
              <option value="">No change</option>
              {shifts.map((shift) => (
                <option key={shift.id} value={shift.id}>
                  {shift.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>
    </div>
  );
}
