"use client";

import { Plus, Trash2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import {
  APPLIES_WHEN,
  APPLIES_WHEN_LABELS,
  CALCULATION_TYPE_LABELS,
  CALCULATION_TYPES,
  formatInr,
  rupeesToMinor,
  type AppliesWhen,
  type CalculationType,
  type SalaryComponent,
  type SalaryStructureLine,
  type SalaryStructureLineInput,
} from "@/lib/payroll/types";

/** One structure line as the editor holds it — amounts in rupees, as typed. */
export interface LineRow {
  componentId: string;
  calculationType: CalculationType;
  percentage: string;
  amount: string;
  baseId: string;
  cap: string;
  appliesWhen: AppliesWhen;
}

export const EMPTY_LINE_ROW: LineRow = {
  componentId: "",
  calculationType: "FIXED",
  percentage: "",
  amount: "",
  baseId: "",
  cap: "",
  appliesWhen: "ALWAYS",
};

export function toRow(line: SalaryStructureLine): LineRow {
  return {
    componentId: line.salary_component_id,
    calculationType: line.calculation_type,
    percentage: line.percentage ?? "",
    amount:
      line.amount_monthly_minor !== null
        ? String(line.amount_monthly_minor / 100)
        : "",
    baseId: line.base_salary_component_id ?? "",
    cap:
      line.max_monthly_minor !== null
        ? String(line.max_monthly_minor / 100)
        : "",
    appliesWhen: line.applies_when,
  };
}

export function toInput(row: LineRow, index: number): SalaryStructureLineInput {
  const needsPercentage = row.calculationType.startsWith("PERCENTAGE");
  return {
    salary_component_id: row.componentId,
    calculation_type: row.calculationType,
    percentage: needsPercentage && row.percentage ? row.percentage : null,
    amount_monthly_minor:
      row.calculationType === "FIXED" ? rupeesToMinor(row.amount) : null,
    base_salary_component_id:
      row.calculationType === "PERCENTAGE_OF_COMPONENT" && row.baseId
        ? row.baseId
        : null,
    max_monthly_minor: row.cap ? rupeesToMinor(row.cap) : null,
    applies_when: row.appliesWhen,
    display_order: (index + 1) * 10,
  };
}

/** Editable structure lines: component, how it is calculated, and its percentage / amount /
 * base / cap. With `amounts` (monthly paise by component id), each row also shows what it pays. */
export function StructureLinesEditor({
  rows,
  onChange,
  components,
  amounts,
}: {
  rows: LineRow[];
  onChange: (rows: LineRow[]) => void;
  components: SalaryComponent[];
  amounts?: Record<string, number>;
}) {
  const usable = components.filter(
    (c) => c.is_active && c.component_type !== "DEDUCTION",
  );
  const earnings = usable.filter((c) => c.component_type === "EARNING");

  function updateRow(index: number, patch: Partial<LineRow>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  return (
    <div className="space-y-3">
      {rows.map((row, index) => {
        const component = usable.find((c) => c.id === row.componentId);
        const amount = amounts?.[row.componentId];
        return (
          <div
            key={index}
            className="grid grid-cols-1 gap-2 rounded-md border border-border bg-surface-secondary/30 p-3 md:grid-cols-6"
          >
            <NativeSelect
              aria-label="Component"
              value={row.componentId}
              onChange={(e) =>
                updateRow(index, { componentId: e.target.value })
              }
            >
              <option value="">Component…</option>
              {usable.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
            <NativeSelect
              aria-label="Calculation"
              value={row.calculationType}
              onChange={(e) =>
                updateRow(index, {
                  calculationType: e.target.value as CalculationType,
                })
              }
            >
              {CALCULATION_TYPES.filter(
                (t) =>
                  component?.component_type !== "EMPLOYER_CONTRIBUTION" ||
                  (t !== "BALANCING" && t !== "PERCENTAGE_OF_GROSS"),
              ).map((t) => (
                <option key={t} value={t}>
                  {CALCULATION_TYPE_LABELS[t]}
                </option>
              ))}
            </NativeSelect>
            {row.calculationType === "FIXED" ? (
              <Input
                aria-label="Monthly amount (₹)"
                placeholder="₹ a month"
                value={row.amount}
                onChange={(e) => updateRow(index, { amount: e.target.value })}
              />
            ) : row.calculationType === "BALANCING" ? (
              <div className="self-center text-xs text-foreground-muted">
                Takes whatever remains of gross
              </div>
            ) : (
              <Input
                aria-label="Percentage"
                placeholder="%"
                value={row.percentage}
                onChange={(e) =>
                  updateRow(index, { percentage: e.target.value })
                }
              />
            )}
            {row.calculationType === "PERCENTAGE_OF_COMPONENT" ? (
              <NativeSelect
                aria-label="Of component"
                value={row.baseId}
                onChange={(e) => updateRow(index, { baseId: e.target.value })}
              >
                <option value="">Of…</option>
                {earnings
                  .filter((c) => c.id !== row.componentId)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </NativeSelect>
            ) : (
              <div />
            )}
            <Input
              aria-label="Monthly cap (₹)"
              placeholder="Cap ₹ (optional)"
              value={row.cap}
              disabled={row.calculationType === "BALANCING"}
              onChange={(e) => updateRow(index, { cap: e.target.value })}
            />
            <div className="flex items-center gap-2">
              <NativeSelect
                aria-label="Applies"
                value={row.appliesWhen}
                onChange={(e) =>
                  updateRow(index, {
                    appliesWhen: e.target.value as AppliesWhen,
                  })
                }
              >
                {APPLIES_WHEN.map((a) => (
                  <option key={a} value={a}>
                    {APPLIES_WHEN_LABELS[a]}
                  </option>
                ))}
              </NativeSelect>
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Remove line"
                onClick={() => onChange(rows.filter((_, i) => i !== index))}
              >
                <Trash2 />
              </Button>
            </div>
            {amounts ? (
              <div
                className="text-sm tabular-nums text-foreground-secondary md:col-span-6"
                data-testid={`line-amount-${row.componentId}`}
              >
                {amount !== undefined ? (
                  <>
                    <span className="font-medium text-foreground">
                      {formatInr(amount)}
                    </span>{" "}
                    a month · {formatInr(amount * 12)} a year
                  </>
                ) : (
                  <span className="text-foreground-muted">—</span>
                )}
              </div>
            ) : null}
          </div>
        );
      })}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => onChange([...rows, { ...EMPTY_LINE_ROW }])}
      >
        <Plus /> Add component
      </Button>
    </div>
  );
}
