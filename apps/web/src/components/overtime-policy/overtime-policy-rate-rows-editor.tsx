import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { DAY_CLASS_LABELS } from "@/lib/overtime-policy/labels";
import { DAY_CLASSES } from "@/lib/overtime-policy/types";
import {
  EMPTY_RATE_ROW,
  type OvertimeRateRowFormValue,
} from "@/lib/overtime-policy/validate-overtime-policy";

interface OvertimePolicyRateRowsEditorProps {
  rows: OvertimeRateRowFormValue[];
  onChange: (rows: OvertimeRateRowFormValue[]) => void;
}

/** `day_class` must be unique within a version (backend `INVALID_POLICY_RATE_ROW`) — not
 * re-validated client-side, since the `NativeSelect` doesn't prevent picking the same class
 * twice across rows; the backend error surfaces via the shared `rateRows` banner instead. */
export function OvertimePolicyRateRowsEditor({ rows, onChange }: OvertimePolicyRateRowsEditorProps) {
  function updateRow(index: number, patch: Partial<OvertimeRateRowFormValue>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }
  function addRow() {
    onChange([...rows, { ...EMPTY_RATE_ROW }]);
  }
  function removeRow(index: number) {
    onChange(rows.filter((_, i) => i !== index));
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-medium text-foreground">Overtime labels</h4>
          <p className="text-xs text-foreground-muted">
            Stamps a label on overtime worked on each kind of day. Payroll uses the label to decide
            how it is paid. The multiplier is for information only and never becomes money here.
            Each kind of day can appear once.
          </p>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          Add label
        </Button>
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-foreground-muted">No labels configured. Overtime will have no label.</p>
      ) : null}

      {rows.map((row, index) => (
        <div key={index} className="grid grid-cols-1 gap-4 rounded-md border border-border p-4 sm:grid-cols-4">
          <FormField id={`rate-row-${index}-class`} label="Kind of day" required>
            <NativeSelect
              value={row.dayClass}
              onChange={(e) => updateRow(index, { dayClass: e.target.value })}
            >
              {DAY_CLASSES.map((c) => (
                <option key={c} value={c}>
                  {DAY_CLASS_LABELS[c] ?? c}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id={`rate-row-${index}-code`} label="Label for payroll" required>
            <Input
              value={row.classificationCode}
              onChange={(e) => updateRow(index, { classificationCode: e.target.value })}
              placeholder="OT_NORMAL"
            />
          </FormField>
          <FormField id={`rate-row-${index}-multiplier`} label="Multiplier (information only)">
            <Input
              value={row.multiplierDecimal}
              onChange={(e) => updateRow(index, { multiplierDecimal: e.target.value })}
              placeholder="1.5000"
            />
          </FormField>
          <div className="flex items-end">
            <Button type="button" size="sm" variant="ghost" onClick={() => removeRow(index)}>
              Remove
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
