import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type {
  OvertimePolicyFormErrors,
  OvertimePolicyFormValues,
} from "@/lib/overtime-policy/validate-overtime-policy";

interface OvertimePolicyFormProps {
  values: OvertimePolicyFormValues;
  errors: OvertimePolicyFormErrors;
  onChange: (values: OvertimePolicyFormValues) => void;
  idPrefix?: string;
}

export function OvertimePolicyForm({
  values,
  errors,
  onChange,
  idPrefix = "",
}: OvertimePolicyFormProps) {
  function update<K extends keyof OvertimePolicyFormValues>(
    key: K,
    value: OvertimePolicyFormValues[K],
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
