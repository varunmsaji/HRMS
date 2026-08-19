import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  EMPTY_DUTY_BLOCK_FORM_VALUE,
  type ShiftDutyBlockFormValue,
} from "@/lib/shift/validate-shift-version";

interface ShiftDutyBlocksEditorProps {
  dutyBlocks: ShiftDutyBlockFormValue[];
  error?: string;
  onChange: (dutyBlocks: ShiftDutyBlockFormValue[]) => void;
}

/** SPLIT shift type only. `sequence` is derived from array position at save time — the backend
 * requires a contiguous 1..N sequence with no gaps or duplicates (enforced at publish, not
 * mid-edit, since a draft may be incomplete). */
export function ShiftDutyBlocksEditor({ dutyBlocks, error, onChange }: ShiftDutyBlocksEditorProps) {
  function updateRow(index: number, patch: Partial<ShiftDutyBlockFormValue>) {
    onChange(dutyBlocks.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function addRow() {
    onChange([...dutyBlocks, { ...EMPTY_DUTY_BLOCK_FORM_VALUE }]);
  }

  function removeRow(index: number) {
    onChange(dutyBlocks.filter((_, i) => i !== index));
  }

  function moveRow(index: number, direction: -1 | 1) {
    const target = index + direction;
    if (target < 0 || target >= dutyBlocks.length) return;
    const next = dutyBlocks.slice();
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-medium text-foreground">Duty blocks</h4>
        <Button type="button" size="sm" variant="outline" onClick={addRow}>
          Add duty block
        </Button>
      </div>
      <p className="text-xs text-foreground-muted">
        A split shift needs at least 2 blocks (e.g. 09:00–13:00 and 17:00–21:00).
      </p>
      {error ? <p className="text-sm text-danger">{error}</p> : null}

      {dutyBlocks.map((row, index) => (
        <div
          key={index}
          className="flex flex-wrap items-end gap-4 rounded-md border border-border p-4"
        >
          <span className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
            Block {index + 1}
          </span>
          <FormField id={`duty-block-${index}-start`} label="Start time (HH:mm)" required>
            <Input
              placeholder="09:00"
              value={row.startTime}
              onChange={(e) => updateRow(index, { startTime: e.target.value })}
            />
          </FormField>
          <FormField id={`duty-block-${index}-end`} label="End time (HH:mm)" required>
            <Input
              placeholder="13:00"
              value={row.endTime}
              onChange={(e) => updateRow(index, { endTime: e.target.value })}
            />
          </FormField>
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
              disabled={index === dutyBlocks.length - 1}
            >
              Move down
            </Button>
            <Button type="button" size="sm" variant="ghost" onClick={() => removeRow(index)}>
              Remove
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
