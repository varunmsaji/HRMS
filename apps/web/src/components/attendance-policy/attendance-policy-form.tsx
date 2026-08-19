import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type {
  AttendancePolicyFormErrors,
  AttendancePolicyFormValues,
} from "@/lib/attendance-policy/validate-attendance-policy";

interface AttendancePolicyFormProps {
  values: AttendancePolicyFormValues;
  errors: AttendancePolicyFormErrors;
  onChange: (values: AttendancePolicyFormValues) => void;
  idPrefix?: string;
}

/** Identity only (name/code) — evaluation rules live on the Versions tab, mirroring the
 * Shift/ShiftVersion split (SHIFT = SCHEDULE, ATTENDANCE POLICY IDENTITY != EVALUATION RULES). */
export function AttendancePolicyForm({
  values,
  errors,
  onChange,
  idPrefix = "",
}: AttendancePolicyFormProps) {
  function update<K extends keyof AttendancePolicyFormValues>(
    key: K,
    value: AttendancePolicyFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <FormField id={id("name")} label="Policy name" required error={errors.name}>
        <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
      </FormField>
      <FormField id={id("code")} label="Policy code" error={errors.code}>
        <Input value={values.code} onChange={(e) => update("code", e.target.value)} />
      </FormField>
    </div>
  );
}
