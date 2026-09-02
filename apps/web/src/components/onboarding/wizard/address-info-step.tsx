import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type { AddressInfoFormValues } from "@/lib/onboarding/public-wizard";

interface AddressInfoStepProps {
  values: AddressInfoFormValues;
  errors: Partial<Record<keyof AddressInfoFormValues, string>>;
  onChange: (values: AddressInfoFormValues) => void;
}

export function AddressInfoStep({ values, errors, onChange }: AddressInfoStepProps) {
  function update<K extends keyof AddressInfoFormValues>(key: K, value: AddressInfoFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <FormField id="addressLine1" label="Address line 1" error={errors.addressLine1} className="sm:col-span-2">
        <Input value={values.addressLine1} onChange={(e) => update("addressLine1", e.target.value)} />
      </FormField>
      <FormField id="addressLine2" label="Address line 2" error={errors.addressLine2} className="sm:col-span-2">
        <Input value={values.addressLine2} onChange={(e) => update("addressLine2", e.target.value)} />
      </FormField>
      <FormField id="city" label="City" error={errors.city}>
        <Input value={values.city} onChange={(e) => update("city", e.target.value)} />
      </FormField>
      <FormField id="stateCode" label="State code" error={errors.stateCode}>
        <Input value={values.stateCode} onChange={(e) => update("stateCode", e.target.value)} />
      </FormField>
      <FormField id="pincode" label="Pincode" error={errors.pincode}>
        <Input value={values.pincode} onChange={(e) => update("pincode", e.target.value)} />
      </FormField>
      <FormField id="countryCode" label="Country code" error={errors.countryCode}>
        <Input
          value={values.countryCode}
          maxLength={2}
          onChange={(e) => update("countryCode", e.target.value.toUpperCase())}
        />
      </FormField>
    </div>
  );
}
