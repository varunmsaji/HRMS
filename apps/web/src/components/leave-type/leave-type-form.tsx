import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type {
  LeaveTypeFormErrors,
  LeaveTypeFormValues,
} from "@/lib/leave-type/validate-leave-type";

interface LeaveTypeFormProps {
  values: LeaveTypeFormValues;
  errors: LeaveTypeFormErrors;
  onChange: (values: LeaveTypeFormValues) => void;
  idPrefix?: string;
  /** `code` is immutable after creation — omitted from the edit form. */
  codeEditable?: boolean;
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

/** Identity — code/name/is_paid_default/requires_balance. No versioning (mirrors Shift's
 * identity-only shape, not the policy draft/publish split). */
export function LeaveTypeForm({
  values,
  errors,
  onChange,
  idPrefix = "",
  codeEditable = true,
}: LeaveTypeFormProps) {
  function update<K extends keyof LeaveTypeFormValues>(key: K, value: LeaveTypeFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id={id("code")} label="Code" required error={errors.code}>
          <Input
            value={values.code}
            disabled={!codeEditable}
            onChange={(e) => update("code", e.target.value)}
          />
        </FormField>
        <FormField id={id("name")} label="Name" required error={errors.name}>
          <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
        </FormField>
      </div>
      <div className="flex flex-col gap-2">
        <Checkbox
          label="Paid by default"
          checked={values.isPaidDefault}
          onChange={(checked) => update("isPaidDefault", checked)}
        />
        <Checkbox
          label="Requires a balance (unchecked for LOP-style types — no ledger entries, no balance check on application)"
          checked={values.requiresBalance}
          onChange={(checked) => update("requiresBalance", checked)}
        />
      </div>
    </div>
  );
}
