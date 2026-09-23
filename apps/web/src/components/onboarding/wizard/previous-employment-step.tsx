import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  EMPTY_PREVIOUS_EMPLOYMENT_ROW,
  type PreviousEmploymentFormValues,
  type PreviousEmploymentRowValues,
} from "@/lib/onboarding/public-wizard";

interface PreviousEmploymentStepProps {
  values: PreviousEmploymentFormValues;
  errors: Partial<Record<"items", string>>;
  onChange: (values: PreviousEmploymentFormValues) => void;
}

/** Repeatable-rows pattern, same as `OvertimePolicyRateRowsEditor` — a candidate may have any
 * number of past employers (including zero, for a fresher), all concurrently valid, so this is
 * an in-form array edited and saved together as one section PATCH, not append-only history. */
export function PreviousEmploymentStep({ values, errors, onChange }: PreviousEmploymentStepProps) {
  function updateRow(index: number, patch: Partial<PreviousEmploymentRowValues>) {
    onChange({
      items: values.items.map((row, i) => (i === index ? { ...row, ...patch } : row)),
    });
  }
  function addRow() {
    onChange({ items: [...values.items, { ...EMPTY_PREVIOUS_EMPLOYMENT_ROW }] });
  }
  function removeRow(index: number) {
    onChange({ items: values.items.filter((_, i) => i !== index) });
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <p className="text-xs text-foreground-muted">
          List your previous employers, if any — this helps HR carry forward your PF account.
        </p>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          Add employer
        </Button>
      </div>

      {errors.items ? <p className="text-sm text-danger">{errors.items}</p> : null}

      {values.items.length === 0 ? (
        <p className="text-sm text-foreground-muted">
          No previous employers added. If this is your first job, you can continue without
          adding any.
        </p>
      ) : null}

      {values.items.map((row, index) => (
        <div key={index} className="space-y-4 rounded-md border border-border p-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <FormField id={`prev-emp-${index}-company`} label="Company name" required>
              <Input
                value={row.companyName}
                onChange={(e) => updateRow(index, { companyName: e.target.value })}
              />
            </FormField>
            <FormField id={`prev-emp-${index}-designation`} label="Designation">
              <Input
                value={row.designation}
                onChange={(e) => updateRow(index, { designation: e.target.value })}
              />
            </FormField>
            <FormField id={`prev-emp-${index}-from`} label="From date" required>
              <Input
                type="date"
                value={row.fromDate}
                onChange={(e) => updateRow(index, { fromDate: e.target.value })}
              />
            </FormField>
            <FormField id={`prev-emp-${index}-to`} label="To date">
              <Input
                type="date"
                value={row.toDate}
                onChange={(e) => updateRow(index, { toDate: e.target.value })}
              />
            </FormField>
            <FormField id={`prev-emp-${index}-ctc`} label="Last drawn annual CTC">
              <Input
                type="number"
                min="0"
                step="0.01"
                value={row.lastCtc}
                onChange={(e) => updateRow(index, { lastCtc: e.target.value })}
              />
            </FormField>
            <FormField id={`prev-emp-${index}-reason`} label="Reason for leaving">
              <Input
                value={row.reasonForLeaving}
                onChange={(e) => updateRow(index, { reasonForLeaving: e.target.value })}
              />
            </FormField>
          </div>

          <label
            htmlFor={`prev-emp-${index}-pf`}
            className="flex items-center gap-2 text-sm text-foreground"
          >
            <input
              id={`prev-emp-${index}-pf`}
              type="checkbox"
              checked={row.hadPriorPfMembership}
              onChange={(e) => updateRow(index, { hadPriorPfMembership: e.target.checked })}
              className="rounded border-border"
            />
            I was a PF member at this employer
          </label>

          {row.hadPriorPfMembership ? (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <FormField id={`prev-emp-${index}-uan`} label="UAN at this employer">
                <Input
                  value={row.previousUan}
                  onChange={(e) => updateRow(index, { previousUan: e.target.value })}
                />
              </FormField>
              <FormField id={`prev-emp-${index}-pf-account`} label="PF account number">
                <Input
                  value={row.previousPfAccountNumber}
                  onChange={(e) => updateRow(index, { previousPfAccountNumber: e.target.value })}
                />
              </FormField>
              <FormField id={`prev-emp-${index}-esi`} label="ESI IP number">
                <Input
                  value={row.previousEsiIpNumber}
                  onChange={(e) => updateRow(index, { previousEsiIpNumber: e.target.value })}
                />
              </FormField>
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
