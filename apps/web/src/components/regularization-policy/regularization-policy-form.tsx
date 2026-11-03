import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type {
  RegularizationPolicyFormErrors,
  RegularizationPolicyFormValues,
} from "@/lib/regularization-policy/validate-regularization-policy";

interface RegularizationPolicyFormProps {
  values: RegularizationPolicyFormValues;
  errors: RegularizationPolicyFormErrors;
  onChange: (values: RegularizationPolicyFormValues) => void;
  idPrefix?: string;
}

export function RegularizationPolicyForm({
  values,
  errors,
  onChange,
  idPrefix = "",
}: RegularizationPolicyFormProps) {
  function update<K extends keyof RegularizationPolicyFormValues>(
    key: K,
    value: RegularizationPolicyFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }
  const id = (name: string) => `${idPrefix}${name}`;
  return (
    <FormField id={id("name")} label="Policy name" required error={errors.name}>
      <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
    </FormField>
  );
}
