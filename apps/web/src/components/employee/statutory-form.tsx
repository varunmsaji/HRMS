import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { TAX_REGIME_VALUES, type TaxRegime } from "@/lib/employee/types";
import type { StatutoryFormErrors, StatutoryFormValues } from "@/lib/employee/validate-statutory";

interface StatutoryFormProps {
  values: StatutoryFormValues;
  errors: StatutoryFormErrors;
  onChange: (values: StatutoryFormValues) => void;
  idPrefix?: string;
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

export function StatutoryForm({ values, errors, onChange, idPrefix = "" }: StatutoryFormProps) {
  function update<K extends keyof StatutoryFormValues>(key: K, value: StatutoryFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <p className="text-xs text-foreground-muted">
        Every field is required on each revision — nothing carries forward from the current
        statutory row.
      </p>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <FormField id={id("effectiveFrom")} label="Effective from" required error={errors.effectiveFrom}>
          <Input type="date" value={values.effectiveFrom} onChange={(e) => update("effectiveFrom", e.target.value)} />
        </FormField>
        <FormField id={id("taxRegime")} label="Tax regime" required error={errors.taxRegime}>
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
      </div>

      <section>
        <h3 className="text-sm font-medium text-foreground">Provident Fund</h3>
        <div className="mt-3 flex flex-wrap gap-4">
          <Checkbox
            id={id("isPfApplicable")}
            label="PF applicable"
            checked={values.isPfApplicable}
            onChange={(v) => update("isPfApplicable", v)}
          />
          <Checkbox
            id={id("pfWageCeilingOptOut")}
            label="Opted out of PF wage ceiling"
            checked={values.pfWageCeilingOptOut}
            onChange={(v) => update("pfWageCeilingOptOut", v)}
          />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
          <FormField id={id("pfNumber")} label="PF number" error={errors.pfNumber}>
            <Input value={values.pfNumber} onChange={(e) => update("pfNumber", e.target.value)} />
          </FormField>
          <FormField id={id("vpfAmount")} label="VPF amount" error={errors.vpfAmount}>
            <Input type="number" min="0" value={values.vpfAmount} onChange={(e) => update("vpfAmount", e.target.value)} />
          </FormField>
          <FormField id={id("vpfPercentage")} label="VPF percentage" error={errors.vpfPercentage}>
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
            id={id("isEsiApplicable")}
            label="ESI applicable"
            checked={values.isEsiApplicable}
            onChange={(v) => update("isEsiApplicable", v)}
          />
          <Checkbox
            id={id("isLwfApplicable")}
            label="LWF applicable"
            checked={values.isLwfApplicable}
            onChange={(v) => update("isLwfApplicable", v)}
          />
        </div>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("esiIpNumber")} label="ESI IP number" error={errors.esiIpNumber}>
            <Input value={values.esiIpNumber} onChange={(e) => update("esiIpNumber", e.target.value)} />
          </FormField>
          <FormField id={id("ptStateCode")} label="Professional tax state code" error={errors.ptStateCode}>
            <Input value={values.ptStateCode} onChange={(e) => update("ptStateCode", e.target.value)} />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Other</h3>
        <div className="mt-3 flex flex-wrap gap-4">
          <Checkbox
            id={id("isDirector")}
            label="Is a director"
            checked={values.isDirector}
            onChange={(v) => update("isDirector", v)}
          />
          <Checkbox
            id={id("isInternationalWorker")}
            label="International worker"
            checked={values.isInternationalWorker}
            onChange={(v) => update("isInternationalWorker", v)}
          />
        </div>
      </section>

      <FormField id={id("revisionReason")} label="Revision reason" required error={errors.revisionReason}>
        <Input value={values.revisionReason} onChange={(e) => update("revisionReason", e.target.value)} />
      </FormField>
    </div>
  );
}
