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
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <FormField id={id("name")} label="Policy name" required error={errors.name}>
        <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
      </FormField>
      <FormField id={id("code")} label="Policy code" error={errors.code}>
        <Input value={values.code} onChange={(e) => update("code", e.target.value)} />
      </FormField>
    </div>
  );
}
