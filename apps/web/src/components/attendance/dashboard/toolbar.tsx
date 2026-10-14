"use client";

import { Filter, X } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import {
  BUCKET_LABELS,
  DAY_BUCKETS,
  FLAG_LABELS,
  RANGE_PRESETS,
  RANGE_PRESET_LABELS,
  employeeName,
  formatShortDate,
  hasActiveFilters,
  type DashboardFilters,
  type DateRange,
  type DayBucket,
  type EmployeeLite,
  type RangePreset,
} from "@/lib/attendance/dashboard";
import { cn } from "@/lib/utils";

export interface FilterLookups {
  employees: EmployeeLite[];
  shifts: { id: string; name: string }[];
  entities: { id: string; name: string }[];
  employeeStatuses: string[];
}

interface ToolbarProps {
  filters: DashboardFilters;
  range: DateRange;
  today: string;
  lookups: FilterLookups;
  /** Org-level controls (company, shift) are meaningless to a plain team view. */
  showEntity: boolean;
  onChange: (patch: Partial<DashboardFilters>) => void;
  onReset: () => void;
}

interface Chip {
  key: string;
  label: string;
  clear: Partial<DashboardFilters>;
}

function activeChips(f: DashboardFilters, range: DateRange, lookups: FilterLookups): Chip[] {
  const chips: Chip[] = [];
  if (f.preset !== "today") {
    chips.push({
      key: "range",
      label: `${RANGE_PRESET_LABELS[f.preset]}: ${formatShortDate(range.from)} – ${formatShortDate(range.to)}`,
      clear: { preset: "today", from: "", to: "" },
    });
  }
  if (f.employeeId) {
    const employee = lookups.employees.find((e) => e.id === f.employeeId);
    chips.push({ key: "employee", label: `Employee: ${employeeName(employee, f.employeeId)}`, clear: { employeeId: "" } });
  }
  if (f.bucket) chips.push({ key: "bucket", label: `Status: ${BUCKET_LABELS[f.bucket]}`, clear: { bucket: "", scope: "" } });
  if (f.flag) chips.push({ key: "flag", label: FLAG_LABELS[f.flag], clear: { flag: "", scope: "" } });
  if (f.shiftId) {
    chips.push({ key: "shift", label: `Shift: ${lookups.shifts.find((s) => s.id === f.shiftId)?.name ?? "selected"}`, clear: { shiftId: "" } });
  }
  if (f.employeeStatus) chips.push({ key: "estatus", label: `Employment: ${f.employeeStatus}`, clear: { employeeStatus: "" } });
  if (f.legalEntityId) {
    chips.push({
      key: "entity",
      label: `Company: ${lookups.entities.find((e) => e.id === f.legalEntityId)?.name ?? "selected"}`,
      clear: { legalEntityId: "" },
    });
  }
  return chips;
}

function Field({ id, label, children }: { id: string; label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0 space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-foreground-secondary">
        {label}
      </label>
      {children}
    </div>
  );
}

