import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type { LeaveType } from "@/lib/leave-type/types";
import type {
  LeavePolicyFormErrors,
  LeavePolicyFormValues,
} from "@/lib/leave-policy/validate-leave-policy";

interface LeavePolicyFormProps {
  values: LeavePolicyFormValues;
  errors: LeavePolicyFormErrors;
  onChange: (values: LeavePolicyFormValues) => void;
  idPrefix?: string;
  /** Only needed at creation — `leave_type_id` is fixed once a policy exists (LD-10). */
  leaveTypeOptions?: LeaveType[];
  leaveTypeEditable?: boolean;
}

/** Identity — leave_type_id/name/code, never carries evaluation fields directly (mirrors
 * `AttendancePolicyForm`). The actual rule configuration lives on the Versions tab. */
export function LeavePolicyForm({
  values,
  errors,
  onChange,
  idPrefix = "",
  leaveTypeOptions = [],
  leaveTypeEditable = true,
}: LeavePolicyFormProps) {
  function update<K extends keyof LeavePolicyFormValues>(key: K, value: LeavePolicyFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      {leaveTypeEditable ? (
        <FormField id={id("leave-type")} label="Leave type" required error={errors.leaveTypeId}>
          <NativeSelect
            value={values.leaveTypeId}
            onChange={(e) => update("leaveTypeId", e.target.value)}
          >
            <option value="">Choose…</option>
            {leaveTypeOptions.map((leaveType) => (
              <option key={leaveType.id} value={leaveType.id}>
                {leaveType.name} ({leaveType.code})
              </option>
            ))}
          </NativeSelect>
        </FormField>
      ) : null}
      <FormField id={id("name")} label="Policy name" required error={errors.name}>
        <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
      </FormField>
    </div>
  );
}
