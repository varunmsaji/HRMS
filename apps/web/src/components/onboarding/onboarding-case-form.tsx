import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import {
  type OnboardingCaseFormErrors,
  type OnboardingCaseFormValues,
} from "@/lib/onboarding/validate-onboarding";

interface OnboardingCaseFormProps {
  values: OnboardingCaseFormValues;
  errors: OnboardingCaseFormErrors;
  onChange: (values: OnboardingCaseFormValues) => void;
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
  idPrefix?: string;
}

export function OnboardingCaseForm({
  values,
  errors,
  onChange,
  branches,
  departments,
  designations,
  idPrefix = "",
}: OnboardingCaseFormProps) {
  function update<K extends keyof OnboardingCaseFormValues>(
    key: K,
    value: OnboardingCaseFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Candidate</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id={id("candidateFirstName")}
            label="First name"
            required
            error={errors.candidateFirstName}
          >
            <Input
              value={values.candidateFirstName}
              onChange={(e) => update("candidateFirstName", e.target.value)}
            />
          </FormField>
          <FormField id={id("candidateLastName")} label="Last name" error={errors.candidateLastName}>
            <Input
              value={values.candidateLastName}
              onChange={(e) => update("candidateLastName", e.target.value)}
            />
          </FormField>
          <FormField
            id={id("personalEmail")}
            label="Personal email"
            required
            error={errors.personalEmail}
            description="The invite link will be sent here once sending is enabled."
          >
            <Input
              type="email"
              value={values.personalEmail}
              onChange={(e) => update("personalEmail", e.target.value)}
            />
          </FormField>
          <FormField id={id("personalMobile")} label="Personal mobile" error={errors.personalMobile}>
            <Input
              value={values.personalMobile}
              onChange={(e) => update("personalMobile", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Proposed placement</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          The candidate never chooses their own job data — this is fixed by HR up front.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField
            id={id("proposedJoiningDate")}
            label="Proposed joining date"
            required
            error={errors.proposedJoiningDate}
          >
            <Input
              type="date"
              value={values.proposedJoiningDate}
              onChange={(e) => update("proposedJoiningDate", e.target.value)}
            />
          </FormField>
          <FormField id={id("branchId")} label="Branch" error={errors.branchId}>
            <NativeSelect value={values.branchId} onChange={(e) => update("branchId", e.target.value)}>
              <option value="">Not set</option>
              {branches.map((branch) => (
                <option key={branch.id} value={branch.id}>
                  {branch.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("departmentId")} label="Department" error={errors.departmentId}>
            <NativeSelect
              value={values.departmentId}
              onChange={(e) => update("departmentId", e.target.value)}
            >
              <option value="">Not set</option>
              {departments.map((department) => (
                <option key={department.id} value={department.id}>
                  {department.name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("designationId")} label="Designation" error={errors.designationId}>
            <NativeSelect
              value={values.designationId}
              onChange={(e) => update("designationId", e.target.value)}
            >
              <option value="">Not set</option>
              {designations.map((designation) => (
                <option key={designation.id} value={designation.id}>
                  {designation.title}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>
    </div>
  );
}
