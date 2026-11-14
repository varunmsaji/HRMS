"use client";

import { ChevronDown, Plus, Trash2 } from "lucide-react";
import { Fragment, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { cn } from "@/lib/utils";
import {
  APPLIES_WHEN,
  APPLIES_WHEN_LABELS,
  CALCULATION_TYPE_LABELS,
  CALCULATION_TYPES,
  formatInr,
  rupeesToMinor,
  type AppliesWhen,
  type CalculationType,
  type SalaryBreakup,
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

/** Shorter labels for the compact calculation picker. */
const SHORT_CALCULATION_LABELS: Record<CalculationType, string> = {
  FIXED: "Fixed ₹",
  PERCENTAGE_OF_CTC: "% of CTC",
  PERCENTAGE_OF_GROSS: "% of gross",
  PERCENTAGE_OF_COMPONENT: "% of component",
  BALANCING: "Remainder",
};

// Component · Calculation · Value · Monthly · Annual · actions
const COLUMNS =
  "md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1.3fr)_6.5rem_7rem_4.5rem]";
const COLUMNS_NO_AMOUNTS =
  "md:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)_minmax(0,1.3fr)_4.5rem]";

/** Editable structure lines as one compact table: what each component is, how it is calculated
 * and its value on one row; its cap and "applies when" behind the row's settings toggle. With
 * `amounts` (monthly paise by component id) each row shows what it pays, and with `breakup` the
 * table ends in gross, employer contributions and CTC totals. With `highlightMissing`, a row
 * whose component is not chosen yet is marked invalid. */
export function StructureLinesEditor({
  rows,
  onChange,
  components,
  amounts,
  breakup,
  highlightMissing = false,
}: {
  rows: LineRow[];
  onChange: (rows: LineRow[]) => void;
  components: SalaryComponent[];
  amounts?: Record<string, number>;
  breakup?: SalaryBreakup | null;
  highlightMissing?: boolean;
}) {
  const [open, setOpen] = useState<Set<number>>(new Set());
  const usable = components.filter(
    (c) => c.is_active && c.component_type !== "DEDUCTION",
  );
  const earnings = usable.filter((c) => c.component_type === "EARNING");
  const byId = new Map(components.map((c) => [c.id, c]));
  const showAmounts = amounts !== undefined;
  const columns = showAmounts ? COLUMNS : COLUMNS_NO_AMOUNTS;

  const indexed = rows.map((row, index) => ({ row, index }));
  const employerRows = indexed.filter(
    ({ row }) =>
      byId.get(row.componentId)?.component_type === "EMPLOYER_CONTRIBUTION",
  );
  const earningRows = indexed.filter((item) => !employerRows.includes(item));

  function updateRow(index: number, patch: Partial<LineRow>) {
    onChange(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)));
  }

  function removeRow(index: number) {
    onChange(rows.filter((_, i) => i !== index));
    setOpen(new Set());
  }

  function toggle(index: number) {
    const next = new Set(open);
    if (next.has(index)) next.delete(index);
    else next.add(index);
    setOpen(next);
  }

  const money = (minor: number | undefined) =>
    minor === undefined ? (
      <span className="text-foreground-muted">—</span>
    ) : (
      formatInr(minor)
    );

  function renderRow({ row, index }: { row: LineRow; index: number }) {
    const component = byId.get(row.componentId);
    const isEmployer = component?.component_type === "EMPLOYER_CONTRIBUTION";
    const calculations = CALCULATION_TYPES.filter(
      (t) => !isEmployer || (t !== "BALANCING" && t !== "PERCENTAGE_OF_GROSS"),
    );
    const amount = amounts?.[row.componentId];
    const expanded = open.has(index);
    const extras = [
      row.cap ? `cap ${formatInr(rupeesToMinor(row.cap) ?? 0)}` : null,
      row.appliesWhen !== "ALWAYS"
        ? APPLIES_WHEN_LABELS[row.appliesWhen].replace(/^./, (ch) =>
            ch.toLowerCase(),
          )
        : null,
    ].filter(Boolean);

    return (
      <Fragment key={index}>
        <div
          className={cn(
            "grid grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-x-3 gap-y-2 px-3 py-2 text-sm",
            columns,
          )}
        >
          <div className="order-1 min-w-0 md:order-none">
            {component ? (
              <div className="truncate font-medium text-foreground">
                {component.name}
              </div>
            ) : (
              <NativeSelect
                aria-label="Component"
                aria-invalid={highlightMissing && !row.componentId}
                className="h-8"
                value={row.componentId}
                onChange={(e) =>
                  updateRow(index, { componentId: e.target.value })
                }
              >
                <option value="">Choose component…</option>
                {usable
                  .filter((c) => !rows.some((r) => r.componentId === c.id))
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </NativeSelect>
            )}
            {extras.length > 0 && !expanded ? (
              <div className="truncate text-xs text-foreground-muted">
                {extras.join(" · ")}
              </div>
            ) : null}
          </div>
          {/* Phone: calculation and value share the row under the name; md+: own columns. */}
          <div className="order-4 col-span-full grid grid-cols-[minmax(0,0.8fr)_minmax(0,1.2fr)] gap-2 md:order-none md:contents">
            <NativeSelect
              aria-label="Calculation"
              className="h-8"
              value={row.calculationType}
              onChange={(e) =>
                updateRow(index, {
                  calculationType: e.target.value as CalculationType,
                })
              }
            >
              {calculations.map((t) => (
                <option key={t} value={t} title={CALCULATION_TYPE_LABELS[t]}>
                  {SHORT_CALCULATION_LABELS[t]}
                </option>
              ))}
            </NativeSelect>
            <div className="flex min-w-0 items-center gap-1.5">
              {row.calculationType === "FIXED" ? (
                <Input
                  aria-label="Monthly amount (₹)"
                  className="h-8"
                  inputMode="decimal"
                  placeholder="₹ a month"
                  value={row.amount}
                  onChange={(e) => updateRow(index, { amount: e.target.value })}
                />
              ) : row.calculationType === "BALANCING" ? (
                <span className="text-xs text-foreground-muted">
                  Rest of gross
                </span>
              ) : (
                <>
                  <div className="relative w-20 shrink-0">
                    <Input
                      aria-label="Percentage"
                      className="h-8 pr-6 text-right"
                      inputMode="decimal"
                      value={row.percentage}
                      onChange={(e) =>
                        updateRow(index, { percentage: e.target.value })
                      }
                    />
                    <span className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-xs text-foreground-muted">
                      %
                    </span>
                  </div>
                  {row.calculationType === "PERCENTAGE_OF_COMPONENT" ? (
                    <NativeSelect
                      aria-label="Of component"
                      className="h-8 min-w-0"
                      value={row.baseId}
                      onChange={(e) =>
                        updateRow(index, { baseId: e.target.value })
                      }
                    >
                      <option value="">of…</option>
                      {earnings
                        .filter((c) => c.id !== row.componentId)
                        .map((c) => (
                          <option key={c.id} value={c.id}>
                            of {c.name}
                          </option>
                        ))}
                    </NativeSelect>
                  ) : null}
                </>
              )}
            </div>
          </div>
          {showAmounts ? (
            <>
              <div
                className="order-2 text-right font-medium tabular-nums text-foreground md:order-none"
                data-testid={`line-amount-${row.componentId}`}
              >
                {money(amount)}
                <span className="text-xs font-normal text-foreground-muted md:hidden">
                  {" "}
                  /mo
                </span>
              </div>
              <div className="hidden text-right tabular-nums text-foreground-secondary md:block">
                {money(amount === undefined ? undefined : amount * 12)}
              </div>
            </>
          ) : null}
          <div
            className={cn(
              "order-3 flex justify-end gap-0.5 md:order-none",
              !showAmounts && "col-span-2 md:col-span-1",
            )}
          >
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              aria-label="Line settings"
              aria-expanded={expanded}
              onClick={() => toggle(index)}
            >
              <ChevronDown
                className={cn("transition-transform", expanded && "rotate-180")}
              />
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-foreground-muted hover:text-danger"
              aria-label="Remove line"
              onClick={() => removeRow(index)}
            >
              <Trash2 />
            </Button>
          </div>
        </div>
        {expanded ? (
          <div className="flex flex-wrap items-center gap-3 bg-surface-secondary/40 px-3 py-2 text-xs text-foreground-secondary">
            <label className="flex items-center gap-2">
              Monthly cap
              <Input
                aria-label="Monthly cap (₹)"
                className="h-8 w-28"
                inputMode="decimal"
                placeholder="No cap"
                value={row.cap}
                disabled={row.calculationType === "BALANCING"}
                onChange={(e) => updateRow(index, { cap: e.target.value })}
              />
            </label>
            <label className="flex items-center gap-2">
              Applies
              <NativeSelect
                aria-label="Applies"
                className="h-8 w-44"
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
            </label>
          </div>
        ) : null}
      </Fragment>
    );
  }

  const total = (label: string, monthly: number, strong = false) => (
    <div
      className={cn(
        "grid grid-cols-2 items-center gap-x-3 px-3 py-2 text-sm",
        columns,
        strong
          ? "bg-surface-secondary font-semibold text-foreground"
          : "text-foreground-secondary",
      )}
    >
      <div className="md:col-span-3">{label}</div>
      <div className="text-right tabular-nums">
        {formatInr(monthly)}
        <span className="text-xs font-normal text-foreground-muted md:hidden">
          {" "}
          /mo
        </span>
      </div>
      <div className="hidden text-right tabular-nums md:block">
        {formatInr(monthly * 12)}
      </div>
      <div className="hidden md:block" />
    </div>
  );

  const section = (label: string) => (
    <div className="bg-surface-secondary/60 px-3 py-1.5 text-[11px] font-medium uppercase tracking-wide text-foreground-muted">
      {label}
    </div>
  );

  return (
    <div className="space-y-2">
      <div className="overflow-hidden rounded-md border border-border">
        <div
          className={cn(
            "hidden gap-x-3 border-b border-border bg-surface-secondary px-3 py-2 text-xs font-medium uppercase tracking-wide text-foreground-muted md:grid",
            columns,
          )}
        >
          <div>Component</div>
          <div>Calculated as</div>
          <div>Value</div>
          {showAmounts ? (
            <>
              <div className="text-right">Monthly</div>
              <div className="text-right">Annual</div>
            </>
          ) : null}
          <div />
        </div>
        <div className="divide-y divide-border">
          {earningRows.length > 0 && employerRows.length > 0
            ? section("Earnings")
            : null}
          {earningRows.map(renderRow)}
          {breakup ? total("Gross", breakup.gross_monthly_minor) : null}
          {employerRows.length > 0 ? section("Employer contributions") : null}
          {employerRows.map(renderRow)}
          {breakup
            ? total("Cost to company", breakup.monthly_ctc_minor, true)
            : null}
          {rows.length === 0 ? (
            <div className="px-3 py-6 text-center text-sm text-foreground-muted">
              No components yet.
            </div>
          ) : null}
        </div>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        className="text-primary"
        onClick={() => onChange([...rows, { ...EMPTY_LINE_ROW }])}
      >
        <Plus /> Add component
      </Button>
    </div>
  );
}
