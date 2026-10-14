import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  EMPTY_EDUCATION_ROW,
  QUALIFICATION_LABELS,
  QUALIFICATION_VALUES,
  type EducationFormValues,
  type EducationRowValues,
} from "@/lib/onboarding/public-wizard";

interface EducationInfoStepProps {
  values: EducationFormValues;
  errors: Partial<Record<"items", string>>;
  onChange: (values: EducationFormValues) => void;
}

/** Repeatable-rows pattern, same as `PreviousEmploymentStep` — a candidate may hold any number
 * of qualifications, all concurrently valid, so this is an in-form array edited and saved
 * together as one section PATCH, not append-only history. */
export function EducationInfoStep({ values, errors, onChange }: EducationInfoStepProps) {
  function updateRow(index: number, patch: Partial<EducationRowValues>) {
    onChange({
      items: values.items.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    });
  }
  function addRow() {
    onChange({ items: [...values.items, { ...EMPTY_EDUCATION_ROW }] });
  }
  function removeRow(index: number) {
    onChange({ items: values.items.filter((_, i) => i !== index) });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">
          List your educational qualifications, highest first.
        </p>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          Add qualification
        </Button>
      </div>

      {errors.items ? <p className="text-sm text-danger">{errors.items}</p> : null}

      {values.items.length === 0 ? (
        <p className="text-sm text-foreground-muted">No qualifications added yet.</p>
      ) : null}

      {values.items.map((row, index) => (
        <div key={index} className="space-y-4 rounded-md border border-border p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <FormField id={`education-${index}-qualification`} label="Qualification" required>
              <NativeSelect
                value={row.qualification}
                onChange={(e) => updateRow(index, { qualification: e.target.value })}
              >
                <option value="">Select a qualification</option>
                {QUALIFICATION_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {QUALIFICATION_LABELS[value]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField id={`education-${index}-institution`} label="Institution name">
              <Input
                value={row.institutionName}
                onChange={(e) => updateRow(index, { institutionName: e.target.value })}
              />
            </FormField>
            <FormField id={`education-${index}-year`} label="Year of passing">
              <Input
                type="number"
                min="1950"
                max="2100"
                value={row.yearOfPassing}
                onChange={(e) => updateRow(index, { yearOfPassing: e.target.value })}
              />
            </FormField>
          </div>

          <div className="flex justify-end">
            <Button type="button" size="sm" variant="ghost" onClick={() => removeRow(index)}>
              Remove
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
