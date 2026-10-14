import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  EMPTY_NOMINEE_ROW,
  GENDER_LABELS,
  GENDER_VALUES,
  RELATIONSHIP_LABELS,
  RELATIONSHIP_VALUES,
  nomineeGratuityPercentageTotal,
  nomineePfPercentageTotal,
  type NomineeFormValues,
  type NomineeRowValues,
} from "@/lib/onboarding/public-wizard";

interface NomineeInfoStepProps {
  values: NomineeFormValues;
  errors: Partial<Record<"items", string>>;
  onChange: (values: NomineeFormValues) => void;
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

function PercentageTotal({ label, total }: { label: string; total: number }) {
  const overLimit = total > 100;
  return (
    <p className={`text-xs ${overLimit ? "text-danger" : "text-foreground-muted"}`}>
      {label}: {total}% of 100% allocated
      {overLimit ? " — exceeds 100%" : ""}
    </p>
  );
}

/** Repeatable-rows pattern, same as `PreviousEmploymentStep`/`EducationInfoStep` — an employee
 * may declare any number of PF/Gratuity nominees and ESI family members, all concurrently valid,
 * so this is an in-form array edited and saved together as one section PATCH. Unlike those two,
 * each row also carries a minor/guardian conditional block and two independent nominee-scheme
 * percentages, so this step renders a live running total next to each scheme — the candidate
 * sees the 100% ceiling before submitting rather than only after a rejected PATCH. */
export function NomineeInfoStep({ values, errors, onChange }: NomineeInfoStepProps) {
  function updateRow(index: number, patch: Partial<NomineeRowValues>) {
    onChange({
      items: values.items.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    });
  }
  function addRow() {
    onChange({ items: [...values.items, { ...EMPTY_NOMINEE_ROW }] });
  }
  function removeRow(index: number) {
    onChange({ items: values.items.filter((_, i) => i !== index) });
  }

  const pfTotal = nomineePfPercentageTotal(values);
  const gratuityTotal = nomineeGratuityPercentageTotal(values);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">
          Declare your PF/Gratuity nominees and ESI-covered family members.
        </p>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          Add nominee
        </Button>
      </div>

      {(pfTotal > 0 || gratuityTotal > 0) ? (
        <div className="space-y-1 rounded-md border border-border bg-muted/40 p-3">
          <PercentageTotal label="PF nominee share" total={pfTotal} />
          <PercentageTotal label="Gratuity nominee share" total={gratuityTotal} />
        </div>
      ) : null}

      {errors.items ? <p className="text-sm text-danger">{errors.items}</p> : null}

      {values.items.length === 0 ? (
        <p className="text-sm text-foreground-muted">No nominees added yet.</p>
      ) : null}

      {values.items.map((row, index) => (
        <div key={index} className="space-y-4 rounded-md border border-border p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <FormField id={`nominee-${index}-full-name`} label="Full name" required>
              <Input
                value={row.fullName}
                onChange={(e) => updateRow(index, { fullName: e.target.value })}
              />
            </FormField>
            <FormField id={`nominee-${index}-relationship`} label="Relationship" required>
              <NativeSelect
                value={row.relationship}
                onChange={(e) => updateRow(index, { relationship: e.target.value })}
              >
                <option value="">Select a relationship</option>
                {RELATIONSHIP_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {RELATIONSHIP_LABELS[value]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField id={`nominee-${index}-dob`} label="Date of birth">
              <Input
                type="date"
                value={row.dateOfBirth}
                onChange={(e) => updateRow(index, { dateOfBirth: e.target.value })}
              />
            </FormField>
            <FormField id={`nominee-${index}-gender`} label="Gender">
              <NativeSelect
                value={row.gender}
                onChange={(e) => updateRow(index, { gender: e.target.value })}
              >
                <option value="">Select gender</option>
                {GENDER_VALUES.map((value) => (
                  <option key={value} value={value}>
                    {GENDER_LABELS[value]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField id={`nominee-${index}-aadhaar`} label="Aadhaar number">
              <Input
                value={row.aadhaarNumber}
                maxLength={12}
                onChange={(e) => updateRow(index, { aadhaarNumber: e.target.value })}
              />
            </FormField>
          </div>

          <div className="flex flex-wrap gap-4">
            <Checkbox
              id={`nominee-${index}-is-minor`}
              label="Minor"
              checked={row.isMinor}
              onChange={(v) => updateRow(index, { isMinor: v })}
            />
            <Checkbox
              id={`nominee-${index}-is-pf-nominee`}
              label="PF nominee"
              checked={row.isPfNominee}
              onChange={(v) => updateRow(index, { isPfNominee: v })}
            />
            <Checkbox
              id={`nominee-${index}-is-gratuity-nominee`}
              label="Gratuity nominee"
              checked={row.isGratuityNominee}
              onChange={(v) => updateRow(index, { isGratuityNominee: v })}
            />
            <Checkbox
              id={`nominee-${index}-is-esi-dependent`}
              label="ESI family member"
              checked={row.isEsiDependent}
              onChange={(v) => updateRow(index, { isEsiDependent: v })}
            />
          </div>

          {row.isMinor ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField id={`nominee-${index}-guardian-name`} label="Guardian name" required>
                <Input
                  value={row.guardianName}
                  onChange={(e) => updateRow(index, { guardianName: e.target.value })}
                />
              </FormField>
              <FormField
                id={`nominee-${index}-guardian-relationship`}
                label="Guardian relationship"
              >
                <NativeSelect
                  value={row.guardianRelationship}
                  onChange={(e) => updateRow(index, { guardianRelationship: e.target.value })}
                >
                  <option value="">Select a relationship</option>
                  {RELATIONSHIP_VALUES.map((value) => (
                    <option key={value} value={value}>
                      {RELATIONSHIP_LABELS[value]}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            </div>
          ) : null}

          {(row.isPfNominee || row.isGratuityNominee) ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              {row.isPfNominee ? (
                <FormField
                  id={`nominee-${index}-pf-share`}
                  label="PF nominee share %"
                  required
                >
                  <Input
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={row.pfNomineeSharePercentage}
                    onChange={(e) =>
                      updateRow(index, { pfNomineeSharePercentage: e.target.value })
                    }
                  />
                </FormField>
              ) : null}
              {row.isGratuityNominee ? (
                <FormField
                  id={`nominee-${index}-gratuity-share`}
                  label="Gratuity nominee share %"
                  required
                >
                  <Input
                    type="number"
                    min="0"
                    max="100"
                    step="0.01"
                    value={row.gratuityNomineeSharePercentage}
                    onChange={(e) =>
                      updateRow(index, { gratuityNomineeSharePercentage: e.target.value })
                    }
                  />
                </FormField>
              ) : null}
            </div>
          ) : null}

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
