"use client";

import { Plus, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { describeApiError } from "@/lib/api/errors";
import {
  STATUTORY_SCHEME_LABELS,
  STATUTORY_SCHEMES,
  rupeesToMinor,
  type LwfSlab,
  type PtSlab,
  type StatutoryRate,
  type StatutoryScheme,
  type TdsSlab,
} from "@/lib/payroll/types";

const PF_FIELDS: [string, string, "percent" | "money" | "number"][] = [
  ["employee_percent", "Employee contribution (%)", "percent"],
  ["employer_percent", "Employer contribution (%)", "percent"],
  ["eps_percent", "Of which pension, EPS (%)", "percent"],
  ["wage_ceiling_minor", "Wage ceiling (₹)", "money"],
  ["edli_percent", "EDLI (%)", "percent"],
  ["admin_percent", "Admin charges (%)", "percent"],
  ["eps_age_limit", "No pension from age", "number"],
];

const ESI_FIELDS: [string, string, "percent" | "money" | "number"][] = [
  ["employee_percent", "Employee contribution (%)", "percent"],
  ["employer_percent", "Employer contribution (%)", "percent"],
  ["wage_ceiling_minor", "Wage ceiling (₹)", "money"],
  ["employee_exempt_daily_wage_minor", "No employee share up to a daily wage of (₹)", "money"],
];

const TDS_FIELDS: [string, string, "percent" | "money" | "number"][] = [
  ["standard_deduction_minor", "Standard deduction (₹/year)", "money"],
  ["rebate_taxable_income_limit_minor", "Full rebate at or below taxable income (₹/year)", "money"],
  ["cess_percent", "Health & education cess (%)", "percent"],
  ["surcharge_warning_income_minor", "Warn (don't compute) surcharge above (₹/year)", "money"],
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

interface SlabRow {
  from: string;
  to: string;
  amount: string;
  employer: string;
  gender: string;
  overrideMonth: string;
  overrideAmount: string;
}

const toRupees = (minor: number | null | undefined) =>
  minor === null || minor === undefined ? "" : String(minor / 100);

function emptySlab(): SlabRow {
  return { from: "0", to: "", amount: "0", employer: "0", gender: "", overrideMonth: "", overrideAmount: "" };
}

function slabRows(scheme: StatutoryScheme, parameters: Record<string, unknown>): SlabRow[] {
  if (scheme === "TDS") {
    const slabs = (parameters.slabs as TdsSlab[] | undefined) ?? [];
    return slabs.map((slab) => ({
      from: toRupees(slab.min_minor),
      to: toRupees(slab.max_minor),
      amount: slab.percent,
      employer: "0",
      gender: "",
      overrideMonth: "",
      overrideAmount: "",
    }));
  }
  const slabs = (parameters.slabs as (PtSlab & LwfSlab)[] | undefined) ?? [];
  return slabs.map((slab) => {
    const [month, amount] = Object.entries(slab.month_amounts ?? {})[0] ?? ["", undefined];
    return {
      from: toRupees(slab.min_minor),
      to: toRupees(slab.max_minor),
      amount: toRupees(scheme === "PT" ? slab.amount_minor : slab.employee_minor),
      employer: toRupees(slab.employer_minor),
      gender: slab.gender ?? "",
      overrideMonth: month,
      overrideAmount: toRupees(amount),
    };
  });
}

/** Creates a rate (from a date, closing the current one) or corrects one in place. Any change
 * leaves the rate unverified until compliance verifies it again. */
export function StatutoryRateDialog({
  open,
  rate,
  onOpenChange,
  onSaved,
}: {
  open: boolean;
  /** Edit this rate; `null` creates a new one. */
  rate: StatutoryRate | null;
  onOpenChange: (open: boolean) => void;
  onSaved: () => void;
}) {
  const [scheme, setScheme] = useState<StatutoryScheme>("PT");
  const [state, setState] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [fields, setFields] = useState<Record<string, string>>({});
  const [slabs, setSlabs] = useState<SlabRow[]>([]);
  const [months, setMonths] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    const source = rate;
    const nextScheme = source?.scheme ?? "PT";
    const p = source?.parameters ?? {};
    setScheme(nextScheme);
    setState(source?.state_code ?? "");
    setEffectiveFrom("");
    setNotes(source?.notes ?? "");
    const values: Record<string, string> = {};
    for (const [key, , kind] of [...PF_FIELDS, ...ESI_FIELDS, ...TDS_FIELDS]) {
      const value = p[key];
      if (value === undefined || value === null) continue;
      values[key] = kind === "money" ? toRupees(Number(value)) : String(value);
    }
    setFields(values);
    setSlabs(source ? slabRows(nextScheme, p) : [emptySlab()]);
    setMonths(((p.months as number[] | undefined) ?? []).join(", "));
  }, [open, rate]);

  function buildScalarFields(
    scalars: [string, string, "percent" | "money" | "number"][],
  ): Record<string, unknown> | string {
    const result: Record<string, unknown> = {};
    for (const [key, label, kind] of scalars) {
      const raw = (fields[key] ?? "").trim();
      if (!raw) return `${label} is required`;
      if (kind === "money") {
        const minor = rupeesToMinor(raw);
        if (minor === null) return `${label} must be an amount`;
        result[key] = minor;
      } else if (kind === "number") {
        if (!/^\d+$/.test(raw)) return `${label} must be a whole number`;
        result[key] = Number(raw);
      } else {
        if (!/^\d+(\.\d{1,4})?$/.test(raw)) return `${label} must be a percentage`;
        result[key] = raw;
      }
    }
    return result;
  }

  function buildParameters(): Record<string, unknown> | string {
    if (scheme === "PF" || scheme === "ESI") {
      return buildScalarFields(scheme === "PF" ? PF_FIELDS : ESI_FIELDS);
    }
    if (scheme === "TDS") {
      const result = buildScalarFields(TDS_FIELDS);
      if (typeof result === "string") return result;
      const built: TdsSlab[] = [];
      for (let index = 0; index < slabs.length; index += 1) {
        const row = slabs[index];
        const min = rupeesToMinor(row.from);
        const max = row.to.trim() ? rupeesToMinor(row.to) : null;
        if (min === null || (row.to.trim() && max === null)) {
          return `Slab ${index + 1}: from/to are amounts in rupees`;
        }
        if (!/^\d+(\.\d{1,4})?$/.test(row.amount.trim())) {
          return `Slab ${index + 1}: percent must be a number`;
        }
        built.push({ min_minor: min, max_minor: max, percent: row.amount.trim() });
      }
      if (built.length === 0) return "Add at least one slab";
      return { ...result, regime: "NEW", slabs: built };
    }
    const built = [];
    for (let index = 0; index < slabs.length; index += 1) {
      const row = slabs[index];
      const min = rupeesToMinor(row.from);
      const max = row.to.trim() ? rupeesToMinor(row.to) : null;
      const amount = rupeesToMinor(row.amount);
      if (min === null || amount === null || (row.to.trim() && max === null)) {
        return `Slab ${index + 1}: enter amounts in rupees`;
      }
      if (scheme === "PT") {
        const slab: PtSlab = { min_minor: min, max_minor: max, amount_minor: amount };
        if (row.gender) slab.gender = row.gender as "MALE" | "FEMALE";
        if (row.overrideMonth && row.overrideAmount.trim()) {
          const override = rupeesToMinor(row.overrideAmount);
          if (override === null) return `Slab ${index + 1}: month amount must be in rupees`;
          slab.month_amounts = { [row.overrideMonth]: override };
        }
        built.push(slab);
      } else {
        const employer = rupeesToMinor(row.employer);
        if (employer === null) return `Slab ${index + 1}: enter amounts in rupees`;
        built.push({ min_minor: min, max_minor: max, employee_minor: amount, employer_minor: employer });
      }
    }
    if (scheme === "PT") return { slabs: built };
    const monthList = months
      .split(",")
      .map((m) => m.trim())
      .filter(Boolean)
      .map(Number);
    if (monthList.length === 0 || monthList.some((m) => !Number.isInteger(m) || m < 1 || m > 12)) {
      return "Months are month numbers 1–12, e.g. 6, 12";
    }
    if (built.length === 0) return "Add at least one slab";
    return { months: monthList, slabs: built };
  }

  async function handleSave() {
    const parameters = buildParameters();
    if (typeof parameters === "string") {
      setError(parameters);
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (rate) {
        await apiClient.patch<StatutoryRate>(
          `/payroll/statutory-rates/${rate.id}`,
          { parameters, notes: notes.trim() || null },
          { ifMatch: String(rate.version) },
        );
      } else {
        await apiClient.post<StatutoryRate>("/payroll/statutory-rates", {
          scheme,
          state_code: scheme === "PT" || scheme === "LWF" ? state.trim().toUpperCase() : null,
          effective_from: effectiveFrom,
          parameters,
          notes: notes.trim() || null,
        });
      }
      onOpenChange(false);
      onSaved();
    } catch (err) {
      setError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  const perState = scheme === "PT" || scheme === "LWF";
  const showSlabs = perState || scheme === "TDS";
  const scalarFields =
    scheme === "PF" ? PF_FIELDS : scheme === "ESI" ? ESI_FIELDS : scheme === "TDS" ? TDS_FIELDS : [];

  return (
    <Dialog open={open} onOpenChange={(next) => !saving && onOpenChange(next)}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>{rate ? "Correct statutory rate" : "New statutory rate"}</DialogTitle>
          <DialogDescription>
            {rate
              ? "Corrects this rate in place. Pay runs keep the figures they already locked; the rate must be verified again."
              : "Applies from the date you choose; the current rate for the same scheme and state ends the day before. It starts unverified."}
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[65vh] space-y-4 overflow-y-auto pr-1">
          {!rate ? (
            <div className="grid gap-4 sm:grid-cols-3">
              <FormField id="rate-scheme" label="Scheme" required>
                <NativeSelect
                  value={scheme}
                  onChange={(e) => {
                    setScheme(e.target.value as StatutoryScheme);
                    setSlabs([emptySlab()]);
                  }}
                >
                  {STATUTORY_SCHEMES.map((s) => (
                    <option key={s} value={s}>
                      {STATUTORY_SCHEME_LABELS[s]}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
              {perState ? (
                <FormField id="rate-state" label="State code" required description="e.g. MH, KA">
                  <Input value={state} maxLength={10} onChange={(e) => setState(e.target.value)} />
                </FormField>
              ) : null}
              <FormField id="rate-from" label="Effective from" required>
                <Input type="date" value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
              </FormField>
            </div>
          ) : null}

          {scalarFields.length > 0 ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {scalarFields.map(([key, label]) => (
                <FormField key={key} id={`rate-${key}`} label={label} required>
                  <Input
                    inputMode="decimal"
                    value={fields[key] ?? ""}
                    onChange={(e) => setFields({ ...fields, [key]: e.target.value })}
                  />
                </FormField>
              ))}
            </div>
          ) : null}

          {scheme === "LWF" ? (
            <FormField id="rate-months" label="Deducted in months" required description="Month numbers, e.g. 6, 12">
              <Input value={months} onChange={(e) => setMonths(e.target.value)} />
            </FormField>
          ) : null}

          {showSlabs ? (
            <div className="space-y-2">
              <div className="text-sm font-medium text-foreground">
                {scheme === "TDS" ? "Slabs on annual taxable income" : "Slabs on the month's gross"}{" "}
                <span className="font-normal text-foreground-muted">
                  (leave &quot;to&quot; empty for no upper limit
                  {scheme === "PT" ? "; no slabs means the state levies no PT" : ""})
                </span>
              </div>
              {slabs.map((row, index) => {
                const update = (patch: Partial<SlabRow>) =>
                  setSlabs(slabs.map((s, i) => (i === index ? { ...s, ...patch } : s)));
                return (
                  <div key={index} className="flex flex-wrap items-end gap-2 rounded-md border border-border p-2">
                    <FormField id={`slab-${index}-from`} label={scheme === "TDS" ? "From ₹/yr" : "From ₹"} className="w-24">
                      <Input value={row.from} onChange={(e) => update({ from: e.target.value })} />
                    </FormField>
                    <FormField id={`slab-${index}-to`} label={scheme === "TDS" ? "To ₹/yr" : "To ₹"} className="w-24">
                      <Input value={row.to} onChange={(e) => update({ to: e.target.value })} />
                    </FormField>
                    <FormField
                      id={`slab-${index}-amount`}
                      label={scheme === "TDS" ? "Percent" : scheme === "PT" ? "Tax ₹" : "Employee ₹"}
                      className="w-24"
                    >
                      <Input value={row.amount} onChange={(e) => update({ amount: e.target.value })} />
                    </FormField>
                    {scheme === "TDS" ? null : scheme === "LWF" ? (
                      <FormField id={`slab-${index}-employer`} label="Employer ₹" className="w-24">
                        <Input value={row.employer} onChange={(e) => update({ employer: e.target.value })} />
                      </FormField>
                    ) : (
                      <>
                        <FormField id={`slab-${index}-gender`} label="Applies to" className="w-28">
                          <NativeSelect value={row.gender} onChange={(e) => update({ gender: e.target.value })}>
                            <option value="">Everyone</option>
                            <option value="MALE">Men</option>
                            <option value="FEMALE">Women</option>
                          </NativeSelect>
                        </FormField>
                        <FormField id={`slab-${index}-month`} label="Except in" className="w-24">
                          <NativeSelect
                            value={row.overrideMonth}
                            onChange={(e) => update({ overrideMonth: e.target.value })}
                          >
                            <option value="">—</option>
                            {MONTHS.map((m, i) => (
                              <option key={m} value={String(i + 1)}>
                                {m}
                              </option>
                            ))}
                          </NativeSelect>
                        </FormField>
                        <FormField id={`slab-${index}-override`} label="Then ₹" className="w-24">
                          <Input
                            value={row.overrideAmount}
                            disabled={!row.overrideMonth}
                            onChange={(e) => update({ overrideAmount: e.target.value })}
                          />
                        </FormField>
                      </>
                    )}
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      aria-label={`Remove slab ${index + 1}`}
                      onClick={() => setSlabs(slabs.filter((_, i) => i !== index))}
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                );
              })}
              <Button type="button" variant="outline" size="sm" onClick={() => setSlabs([...slabs, emptySlab()])}>
                <Plus className="mr-1 h-4 w-4" /> Add slab
              </Button>
            </div>
          ) : null}

          <FormField id="rate-notes" label="Notes" description="Source notification or circular">
            <Input value={notes} maxLength={2000} onChange={(e) => setNotes(e.target.value)} />
          </FormField>
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || (!rate && (!effectiveFrom || (perState && !state.trim())))}
          >
            {saving ? "Saving…" : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
