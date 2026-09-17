"use client";

import { Wallet } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { LeaveBalance, LeaveLedgerEntry } from "@/lib/leave-ledger/types";

interface EncashmentFormValues {
  days: string;
  effectiveDate: string;
  reason: string;
}

function emptyEncashmentFormValues(): EncashmentFormValues {
  return { days: "", effectiveDate: new Date().toISOString().slice(0, 10), reason: "" };
}

interface EmployeeOption {
  id: string;
  first_name: string;
  last_name: string | null;
  employee_code: string | null;
}

function employeeLabelFor(employee: EmployeeOption): string {
  const name = [employee.first_name, employee.last_name].filter(Boolean).join(" ");
  return employee.employee_code ? `${name} (${employee.employee_code})` : name;
}

type ViewMode = "MINE" | "TEAM";

/** `/v1/leave-balances`/`/v1/leave-ledger` (LEAVE_DECISION_LOG.md LD-02/LD-03) — both require a
 * specific `employee_id`, there's no "every employee's balance" list endpoint. "Mine" resolves to
 * the caller's own linked employee; "Team" needs an explicit picker. */
export default function LeaveBalancesPage() {
  const { user } = useAuth();
  const tz = user?.company_timezone ?? "Asia/Kolkata";
  const { toast } = useToast();
  const { can } = usePermissions();
  const canViewAll = can("LEAVE.BALANCE_VIEW_ALL");
  const canAdjust = can("LEAVE.BALANCE_ADJUST");

  const [view, setView] = useState<ViewMode>(canViewAll ? "TEAM" : "MINE");
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [selectedEmployeeId, setSelectedEmployeeId] = useState("");

  const [balances, setBalances] = useState<LeaveBalance[] | null>(null);
  const [ledger, setLedger] = useState<LeaveLedgerEntry[] | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const [encashingType, setEncashingType] = useState<LeaveBalance | null>(null);
  const [encashmentValues, setEncashmentValues] = useState<EncashmentFormValues>(
    emptyEncashmentFormValues(),
  );
  const [encashmentError, setEncashmentError] = useState<string | null>(null);
  const [encashmentSaving, setEncashmentSaving] = useState(false);

  const targetEmployeeId = view === "MINE" ? user?.employee_id ?? "" : selectedEmployeeId;

  const employeeById = useMemo(() => {
    const map = new Map<string, EmployeeOption>();
    for (const emp of employees) map.set(emp.id, emp);
    return map;
  }, [employees]);

  useEffect(() => {
    if (view !== "TEAM") return;
    void apiClient
      .get<EmployeeOption[]>("/employees")
      .then(setEmployees)
      .catch(() => setEmployees([]));
  }, [view]);

  const load = useCallback(async () => {
    if (!targetEmployeeId) {
      setBalances(null);
      setLedger(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [balanceData, ledgerData] = await Promise.all([
        apiClient.get<LeaveBalance[]>(`/leave-balances?employee_id=${targetEmployeeId}`),
        apiClient.get<LeaveLedgerEntry[]>(`/leave-ledger?employee_id=${targetEmployeeId}`),
      ]);
      setBalances(balanceData);
      setLedger(ledgerData);
    } catch (err) {
      setBalances(null);
      setLedger(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [targetEmployeeId]);

  useEffect(() => {
    void load();
  }, [load]);

  function openEncash(balance: LeaveBalance) {
    setEncashingType(balance);
    setEncashmentValues(emptyEncashmentFormValues());
    setEncashmentError(null);
  }

  async function handleEncash() {
    if (!encashingType || !targetEmployeeId) return;
    if (!encashmentValues.days.trim()) {
      setEncashmentError("Enter the number of days to encash.");
      return;
    }
    setEncashmentSaving(true);
    setEncashmentError(null);
    try {
      await apiClient.post("/leave-ledger/encashments", {
        employee_id: targetEmployeeId,
        leave_type_id: encashingType.leave_type_id,
        days: encashmentValues.days.trim(),
        effective_date: encashmentValues.effectiveDate,
        reason: encashmentValues.reason.trim() || "Encashment",
      });
      setEncashingType(null);
      toast({ title: "Encashment recorded", variant: "success" });
      await load();
    } catch (err) {
      setEncashmentError(describeApiError(err));
    } finally {
      setEncashmentSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave Balances"
        description="Current balance per leave type, and the append-only ledger behind it (accruals, applications, manual adjustments)."
      />

      <div className="flex gap-2">
        <Button
          type="button"
          variant={view === "MINE" ? "default" : "outline"}
          size="sm"
          onClick={() => setView("MINE")}
        >
          My balance
        </Button>
        {canViewAll ? (
          <Button
            type="button"
            variant={view === "TEAM" ? "default" : "outline"}
            size="sm"
            onClick={() => setView("TEAM")}
          >
            Team balances
          </Button>
        ) : null}
      </div>

      {view === "TEAM" ? (
        <Card>
          <CardContent className="pt-6">
            <FormField id="leave-balances-employee" label="Employee">
              <NativeSelect
                value={selectedEmployeeId}
                onChange={(e) => setSelectedEmployeeId(e.target.value)}
              >
                <option value="">Choose an employee…</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {employeeLabelFor(emp)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          </CardContent>
        </Card>
      ) : null}

      {!targetEmployeeId && view === "TEAM" ? (
        <Card>
          <CardContent className="pt-6">
            <EmptyState icon={Wallet} title="Choose an employee to view their leave balance." />
          </CardContent>
        </Card>
      ) : null}

      {!targetEmployeeId && view === "MINE" ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState message="Your user account has no linked employee record." />
          </CardContent>
        </Card>
      ) : null}

      {targetEmployeeId ? (
        <>
          <Card>
            <CardContent className="pt-6">
              {loading ? <LoadingState label="Loading balances…" /> : null}
              {error && !loading ? (
                <ErrorState
                  message={
                    error.status === 403
                      ? "You do not have permission to view this balance."
                      : error.message
                  }
                  onRetry={() => void load()}
                />
              ) : null}
              {!loading && !error && balances && balances.length === 0 ? (
                <EmptyState
                  icon={Wallet}
                  title="No balance-backed leave types configured yet."
                  description="LOP-style leave types (requires_balance=false) never appear here."
                />
              ) : null}
              {!loading && !error && balances && balances.length > 0 ? (
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Leave type</th>
                        <th className="px-3 py-2 text-right font-medium">Available balance</th>
                        <th className="px-3 py-2 text-right font-medium">Reserved / pending</th>
                        {canAdjust ? <th className="px-3 py-2 text-right font-medium">Encashment</th> : null}
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {balances.map((balance) => (
                        <tr key={balance.leave_type_id}>
                          <td className="px-3 py-2 font-medium text-foreground">
                            {balance.leave_type_name}{" "}
                            <span className="text-foreground-muted">({balance.leave_type_code})</span>
                          </td>
                          <td className="px-3 py-2 text-right text-foreground">{balance.balance}</td>
                          <td className="px-3 py-2 text-right text-foreground-secondary">
                            {balance.reserved_balance}
                          </td>
                          {canAdjust ? (
                            <td className="px-3 py-2 text-right">
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => openEncash(balance)}
                              >
                                Encash
                              </Button>
                            </td>
                          ) : null}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </CardContent>
          </Card>

          <Card>
            <CardContent className="pt-6">
              <h2 className="mb-4 text-sm font-medium text-foreground">
                Ledger{canAdjust ? " (append-only — a correction is always a new entry, never an edit)" : ""}
              </h2>
              {!loading && !error && ledger && ledger.length === 0 ? (
                <p className="text-sm text-foreground-muted">No ledger activity yet.</p>
              ) : null}
              {!loading && !error && ledger && ledger.length > 0 ? (
                <div className="overflow-x-auto rounded-md border border-border">
                  <table className="w-full text-sm">
                    <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                      <tr>
                        <th className="px-3 py-2 text-left font-medium">Date</th>
                        <th className="px-3 py-2 text-left font-medium">Type</th>
                        <th className="px-3 py-2 text-right font-medium">Amount</th>
                        <th className="px-3 py-2 text-left font-medium">Reason</th>
                        <th className="px-3 py-2 text-left font-medium">Recorded</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {ledger.map((entry) => (
                        <tr key={entry.id}>
                          <td className="px-3 py-2">{entry.effective_date}</td>
                          <td className="px-3 py-2">{entry.entry_type}</td>
                          <td className="px-3 py-2 text-right">{entry.amount}</td>
                          <td className="px-3 py-2 text-foreground-secondary">{entry.reason ?? "—"}</td>
                          <td className="px-3 py-2 text-xs text-foreground-muted">
                            {formatDateTime(entry.created_at, tz)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : null}
            </CardContent>
          </Card>
        </>
      ) : null}

      <Dialog
        open={encashingType !== null}
        onOpenChange={(open) => (!encashmentSaving && !open ? setEncashingType(null) : null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Encash {encashingType?.leave_type_name}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <p className="text-sm text-foreground-muted">
              Available balance: {encashingType?.balance}
            </p>
            <FormField id="encashment-days" label="Days to encash" required>
              <Input
                value={encashmentValues.days}
                onChange={(e) =>
                  setEncashmentValues((c) => ({ ...c, days: e.target.value }))
                }
                placeholder="5"
              />
            </FormField>
            <FormField id="encashment-effective-date" label="Effective date" required>
              <Input
                type="date"
                value={encashmentValues.effectiveDate}
                onChange={(e) =>
                  setEncashmentValues((c) => ({ ...c, effectiveDate: e.target.value }))
                }
              />
            </FormField>
            <FormField id="encashment-reason" label="Reason">
              <Input
                value={encashmentValues.reason}
                onChange={(e) => setEncashmentValues((c) => ({ ...c, reason: e.target.value }))}
                maxLength={2000}
              />
            </FormField>
            {encashmentError ? (
              <p role="alert" className="text-sm text-danger">
                {encashmentError}
              </p>
            ) : null}
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setEncashingType(null)}
              disabled={encashmentSaving}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleEncash()} disabled={encashmentSaving}>
              {encashmentSaving ? "Recording…" : "Record encashment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