function FilterFields({
  filters,
  lookups,
  showEntity,
  onChange,
  idPrefix,
}: Pick<ToolbarProps, "filters" | "lookups" | "showEntity" | "onChange"> & { idPrefix: string }) {
  return (
    <>
      {lookups.employees.length > 0 ? (
        <Field id={`${idPrefix}-employee`} label="Employee">
          <NativeSelect id={`${idPrefix}-employee`} value={filters.employeeId} onChange={(e) => onChange({ employeeId: e.target.value })}>
            <option value="">All employees</option>
            {lookups.employees.map((employee) => (
              <option key={employee.id} value={employee.id}>
                {employeeName(employee, employee.id)}
                {employee.employee_code ? ` (${employee.employee_code})` : ""}
              </option>
            ))}
          </NativeSelect>
        </Field>
      ) : null}
      <Field id={`${idPrefix}-status`} label="Attendance status">
        <NativeSelect
          id={`${idPrefix}-status`}
          value={filters.bucket}
          // Focus-date scoped, like every KPI-card/status-chart drill — always clears any
          // range-scoped Needs Attention drill rather than inheriting its (different) population.
          onChange={(e) => onChange({ bucket: e.target.value as DayBucket | "", scope: "" })}
        >
          <option value="">All statuses</option>
          {DAY_BUCKETS.map((bucket) => (
            <option key={bucket} value={bucket}>
              {BUCKET_LABELS[bucket]}
            </option>
          ))}
        </NativeSelect>
      </Field>
      {lookups.shifts.length > 0 ? (
        <Field id={`${idPrefix}-shift`} label="Shift">
          <NativeSelect id={`${idPrefix}-shift`} value={filters.shiftId} onChange={(e) => onChange({ shiftId: e.target.value })}>
            <option value="">All shifts</option>
            {lookups.shifts.map((shift) => (
              <option key={shift.id} value={shift.id}>
                {shift.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
      ) : null}
      {lookups.employeeStatuses.length > 1 ? (
        <Field id={`${idPrefix}-estatus`} label="Employment status">
          <NativeSelect id={`${idPrefix}-estatus`} value={filters.employeeStatus} onChange={(e) => onChange({ employeeStatus: e.target.value })}>
            <option value="">All</option>
            {lookups.employeeStatuses.map((status) => (
              <option key={status} value={status}>
                {status.charAt(0) + status.slice(1).toLowerCase()}
              </option>
            ))}
          </NativeSelect>
        </Field>
      ) : null}
      {showEntity && lookups.entities.length > 0 ? (
        <Field id={`${idPrefix}-entity`} label="Company (periods)">
          <NativeSelect id={`${idPrefix}-entity`} value={filters.legalEntityId} onChange={(e) => onChange({ legalEntityId: e.target.value })}>
            <option value="">All companies</option>
            {lookups.entities.map((entity) => (
              <option key={entity.id} value={entity.id}>
                {entity.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
      ) : null}
    </>
  );
}

/** Command bar: range presets + custom dates always visible; the remaining filters sit inline on
 * desktop and in a drawer on small screens. Filter state lives in the URL (see the page), so it
 * survives a reload and a link can be shared. */
export function AttendanceToolbar({ filters, range, today, lookups, showEntity, onChange, onReset }: ToolbarProps) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const chips = activeChips(filters, range, lookups);
  const active = hasActiveFilters(filters);

  function selectPreset(preset: RangePreset) {
    if (preset === "custom") {
      onChange({ preset, from: filters.from || range.from, to: filters.to || range.to });
    } else {
      onChange({ preset, from: "", to: "" });
    }
  }

  return (
    <section aria-label="Filters" className="space-y-3 rounded-lg border border-border bg-surface p-3 sm:p-4">
      <div className="flex flex-wrap items-end gap-3">
        <div role="group" aria-label="Date range" className="inline-flex rounded-md border border-border p-0.5">
          {RANGE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              aria-pressed={filters.preset === preset}
              onClick={() => selectPreset(preset)}
              className={cn(
                "rounded px-3 py-1.5 text-sm font-medium transition-colors",
                filters.preset === preset
                  ? "bg-primary text-on-primary"
                  : "text-foreground-secondary hover:bg-muted",
              )}
            >
              {RANGE_PRESET_LABELS[preset]}
            </button>
          ))}
        </div>
        {filters.preset === "custom" ? (
          <div className="flex items-end gap-2">
            <Field id="att-filter-from" label="From">
              <Input
                id="att-filter-from"
                type="date"
                max={today}
                value={range.from}
                onChange={(e) => onChange({ from: e.target.value, to: range.to })}
              />
            </Field>
            <Field id="att-filter-to" label="To">
              <Input
                id="att-filter-to"
                type="date"
                max={today}
                value={range.to}
                onChange={(e) => onChange({ from: range.from, to: e.target.value })}
              />
            </Field>
          </div>
        ) : (
          <p className="pb-2 text-sm text-foreground-secondary">
            {range.from === range.to ? formatShortDate(range.to) : `${formatShortDate(range.from)} – ${formatShortDate(range.to)}`}
          </p>
        )}
        <div className="ml-auto flex items-center gap-2 pb-0.5">
          <Button type="button" variant="outline" size="sm" className="md:hidden" onClick={() => setDrawerOpen(true)}>
            <Filter className="mr-1.5 h-4 w-4" aria-hidden="true" />
            Filters{chips.length > 0 ? ` (${chips.length})` : ""}
          </Button>
          <Button type="button" variant="ghost" size="sm" onClick={onReset} disabled={!active}>
            Reset filters
          </Button>
        </div>
      </div>

      <div className="hidden grid-cols-2 gap-3 md:grid lg:grid-cols-5">
        <FilterFields filters={filters} lookups={lookups} showEntity={showEntity} onChange={onChange} idPrefix="att-filter" />
      </div>

      {chips.length > 0 ? (
        <ul className="flex flex-wrap gap-2" aria-label="Active filters">
          {chips.map((chip) => (
            <li key={chip.key}>
              <button
                type="button"
                onClick={() => onChange(chip.clear)}
                aria-label={`Remove filter ${chip.label}`}
                className="inline-flex items-center gap-1 rounded-full border border-border bg-muted px-2.5 py-1 text-xs text-foreground hover:border-border-strong"
              >
                {chip.label}
                <X className="h-3 w-3" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}

      <Sheet open={drawerOpen} onOpenChange={setDrawerOpen}>
        <SheetContent side="right" className="w-[20rem] max-w-full overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Filters</SheetTitle>
            <SheetDescription>Narrow every section of the dashboard.</SheetDescription>
          </SheetHeader>
          <div className="mt-4 grid gap-3">
            <FilterFields filters={filters} lookups={lookups} showEntity={showEntity} onChange={onChange} idPrefix="att-drawer" />
          </div>
          <div className="mt-6 flex gap-2">
            <Button type="button" variant="outline" onClick={onReset} disabled={!active}>
              Reset filters
            </Button>
            <Button type="button" onClick={() => setDrawerOpen(false)}>
              Done
            </Button>
          </div>
        </SheetContent>
      </Sheet>
    </section>
  );
}
