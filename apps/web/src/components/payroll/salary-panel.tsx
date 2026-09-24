"use client";

import { useCallback, useEffect, useState } from "react";

import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { SalaryBreakupTable } from "@/components/payroll/salary-breakup-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  currentVersion,
  formatInr,
  rupeesToMinor,
  type EmployeeSalary,
  type EmployeeSalaryBreakup,
  type SalaryStructure,
} from "@/lib/payroll/types";

/** Payroll Phase 5.1 — the employee's salary: the breakup of their CTC under their assigned
 * structure as of a date, the assignment history, and (with `PAYROLL.SETUP_MANAGE`) assigning a
 * structure or, for a daily-wage employee, a daily rate (D5). CTC itself is edited on the
 * Compensation tab. */
export function SalaryPanel({ employeeId }: { employeeId: string }) {
  const { toast } = useToast();
  const { user } = useAuth();
  const { can } = usePermissions();
  const canAssign = can("PAYROLL.SETUP_MANAGE");
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");

  const [asOf, setAsOf] = useState(today);
  const [breakup, setBreakup] = useState<EmployeeSalaryBreakup | null>(null);
  const [breakupMessage, setBreakupMessage] = useState<string | null>(null);
  const [history, setHistory] = useState<EmployeeSalary[]>([]);
  const [structures, setStructures] = useState<SalaryStructure[]>([]);
  const [loading, setLoading] = useState(true);

  const [assignOpen, setAssignOpen] = useState(false);
  const [basis, setBasis] = useState<"STRUCTURE" | "DAILY">("STRUCTURE");
  const [structureId, setStructureId] = useState("");
  const [dailyRate, setDailyRate] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState(today);
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [rows, breakupResult] = await Promise.all([
        apiClient.get<EmployeeSalary[]>(`/employees/${employeeId}/salary`),
        apiClient
          .get<EmployeeSalaryBreakup>(`/employees/${employeeId}/salary/breakup?as_of=${asOf}`)
          .then((data) => ({ data, message: null }))
          .catch((err: unknown) => ({ data: null, message: describeApiError(err) })),
      ]);
      setHistory(rows);
      setBreakup(breakupResult.data);
      setBreakupMessage(breakupResult.message);
      if (canAssign) {
        setStructures(await apiClient.get<SalaryStructure[]>("/payroll/salary-structures"));
      }
    } catch (err) {
      setBreakupMessage(
        err instanceof ApiError && err.status === 403
          ? "You do not have permission to view this employee's salary."
          : describeApiError(err),
      );
    } finally {
      setLoading(false);
    }
  }, [asOf, canAssign, employeeId]);

  useEffect(() => {
    void load();
  }, [load]);

  const structureName = (id: string | null) =>
    structures.find((s) => s.id === id)?.name ?? (id ? "Salary structure" : "—");
  const assignable = structures.filter((s) => s.is_active && currentVersion(s));

  async function handleAssign() {
    setSaving(true);
    setFormError(null);
    try {
      const dailyMinor = basis === "DAILY" ? rupeesToMinor(dailyRate) : null;
      if (basis === "DAILY" && !dailyMinor) {
        setFormError("Enter the daily rate in rupees.");
        return;
      }
      await apiClient.post<EmployeeSalary>(`/employees/${employeeId}/salary`, {
        ...(basis === "STRUCTURE"
          ? { salary_structure_id: structureId }
          : { daily_rate_minor: dailyMinor }),
        effective_from: effectiveFrom,
        reason: reason.trim(),
      });
      setAssignOpen(false);
      toast({ title: "Salary assigned", variant: "success" });
      await load();
    } catch (err) {
      setFormError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="flex flex-wrap items-end justify-between gap-3">
            <FormField id="salary-as-of" label="Salary as of" className="w-48">
              <Input type="date" value={asOf} onChange={(e) => setAsOf(e.target.value)} />
            </FormField>
            {canAssign ? (
              <Button
                type="button"
                onClick={() => {
                  setStructureId(assignable[0]?.id ?? "");
                  setReason("");
                  setFormError(null);
                  setAssignOpen(true);
                }}
              >
                Assign salary
              </Button>
            ) : null}
          </div>
          {loading ? <LoadingState label="Loading salary…" /> : null}
          {!loading && breakupMessage ? (
            <p className="text-sm text-foreground-muted">{breakupMessage}</p>
          ) : null}
          {!loading && breakup ? (
            <div className="space-y-3">
              <p className="text-sm text-foreground-secondary">
                {breakup.pay_basis === "DAILY_WAGE"
                  ? `Daily-wage employee — ${formatInr(breakup.daily_rate_minor ?? 0)} a day.`
                  : `${structureName(breakup.salary_structure_id)} · PF ${
                      breakup.pf_applicable ? "applies" : "does not apply"
                    }`}
              </p>
              {breakup.breakup ? <SalaryBreakupTable breakup={breakup.breakup} /> : null}
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          <h3 className="mb-3 text-sm font-medium text-foreground">Salary history</h3>
          {history.length === 0 ? (
            <p className="text-sm text-foreground-muted">No salary assigned yet.</p>
          ) : (
            <ul className="divide-y divide-border rounded-md border border-border text-sm">
              {[...history].reverse().map((row) => (
                <li key={row.id} className="flex flex-wrap justify-between gap-2 px-3 py-2">
                  <span className="text-foreground">
                    {row.daily_rate_minor !== null
                      ? `Daily rate ${formatInr(row.daily_rate_minor)}`
                      : structureName(row.salary_structure_id)}
                    {row.reason ? (
                      <span className="text-foreground-muted"> · {row.reason}</span>
                    ) : null}
                  </span>
                  <span className="text-foreground-secondary">
                    {row.effective_from} → {row.effective_to ?? "now"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>

      <Dialog open={assignOpen} onOpenChange={(next) => !saving && setAssignOpen(next)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Assign salary</DialogTitle>
            <DialogDescription>
              Replaces the current assignment from the chosen date. The CTC itself comes from the
              Compensation tab.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <FormField id="salary-basis" label="Paid by">
              <NativeSelect
                value={basis}
                onChange={(e) => setBasis(e.target.value as "STRUCTURE" | "DAILY")}
              >
                <option value="STRUCTURE">Salary structure (monthly-paid)</option>
                <option value="DAILY">Daily rate (daily-wage)</option>
              </NativeSelect>
            </FormField>
            {basis === "STRUCTURE" ? (
              <FormField id="salary-structure" label="Structure">
                <NativeSelect value={structureId} onChange={(e) => setStructureId(e.target.value)}>
                  {assignable.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.name}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
            ) : (
              <FormField id="salary-daily-rate" label="Daily rate (₹)">
                <Input value={dailyRate} onChange={(e) => setDailyRate(e.target.value)} />
              </FormField>
            )}
            <FormField id="salary-effective-from" label="Effective from">
              <Input
                type="date"
                value={effectiveFrom}
                onChange={(e) => setEffectiveFrom(e.target.value)}
              />
            </FormField>
            <FormField id="salary-reason" label="Reason" required>
              <Input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
            </FormField>
            {formError ? (
              <p role="alert" className="text-sm text-danger">
                {formError}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAssignOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleAssign()}
              disabled={
                saving || !reason.trim() || !effectiveFrom || (basis === "STRUCTURE" && !structureId)
              }
            >
              {saving ? "Saving…" : "Assign"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
