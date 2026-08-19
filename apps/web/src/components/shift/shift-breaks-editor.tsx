import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { SHIFT_BREAK_KINDS } from "@/lib/shift/types";
import {
  EMPTY_BREAK_FORM_VALUE,
  type ShiftBreakFormErrors,
  type ShiftBreakFormValue,
} from "@/lib/shift/validate-shift-version";

interface ShiftBreaksEditorProps {
  breaks: ShiftBreakFormValue[];
  errors?: ShiftBreakFormErrors[];
  onChange: (breaks: ShiftBreakFormValue[]) => void;
}

/** Full-replace nested editor — mirrors the backend's own posture (breaks have no independent
 * lifecycle, replaced wholesale on every draft PATCH). Reordering just swaps array position;
 * `sort_order` is derived from index at save time. */
export function ShiftBreaksEditor({ breaks, errors, onChange }: ShiftBreaksEditorProps) {
  function updateRow(index: number, patch: Partial<ShiftBreakFormValue>) {
    onChange(breaks.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addRow() {
    onChange([...breaks, { ...EMPTY_BREAK_FORM_VALUE }]);
  }

  function removeRow(index: number) {
    onChange(breaks.filter((_, i) => i !== index));
  }

  function moveRow(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= breaks.length) return;
    const next = breaks.slice();
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-foreground">Breaks</h4>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          Add break
        </Button>
      </div>

      {breaks.length === 0 ? (
        <p className="text-sm text-foreground-muted">No breaks configured for this schedule.</p>
      ) : null}

      {breaks.map((row, index) => {
        const rowErrors = errors?.[index];
        return (
          <div key={index} className="space-y-3 rounded-md border border-border p-4">
            <div className="flex items-center justify-between gap-2">
              <span className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                Break {index + 1}
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
                  disabled={index === breaks.length - 1}
                >
                  Move down
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => removeRow(index)}
                >
                  Remove
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField id={`break-${index}-name`} label="Name" required error={rowErrors?.name}>
                <Input
                  value={row.name}
                  onChange={(e) => updateRow(index, { name: e.target.value })}
                />
              </FormField>
              <FormField id={`break-${index}-kind`} label="Kind" required>
                <NativeSelect
                  value={row.breakKind}
                  onChange={(e) =>
                    updateRow(index, {
                      breakKind: e.target.value as ShiftBreakFormValue["breakKind"],
                    })
                  }
                >
                  {SHIFT_BREAK_KINDS.map((kind) => (
                    <option key={kind} value={kind}>
                      {kind === "FIXED_WINDOW" ? "Fixed window" : "Flexible duration"}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            </div>

            {row.breakKind === "FIXED_WINDOW" ? (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField
                  id={`break-${index}-start`}
                  label="Start time (HH:mm)"
                  required
                  error={rowErrors?.startTime}
                >
                  <Input
                    placeholder="13:00"
                    value={row.startTime}
                    onChange={(e) => updateRow(index, { startTime: e.target.value })}
                  />
                </FormField>
                <FormField
                  id={`break-${index}-end`}
                  label="End time (HH:mm)"
                  required
                  error={rowErrors?.endTime}
                >
                  <Input
                    placeholder="14:00"
                    value={row.endTime}
                    onChange={(e) => updateRow(index, { endTime: e.target.value })}
                  />
                </FormField>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField
                  id={`break-${index}-window-start`}
                  label="Window start (HH:mm)"
                  required
                  error={rowErrors?.windowStart}
                >
                  <Input
                    placeholder="12:00"
                    value={row.windowStart}
                    onChange={(e) => updateRow(index, { windowStart: e.target.value })}
                  />
                </FormField>
                <FormField
                  id={`break-${index}-window-end`}
                  label="Window end (HH:mm)"
                  required
                  error={rowErrors?.windowEnd}
                >
                  <Input
                    placeholder="15:00"
                    value={row.windowEnd}
                    onChange={(e) => updateRow(index, { windowEnd: e.target.value })}
                  />
                </FormField>
                <FormField
                  id={`break-${index}-min`}
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
                  id={`break-${index}-max`}
                  label="Max minutes"
                  required
                  error={rowErrors?.maxMinutes}
                >
                  <Input
                    type="number"
                    value={row.maxMinutes}
                    onChange={(e) => updateRow(index, { maxMinutes: e.target.value })}
                  />
                </FormField>
              </div>
            )}

            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={row.isPaid}
                  onChange={(e) => updateRow(index, { isPaid: e.target.checked })}
                  className="rounded border-border"
                />
                Paid
              </label>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={row.isMandatory}
                  onChange={(e) => updateRow(index, { isMandatory: e.target.checked })}
                  className="rounded border-border"
                />
                Mandatory
              </label>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  checked={row.allowsSplit}
                  onChange={(e) => updateRow(index, { allowsSplit: e.target.checked })}
                  className="rounded border-border"
                />
                Allows split
              </label>
            </div>
          </div>
        );
      })}
    </div>
  );
}
