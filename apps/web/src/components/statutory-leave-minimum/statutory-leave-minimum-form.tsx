import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { STATUTORY_LEAVE_CATEGORIES } from "@/lib/leave-type/types";
import type {
  StatutoryLeaveMinimumFormErrors,
  StatutoryLeaveMinimumFormValues,
} from "@/lib/statutory-leave-minimum/validate-statutory-leave-minimum";

interface StatutoryLeaveMinimumFormProps {
  values: StatutoryLeaveMinimumFormValues;
  errors: StatutoryLeaveMinimumFormErrors;
  onChange: (values: StatutoryLeaveMinimumFormValues) => void;
  idPrefix?: string;
}

const STATUTORY_CATEGORY_LABELS: Record<string, string> = {
  EARNED: "Earned / Privilege Leave",
  SICK: "Sick Leave",
  CASUAL: "Casual Leave",
  MATERNITY: "Maternity Leave",
  PATERNITY: "Paternity Leave",
};

/** Client spec §16 (LEAVE_DECISION_LOG.md LD-22) — a flat identity row, no edit. Changing a
 * minimum is delete-and-recreate, same posture as `LeaveCombinationRuleForm`. */
export function StatutoryLeaveMinimumForm({
  values,
  errors,
  onChange,
  idPrefix = "",
}: StatutoryLeaveMinimumFormProps) {
  function update<K extends keyof StatutoryLeaveMinimumFormValues>(
    key: K,
    value: StatutoryLeaveMinimumFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField
          id={id("leave-category")}
          label="Leave category"
          required
          error={errors.leaveCategory}
        >
          <NativeSelect
            value={values.leaveCategory}
            onChange={(e) =>
              update(
                "leaveCategory",
                e.target.value as StatutoryLeaveMinimumFormValues["leaveCategory"],
              )
            }
          >
            <option value="">Choose…</option>
            {STATUTORY_LEAVE_CATEGORIES.map((category) => (
              <option key={category} value={category}>
                {STATUTORY_CATEGORY_LABELS[category] ?? category}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField
          id={id("min-days")}
          label="Minimum days / year"
          required
          error={errors.minDaysPerYear}
        >
          <Input
            value={values.minDaysPerYear}
            onChange={(e) => update("minDaysPerYear", e.target.value)}
            placeholder="12"
          />
        </FormField>
      </div>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField
          id={id("state-code")}
          label="State"
          description="Optional — leave blank if this minimum applies regardless of state."
        >
          <Input
            value={values.stateCode}
            onChange={(e) => update("stateCode", e.target.value)}
            placeholder="KA"
          />
        </FormField>
        <FormField
          id={id("establishment-type")}
          label="Establishment type"
          description="Optional — e.g. Shop & Establishment, Factory, IT/ITES."
        >
          <Input
            value={values.establishmentType}
            onChange={(e) => update("establishmentType", e.target.value)}
          />
        </FormField>
      </div>
      <FormField
        id={id("note")}
        label="Note"
        description="Optional — e.g. a citation for where this figure comes from."
      >
        <Input value={values.note} onChange={(e) => update("note", e.target.value)} />
      </FormField>
    </div>
  );
}
