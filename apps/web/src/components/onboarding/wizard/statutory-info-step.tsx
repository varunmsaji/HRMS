import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  INDIA_STATE_CODES,
  TAX_REGIME_VALUES,
  type StatutoryInfoFormValues,
  type TaxRegime,
} from "@/lib/onboarding/public-wizard";

const STATE_OPTIONS = Object.entries(INDIA_STATE_CODES).sort((a, b) => a[1].localeCompare(b[1]));

interface StatutoryInfoStepProps {
  values: StatutoryInfoFormValues;
  errors: Partial<Record<keyof StatutoryInfoFormValues, string>>;
  onChange: (values: StatutoryInfoFormValues) => void;
}

function Checkbox({
  id,
  label,
  checked,
  onChange,
}: {
  id: string;
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label htmlFor={id} className="flex items-center gap-2 text-sm text-foreground">
      <input
        id={id}
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="rounded border-border"
      />
      {label}
    </label>
  );
}

export function StatutoryInfoStep({ values, errors, onChange }: StatutoryInfoStepProps) {
  function update<K extends keyof StatutoryInfoFormValues>(
    key: K,
    value: StatutoryInfoFormValues[K],
  ) {
    onChange({ ...values, [key]: value });
  }

  return (
    <div className="space-y-6">
      <FormField id="taxRegime" label="Tax regime" required error={errors.taxRegime}>
        <NativeSelect
          value={values.taxRegime}
          onChange={(e) => update("taxRegime", e.target.value as TaxRegime | "")}
        >
          <option value="">Select a tax regime</option>
          {TAX_REGIME_VALUES.map((regime) => (
            <option key={regime} value={regime}>
              {regime}
            </option>
          ))}
        </NativeSelect>
      </FormField>

      <section>
        <h3 className="text-sm font-medium text-foreground">Provident Fund</h3>
        <div className="mt-3 flex flex-wrap gap-4">
          <Checkbox
            id="isPfApplicable"
            label="PF applicable"
            checked={values.isPfApplicable}
            onChange={(v) => update("isPfApplicable", v)}
          />
          <Checkbox
            id="pfWageCeilingOptOut"
            label="Opted out of PF wage ceiling"
            checked={values.pfWageCeilingOptOut}
            onChange={(v) => update("pfWageCeilingOptOut", v)}
          />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField id="pfNumber" label="PF number" error={errors.pfNumber}>
            <Input value={values.pfNumber} onChange={(e) => update("pfNumber", e.target.value)} />
          </FormField>
          <FormField id="uanNumber" label="UAN" error={errors.uanNumber}>
            <Input value={values.uanNumber} onChange={(e) => update("uanNumber", e.target.value)} />
          </FormField>
          <FormField id="vpfAmount" label="VPF amount" error={errors.vpfAmount}>
            <Input
              type="number"
              min="0"
              value={values.vpfAmount}
              onChange={(e) => update("vpfAmount", e.target.value)}
            />
          </FormField>
          <FormField id="vpfPercentage" label="VPF percentage" error={errors.vpfPercentage}>
            <Input
              type="number"
              min="0"
              step="0.01"
              value={values.vpfPercentage}
              onChange={(e) => update("vpfPercentage", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">ESI &amp; LWF</h3>
        <div className="mt-3 flex flex-wrap gap-4">
          <Checkbox
            id="isEsiApplicable"
            label="ESI applicable"
            checked={values.isEsiApplicable}
            onChange={(v) => update("isEsiApplicable", v)}
          />
          <Checkbox
            id="isLwfApplicable"
            label="LWF applicable"
            checked={values.isLwfApplicable}
            onChange={(v) => update("isLwfApplicable", v)}
          />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id="esiIpNumber" label="ESI IP number" error={errors.esiIpNumber}>
            <Input value={values.esiIpNumber} onChange={(e) => update("esiIpNumber", e.target.value)} />
          </FormField>
          <FormField id="ptStateCode" label="Professional tax state" error={errors.ptStateCode}>
            <NativeSelect
              value={values.ptStateCode}
              onChange={(e) => update("ptStateCode", e.target.value)}
            >
              <option value="">Select a state</option>
              {STATE_OPTIONS.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </NativeSelect>
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Other</h3>
        <div className="mt-3 flex flex-wrap gap-4">
          <Checkbox
            id="isDirector"
            label="Is a director"
            checked={values.isDirector}
            onChange={(v) => update("isDirector", v)}
          />
          <Checkbox
            id="isInternationalWorker"
            label="International worker"
            checked={values.isInternationalWorker}
            onChange={(v) => update("isInternationalWorker", v)}
          />
        </div>
      </section>
    </div>
  );
}
