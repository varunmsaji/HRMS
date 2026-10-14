import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  RELATIONSHIP_LABELS,
  RELATIONSHIP_VALUES,
  type EmergencyContactFormValues,
} from "@/lib/onboarding/public-wizard";

interface EmergencyContactStepProps {
  values: EmergencyContactFormValues;
  errors: Partial<Record<keyof EmergencyContactFormValues, string>>;
  onChange: (values: EmergencyContactFormValues) => void;
}

export function EmergencyContactStep({ values, errors, onChange }: EmergencyContactStepProps) {
  function update<K extends keyof EmergencyContactFormValues>(
    key: K,
    value: EmergencyContactFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <FormField id="contactName" label="Contact name" required error={errors.contactName}>
        <Input value={values.contactName} onChange={(e) => update("contactName", e.target.value)} />
      </FormField>
      <FormField id="relationship" label="Relationship" error={errors.relationship}>
        <NativeSelect
          value={values.relationship}
          onChange={(e) => update("relationship", e.target.value)}
        >
          <option value="">Select a relationship</option>
          {RELATIONSHIP_VALUES.map((value) => (
            <option key={value} value={value}>
              {RELATIONSHIP_LABELS[value]}
            </option>
          ))}
        </NativeSelect>
      </FormField>
      <FormField id="phone" label="Phone number" required error={errors.phone}>
        <Input value={values.phone} onChange={(e) => update("phone", e.target.value)} />
      </FormField>
    </div>
  );
}
