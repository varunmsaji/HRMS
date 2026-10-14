import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { INDIA_STATE_CODES, type AddressInfoFormValues } from "@/lib/onboarding/public-wizard";

interface AddressInfoStepProps {
  values: AddressInfoFormValues;
  errors: Partial<Record<keyof AddressInfoFormValues, string>>;
  onChange: (values: AddressInfoFormValues) => void;
}

const STATE_OPTIONS = Object.entries(INDIA_STATE_CODES).sort((a, b) => a[1].localeCompare(b[1]));

export function AddressInfoStep({ values, errors, onChange }: AddressInfoStepProps) {
  function update<K extends keyof AddressInfoFormValues>(key: K, value: AddressInfoFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Present address</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="addressLine1" label="Address line 1" error={errors.addressLine1} className="sm:col-span-2">
            <Input value={values.addressLine1} onChange={(e) => update("addressLine1", e.target.value)} />
          </FormField>
          <FormField id="addressLine2" label="Address line 2" error={errors.addressLine2} className="sm:col-span-2">
            <Input value={values.addressLine2} onChange={(e) => update("addressLine2", e.target.value)} />
          </FormField>
          <FormField id="city" label="City" error={errors.city}>
            <Input value={values.city} onChange={(e) => update("city", e.target.value)} />
          </FormField>
          <FormField id="stateCode" label="State / union territory" error={errors.stateCode}>
            <NativeSelect
              value={values.stateCode}
              onChange={(e) => update("stateCode", e.target.value)}
            >
              <option value="">Select a state</option>
              {STATE_OPTIONS.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </NativeSelect>
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
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Permanent address</h3>
        <label htmlFor="permanentSameAsPresent" className="mt-3 flex items-center gap-2 text-sm text-foreground">
          <input
            id="permanentSameAsPresent"
            type="checkbox"
            checked={values.permanentSameAsPresent}
            onChange={(e) => update("permanentSameAsPresent", e.target.checked)}
            className="rounded border-border"
          />
          Same as present address
        </label>
        {!values.permanentSameAsPresent && (
          <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField
              id="permanentAddressLine1"
              label="Address line 1"
              error={errors.permanentAddressLine1}
              className="sm:col-span-2"
            >
              <Input
                value={values.permanentAddressLine1}
                onChange={(e) => update("permanentAddressLine1", e.target.value)}
              />
            </FormField>
            <FormField
              id="permanentAddressLine2"
              label="Address line 2"
              error={errors.permanentAddressLine2}
              className="sm:col-span-2"
            >
              <Input
                value={values.permanentAddressLine2}
                onChange={(e) => update("permanentAddressLine2", e.target.value)}
              />
            </FormField>
            <FormField id="permanentCity" label="City" error={errors.permanentCity}>
              <Input value={values.permanentCity} onChange={(e) => update("permanentCity", e.target.value)} />
            </FormField>
            <FormField
              id="permanentStateCode"
              label="State / union territory"
              error={errors.permanentStateCode}
            >
              <NativeSelect
                value={values.permanentStateCode}
                onChange={(e) => update("permanentStateCode", e.target.value)}
              >
                <option value="">Select a state</option>
                {STATE_OPTIONS.map(([code, name]) => (
                  <option key={code} value={code}>
                    {name}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField id="permanentPincode" label="Pincode" error={errors.permanentPincode}>
              <Input
                value={values.permanentPincode}
                onChange={(e) => update("permanentPincode", e.target.value)}
              />
            </FormField>
            <FormField id="permanentCountryCode" label="Country code" error={errors.permanentCountryCode}>
              <Input
                value={values.permanentCountryCode}
                maxLength={2}
                onChange={(e) => update("permanentCountryCode", e.target.value.toUpperCase())}
              />
            </FormField>
          </div>
        )}
      </section>
    </div>
  );
}
