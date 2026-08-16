import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  BLOOD_GROUP_OPTIONS,
  GENDER_OPTIONS,
  MARITAL_STATUS_OPTIONS,
  type EmployeeFormErrors,
  type EmployeeFormValues,
} from "@/lib/employee/validate-employee";

interface EmployeeFormProps {
  values: EmployeeFormValues;
  errors: EmployeeFormErrors;
  onChange: (values: EmployeeFormValues) => void;
  idPrefix?: string;
}

export function EmployeeForm({ values, errors, onChange, idPrefix = "" }: EmployeeFormProps) {
  function update<K extends keyof EmployeeFormValues>(key: K, value: EmployeeFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Name</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField id={id("firstName")} label="First name" required error={errors.firstName}>
            <Input value={values.firstName} onChange={(e) => update("firstName", e.target.value)} />
          </FormField>
          <FormField id={id("middleName")} label="Middle name" error={errors.middleName}>
            <Input value={values.middleName} onChange={(e) => update("middleName", e.target.value)} />
          </FormField>
          <FormField id={id("lastName")} label="Last name" error={errors.lastName}>
            <Input value={values.lastName} onChange={(e) => update("lastName", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Personal details</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("dateOfBirth")} label="Date of birth" error={errors.dateOfBirth}>
            <Input
              type="date"
              value={values.dateOfBirth}
              onChange={(e) => update("dateOfBirth", e.target.value)}
            />
          </FormField>
          <FormField id={id("gender")} label="Gender" error={errors.gender}>
            <NativeSelect value={values.gender} onChange={(e) => update("gender", e.target.value)}>
              <option value="">Not specified</option>
              {GENDER_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("maritalStatus")} label="Marital status" error={errors.maritalStatus}>
            <NativeSelect value={values.maritalStatus} onChange={(e) => update("maritalStatus", e.target.value)}>
              <option value="">Not specified</option>
              {MARITAL_STATUS_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("bloodGroup")} label="Blood group" error={errors.bloodGroup}>
            <NativeSelect value={values.bloodGroup} onChange={(e) => update("bloodGroup", e.target.value)}>
              <option value="">Not specified</option>
              {BLOOD_GROUP_OPTIONS.map((option) => (
                <option key={option} value={option}>
                  {option}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={id("nationality")} label="Nationality" error={errors.nationality}>
            <Input value={values.nationality} onChange={(e) => update("nationality", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Personal contact</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Used for personal correspondence only — work email/mobile are assigned separately once
          employment begins.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("personalEmail")} label="Personal email" error={errors.personalEmail}>
            <Input
              type="email"
              value={values.personalEmail}
              onChange={(e) => update("personalEmail", e.target.value)}
            />
          </FormField>
          <FormField id={id("personalMobile")} label="Personal mobile" error={errors.personalMobile}>
            <Input value={values.personalMobile} onChange={(e) => update("personalMobile", e.target.value)} />
          </FormField>
        </div>
      </section>
    </div>
  );
}
