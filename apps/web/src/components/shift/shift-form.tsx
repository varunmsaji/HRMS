import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import type { ShiftFormErrors, ShiftFormValues } from "@/lib/shift/validate-shift";

interface ShiftFormProps {
  values: ShiftFormValues;
  errors: ShiftFormErrors;
  onChange: (values: ShiftFormValues) => void;
  idPrefix?: string;
  /** Hide the code field (create flow — the server assigns one). */
}

/** W2 — identity only (name/code). Schedule configuration (timings, breaks, duty blocks) lives
 * on the Versions tab (`ShiftVersionForm`) — deliberately kept separate so it's obvious SHIFT =
 * SCHEDULE, not an attendance-policy editor. */
export function ShiftForm({ values, errors, onChange, idPrefix = "" }: ShiftFormProps) {
  function update<K extends keyof ShiftFormValues>(key: K, value: ShiftFormValues[K]) {
    onChange({ ...values, [key]: value });
  }

  const id = (name: string) => `${idPrefix}${name}`;

  return (
    <div className="space-y-6">
      <section>
        <h3 className="text-sm font-medium text-foreground">Identity</h3>
        <div className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
          <FormField id={id("name")} label="Shift name" required error={errors.name}>
            <Input value={values.name} onChange={(e) => update("name", e.target.value)} />
          </FormField>
        </div>
      </section>
    </div>
  );
}
