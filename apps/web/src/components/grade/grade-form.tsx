import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type { GradeFormErrors, GradeFormValues } from "@/lib/grade/validate-grade";

interface GradeFormProps {
  values: GradeFormValues;
  errors: GradeFormErrors;
  onChange: (values: GradeFormValues) => void;
  idPrefix?: string;
}

export function GradeForm({ values, errors, onChange, idPrefix = "" }: GradeFormProps) {
  function update<K extends keyof GradeFormValues>(key: K, value: GradeFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Identity</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("code")} label="Grade code" required error={errors.code}>
            <Input value={values.code} onChange={(e) => update("code", e.target.value)} />
          </FormField>
          <FormField id={id("name")} label="Grade name" required error={errors.name}>
            <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
          </FormField>
          <FormField id={id("level")} label="Level" error={errors.level}>
            <Input
              type="number"
              value={values.level}
              onChange={(e) => update("level", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Compensation band</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Optional. Amounts are in whole rupees; a grade can exist before its compensation
          band is decided.
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("minCtc")} label="Min CTC (₹)" error={errors.minCtc}>
            <Input
              type="number"
              value={values.minCtc}
              onChange={(e) => update("minCtc", e.target.value)}
            />
          </FormField>
          <FormField id={id("maxCtc")} label="Max CTC (₹)" error={errors.maxCtc}>
            <Input
              type="number"
              value={values.maxCtc}
              onChange={(e) => update("maxCtc", e.target.value)}
            />
          </FormField>
          <FormField id={id("approvalLimit")} label="Approval limit (₹)" error={errors.approvalLimit}>
            <Input
              type="number"
              value={values.approvalLimit}
              onChange={(e) => update("approvalLimit", e.target.value)}
            />
          </FormField>
        </div>
      </section>

      <section>
        <h3 className="text-sm font-medium text-foreground">Overrides</h3>
        <p className="mt-1 text-xs text-foreground-muted">
          Optional overrides in the Company → Branch → Department → Grade → Employee chain
          (most specific wins).
        </p>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("noticePeriodDays")} label="Notice period (days)" error={errors.noticePeriodDays}>
            <Input
              type="number"
              value={values.noticePeriodDays}
              onChange={(e) => update("noticePeriodDays", e.target.value)}
            />
          </FormField>
          <FormField id={id("probationDays")} label="Probation (days)" error={errors.probationDays}>
            <Input
              type="number"
              value={values.probationDays}
              onChange={(e) => update("probationDays", e.target.value)}
            />
          </FormField>
        </div>
      </section>
    </div>
  );
}
