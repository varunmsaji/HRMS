import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  emptyBandRow,
  type PolicyBandFormRow,
  type PolicyBandRowErrors,
} from "@/lib/attendance-policy/validate-attendance-policy";

interface PolicyBandsEditorProps {
  title: string;
  description: string;
  rows: PolicyBandFormRow[];
  errors?: PolicyBandRowErrors[];
  statusLabel: string;
  statusOptions: readonly string[];
  showCountsTowardCap: boolean;
  idPrefix: string;
  onChange: (rows: PolicyBandFormRow[]) => void;
}

/** Shared editor for hour bands / late bands / early-departure bands (architecture §9/§11.1) —
 * one typed child-table shape reused three times rather than three near-duplicate components,
 * since the row shape (min/max minutes + a status classification) is identical. Full-replace on
 * every draft save, mirroring `ShiftBreaksEditor`; `sort_order` is derived from array index. */
export function PolicyBandsEditor({
  title,
  description,
  rows,
  errors,
  statusLabel,
  statusOptions,
  showCountsTowardCap,
  idPrefix,
  onChange,
}: PolicyBandsEditorProps) {
  function updateRow(index: number, patch: Partial<PolicyBandFormRow>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addRow() {
    onChange([...rows, emptyBandRow(statusOptions[0])]);
  }

  function removeRow(index: number) {
    onChange(rows.filter((_, i) => i !== index));
  }

  function moveRow(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= rows.length) return;
    const next = rows.slice();
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h4 className="text-sm font-medium text-foreground">{title}</h4>
          <p className="text-xs text-foreground-muted">{description}</p>
        </div>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          Add band
        </Button>
      </div>

      {rows.length === 0 ? (
        <p className="text-sm text-foreground-muted">No bands configured.</p>
      ) : null}

      {rows.map((row, index) => {
        const rowErrors = errors?.[index];
        return (
          <div key={index} className="space-y-3 rounded-md border border-border p-4">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                Band {index + 1}
              </span>
              <div className="flex items-center gap-1">
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => moveRow(index, -1)}
                  disabled={index === 0}
                >
                  Move up
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => moveRow(index, 1)}
                  disabled={index === rows.length - 1}
                >
                  Move down
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={() => removeRow(index)}>
                  Remove
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <FormField
                id={`${idPrefix}-${index}-min`}
                label="Min minutes"
                required
                error={rowErrors?.minMinutes}
              >
                <Input
                  type="number"
                  value={row.minMinutes}
                  onChange={(e) => updateRow(index, { minMinutes: e.target.value })}
                />
              </FormField>
              <FormField
                id={`${idPrefix}-${index}-max`}
                label="Max minutes"
                description="Leave blank for open-ended (only the last band may be open-ended)."
                error={rowErrors?.maxMinutes}
              >
                <Input
                  type="number"
                  value={row.maxMinutes}
                  onChange={(e) => updateRow(index, { maxMinutes: e.target.value })}
                />
              </FormField>
              <FormField id={`${idPrefix}-${index}-status`} label={statusLabel} required>
                <NativeSelect
                  value={row.status}
                  onChange={(e) => updateRow(index, { status: e.target.value })}
                >
                  {statusOptions.map((option) => (
                    <option key={option} value={option}>
                      {option.replaceAll("_", " ")}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            </div>

            {showCountsTowardCap ? (
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={row.countsTowardCap}
                  onChange={(e) => updateRow(index, { countsTowardCap: e.target.checked })}
                  className="rounded border-border"
                />
                Counts toward monthly cap
              </label>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
