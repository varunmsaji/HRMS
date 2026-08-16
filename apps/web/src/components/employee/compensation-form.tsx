import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { REVISION_TYPE_VALUES, type RevisionType } from "@/lib/employee/types";
import {
  REVISION_TYPE_LABELS,
  type CompensationFormErrors,
  type CompensationFormValues,
} from "@/lib/employee/validate-compensation";

interface CompensationFormProps {
  values: CompensationFormValues;
  errors: CompensationFormErrors;
  onChange: (values: CompensationFormValues) => void;
  idPrefix?: string;
}

export function CompensationForm({ values, errors, onChange, idPrefix = "" }: CompensationFormProps) {
  function update<K extends keyof CompensationFormValues>(key: K, value: CompensationFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-4">
      <p className="text-xs text-foreground-muted">
        Every field is required on each revision — nothing carries forward from the current
        compensation row.
      </p>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id={id("effectiveFrom")} label="Effective from" required error={errors.effectiveFrom}>
          <Input type="date" value={values.effectiveFrom} onChange={(e) => update("effectiveFrom", e.target.value)} />
        </FormField>
        <FormField id={id("revisionType")} label="Revision type" required error={errors.revisionType}>
          <NativeSelect
            value={values.revisionType}
            onChange={(e) => update("revisionType", e.target.value as RevisionType | "")}
          >
            <option value="">Select a revision type</option>
            {REVISION_TYPE_VALUES.map((type) => (
              <option key={type} value={type}>
                {REVISION_TYPE_LABELS[type]}
              </option>
            ))}
          </NativeSelect>
        </FormField>
        <FormField id={id("annualCtc")} label="Annual CTC" required error={errors.annualCtc}>
          <Input
            type="number"
            min="0"
            step="0.01"
            value={values.annualCtc}
            onChange={(e) => update("annualCtc", e.target.value)}
          />
        </FormField>
        <FormField id={id("currency")} label="Currency" required error={errors.currency}>
          <Input
            value={values.currency}
            onChange={(e) => update("currency", e.target.value.toUpperCase())}
            maxLength={3}
            placeholder="INR"
          />
        </FormField>
        <FormField
          id={id("revisionReason")}
          label="Revision reason"
          required
          error={errors.revisionReason}
          className="sm:col-span-2"
        >
          <Input value={values.revisionReason} onChange={(e) => update("revisionReason", e.target.value)} />
        </FormField>
      </div>
    </div>
  );
}
