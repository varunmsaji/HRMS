import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type { CompensationInfoFormValues } from "@/lib/onboarding/public-wizard";

interface CompensationInfoStepProps {
  values: CompensationInfoFormValues;
  errors: Partial<Record<keyof CompensationInfoFormValues, string>>;
  onChange: (values: CompensationInfoFormValues) => void;
}

export function CompensationInfoStep({ values, errors, onChange }: CompensationInfoStepProps) {
  function update<K extends keyof CompensationInfoFormValues>(
    key: K,
    value: CompensationInfoFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <FormField
        id="annualCtc"
        label="Annual CTC"
        required
        error={errors.annualCtc}
        description="Your agreed annual cost-to-company, as discussed with HR."
      >
        <Input
          type="number"
          min="0"
          step="0.01"
          value={values.annualCtc}
          onChange={(e) => update("annualCtc", e.target.value)}
        />
      </FormField>
      <FormField id="currency" label="Currency" required error={errors.currency}>
        <Input
          value={values.currency}
          maxLength={3}
          onChange={(e) => update("currency", e.target.value.toUpperCase())}
        />
      </FormField>
    </div>
  );
}
