import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { STATUTORY_LEAVE_CATEGORIES } from "@/lib/leave-type/types";
import type {
  LeaveTypeFormErrors,
  LeaveTypeFormValues,
} from "@/lib/leave-type/validate-leave-type";

const STATUTORY_CATEGORY_LABELS: Record<string, string> = {
  EARNED: "Earned / Privilege Leave",
  SICK: "Sick Leave",
  CASUAL: "Casual Leave",
  MATERNITY: "Maternity Leave",
  PATERNITY: "Paternity Leave",
};

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
        <Checkbox
          label="This is the company's comp-off type (only one leave type per company may be marked this way — approved overtime credits its balance automatically)"
          checked={values.isCompOff}
          onChange={(checked) => update("isCompOff", checked)}
        />
      </div>
      <FormField
        id={id("statutory-category")}
        label="Statutory category"
        description="Classifies this leave type against a legal minimum (client spec §16) — leave unset for types with no statutory floor (LOP, comp-off, bereavement, ...)."
      >
        <NativeSelect
          value={values.statutoryCategory}
          onChange={(e) =>
            update("statutoryCategory", e.target.value as LeaveTypeFormValues["statutoryCategory"])
          }
        >
          <option value="">None</option>
          {STATUTORY_LEAVE_CATEGORIES.map((category) => (
            <option key={category} value={category}>
              {STATUTORY_CATEGORY_LABELS[category] ?? category}
            </option>
          ))}
        </NativeSelect>
      </FormField>
    </div>
  );
}
