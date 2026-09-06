import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import type {
  LeaveCombinationRuleFormErrors,
  LeaveCombinationRuleFormValues,
} from "@/lib/leave-combination-rule/validate-leave-combination-rule";
import type { LeaveType } from "@/lib/leave-type/types";

interface LeaveCombinationRuleFormProps {
  values: LeaveCombinationRuleFormValues;
  errors: LeaveCombinationRuleFormErrors;
  onChange: (values: LeaveCombinationRuleFormValues) => void;
  leaveTypeOptions: LeaveType[];
  idPrefix?: string;
}

function Checkbox({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex items-center gap-2 text-sm text-foreground">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-border"
      />
      {label}
    </label>
  );
}

/** Client spec §7 (LEAVE_DECISION_LOG.md LD-16) — an unordered pair of leave types plus whether
 * they may be applied for on overlapping dates. No edit — changing a rule is delete-and-recreate
 * (LD-16: no meaningful in-flight-draft state for a single boolean), so this form only ever
 * creates. */
export function LeaveCombinationRuleForm({
  values,
  errors,
  onChange,
  leaveTypeOptions,
  idPrefix = "",
}: LeaveCombinationRuleFormProps) {
  function update<K extends keyof LeaveCombinationRuleFormValues>(
    key: K,
    value: LeaveCombinationRuleFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id={id("type-a")} label="Leave type" required error={errors.leaveTypeIdA}>
          <NativeSelect
            value={values.leaveTypeIdA}
            onChange={(e) => update("leaveTypeIdA", e.target.value)}
          >
            <option value="">Choose…</option>
            {leaveTypeOptions.map((lt) => (
              <option key={lt.id} value={lt.id}>
                {lt.name} ({lt.code})
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField id={id("type-b")} label="Combined with" required error={errors.leaveTypeIdB}>
          <NativeSelect
            value={values.leaveTypeIdB}
            onChange={(e) => update("leaveTypeIdB", e.target.value)}
          >
            <option value="">Choose…</option>
            {leaveTypeOptions.map((lt) => (
              <option key={lt.id} value={lt.id}>
                {lt.name} ({lt.code})
              </option>
            ))}
          </NativeSelect>
        </FormField>
      </div>
      <Checkbox
        label="Allowed — an employee may have both applied for on overlapping dates. Unchecked means blocked."
        checked={values.allowed}
        onChange={(checked) => update("allowed", checked)}
      />
      <FormField id={id("reason")} label="Reason" description="Optional — shown to HR on the rule list.">
        <Input value={values.reason} onChange={(e) => update("reason", e.target.value)} />
      </FormField>
    </div>
  );
}
