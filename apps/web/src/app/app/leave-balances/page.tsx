"use client";

import { Wallet } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { BusyRegion } from "@/components/common/busy-region";
import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
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
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
} from "@/components/ui/table";
import { EmployeeSelect } from "@/components/employee/employee-select";
import { TableSkeleton } from "@/components/ui/skeleton";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { CompanyDate } from "@/components/common/company-date";
import { formatDateTime } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import type { LeaveBalance, LeaveLedgerEntry } from "@/lib/leave-ledger/types";
import { cn } from "@/lib/utils";

interface EncashmentFormValues {
  days: string;
  effectiveDate: string;
  reason: string;
}

function emptyEncashmentFormValues(): EncashmentFormValues {
  return { days: "", effectiveDate: new Date().toISOString().slice(0, 10), reason: "" };
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
  const directory = useEmployeeDirectory({ enabled: view === "TEAM" });
  const beginRequest = useLatestRequest();
  const [selectedEmployeeId, setSelectedEmployeeId] = useState("");

  const [balances, setBalances] = useState<LeaveBalance[] | null>(null);
  const [ledger, setLedger] = useState<LeaveLedgerEntry[] | null>(null);
  const [ledgerPagination, setLedgerPagination] = useState<PaginationMeta | null>(null);
  const [ledgerPage, setLedgerPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const [encashingType, setEncashingType] = useState<LeaveBalance | null>(null);
  const [encashmentValues, setEncashmentValues] = useState<EncashmentFormValues>(
    emptyEncashmentFormValues(),
  );
  const [encashmentError, setEncashmentError] = useState<string | null>(null);
  const [encashmentSaving, setEncashmentSaving] = useState(false);
  const encashmentKey = useRef<string | null>(null);

  const targetEmployeeId = view === "MINE" ? (user?.employee_id ?? "") : selectedEmployeeId;

  // A different employee is a different person's data: drop it immediately (skeleton, not the
  // previous employee's balances dimmed under the new selection) and go back to page 1.
  useEffect(() => {
    setLedgerPage(1);
    setBalances(null);
    setLedger(null);
    setLedgerPagination(null);
    setError(null);
  }, [targetEmployeeId]);

  const load = useCallback(
    async (targetLedgerPage: number) => {
      const request = beginRequest();
      if (!targetEmployeeId) {
        setBalances(null);
        setLedger(null);
        setLedgerPagination(null);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const [balanceData, ledgerResult] = await Promise.all([
          apiClient.get<LeaveBalance[]>(`/leave-balances?employee_id=${targetEmployeeId}`, {
            signal: request.signal,
          }),
          apiClient.getList<LeaveLedgerEntry>(
            "/leave-ledger",
            { employee_id: targetEmployeeId, page: targetLedgerPage },
            { signal: request.signal },
          ),
        ]);
        if (!request.isCurrent()) return;
        setBalances(balanceData);
        setLedger(ledgerResult.data);
        setLedgerPagination(ledgerResult.pagination);
      } catch (err) {
        if (isAbortError(err) || !request.isCurrent()) return;
        setBalances(null);
        setLedger(null);
        setLedgerPagination(null);
        setError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      } finally {
        if (request.isCurrent()) setLoading(false);
      }
    },
    [beginRequest, targetEmployeeId],
  );

  useEffect(() => {
    void load(ledgerPage);
  }, [load, ledgerPage]);

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
      encashmentKey.current ??= newIdempotencyKey();
      await apiClient.post(
        "/leave-ledger/encashments",
        {
          employee_id: targetEmployeeId,
          leave_type_id: encashingType.leave_type_id,
          days: encashmentValues.days.trim(),
          effective_date: encashmentValues.effectiveDate,
          reason: encashmentValues.reason.trim() || "Encashment",
        },
        { headers: { "Idempotency-Key": encashmentKey.current } },
      );
      encashmentKey.current = null;
      setEncashingType(null);
      toast({ title: "Encashment recorded", variant: "success" });
      await load(ledgerPage);
    } catch (err) {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
        encashmentKey.current = null;
      }
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

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="Balance scope"
          className="inline-flex rounded-md border border-border bg-surface p-0.5"
        >
          <button
            type="button"
            onClick={() => setView("MINE")}
            className={cn(
              "rounded-sm px-3 py-1.5 text-xs font-medium transition-colors",
              view === "MINE"
                ? "bg-primary text-on-primary"
                : "text-foreground-secondary hover:bg-muted hover:text-foreground",
            )}
          >
            My balance
          </button>
          {canViewAll ? (
            <button
              type="button"
              onClick={() => setView("TEAM")}
              className={cn(
                "rounded-sm px-3 py-1.5 text-xs font-medium transition-colors",
                view === "TEAM"
                  ? "bg-primary text-on-primary"
                  : "text-foreground-secondary hover:bg-muted hover:text-foreground",
              )}
            >
              Team balances
            </button>
          ) : null}
        </div>

        {view === "TEAM" ? (
          <div className="w-full max-w-sm">
            <FormField id="leave-balances-employee" label="Employee">
              <EmployeeSelect
                directory={directory}
                value={selectedEmployeeId}
                emptyLabel="Choose an employee…"
                onChange={setSelectedEmployeeId}
              />
            </FormField>
          </div>
        ) : null}
      </div>

      {!targetEmployeeId && view === "TEAM" ? (
        <EmptyState icon={Wallet} title="Choose an employee to view their leave balance." />
      ) : null}

      {!targetEmployeeId && view === "MINE" ? (
        <ErrorState message="Your user account has no linked employee record." />
      ) : null}

      {targetEmployeeId ? (
        <div className="space-y-6">
          <TableContainer>
            <TableToolbar>
              <h2 className="text-sm font-semibold text-foreground">Available Leave Balances</h2>
            </TableToolbar>

            {loading && balances === null ? (
              <div role="status" aria-label="Loading balances">
                <TableSkeleton rows={5} columns={5} />
                <span className="sr-only">Loading balances…</span>
              </div>
            ) : null}
            {error && !loading ? (
              <div className="p-6">
                <ErrorState
                  message={
                    error.status === 403
                      ? "You do not have permission to view this balance."
                      : error.message
                  }
                  onRetry={() => void load(ledgerPage)}
                />
              </div>
            ) : null}
            {!error && balances && balances.length === 0 ? (
              <div className="p-6">
                <EmptyState
                  icon={Wallet}
                  title="No balance-backed leave types configured yet."
                  description="LOP-style leave types (requires_balance=false) never appear here."
                />
              </div>
            ) : null}
            {!error && balances && balances.length > 0 ? (
              <BusyRegion busy={loading} label="Refreshing balances…">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Leave type</TableHead>
                    <TableHead align="right">Available balance</TableHead>
                    <TableHead align="right">Reserved / pending</TableHead>
                    {canAdjust ? <TableHead align="right">Encashment</TableHead> : null}
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {balances.map((balance) => (
                    <TableRow key={balance.leave_type_id}>
                      <TableCell className="font-medium text-foreground">
                        {balance.leave_type_name}{" "}
                        <span className="font-mono text-xs text-foreground-muted">
                          ({balance.leave_type_code})
                        </span>
                      </TableCell>
                      <TableCell align="right" numeric className="font-semibold text-foreground">
                        {balance.balance}
                      </TableCell>
                      <TableCell align="right" numeric className="text-foreground-secondary">
                        {balance.reserved_balance}
                      </TableCell>
                      {canAdjust ? (
                        <TableCell align="right">
                          <Button
                            type="button"
                            variant="outline"
                            size="xs"
                            onClick={() => openEncash(balance)}
                          >
                            Encash
                          </Button>
                        </TableCell>
                      ) : null}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              </BusyRegion>
            ) : null}
          </TableContainer>

          <TableContainer>
            <TableToolbar>
              <h2 className="text-sm font-semibold text-foreground">
                Ledger
                {canAdjust
                  ? " (append-only — a correction is always a new entry, never an edit)"
                  : ""}
              </h2>
            </TableToolbar>

            {!error && ledger && ledger.length === 0 ? (
              <p className="px-4 py-8 text-center text-sm text-foreground-muted">
                No ledger activity yet.
              </p>
            ) : null}
            {!error && ledger && ledger.length > 0 ? (
              <BusyRegion busy={loading} label="Refreshing ledger…">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead>Date</TableHead>
                    <TableHead>Type</TableHead>
                    <TableHead align="right">Amount</TableHead>
                    <TableHead>Reason</TableHead>
                    <TableHead>Recorded</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {ledger.map((entry) => (
                    <TableRow key={entry.id}>
                      <TableCell className="tabular-nums text-foreground-secondary">
                        <CompanyDate value={entry.effective_date} />
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="font-mono text-2xs">
                          {entry.entry_type}
                        </Badge>
                      </TableCell>
                      <TableCell align="right" numeric className="font-medium text-foreground">
                        {entry.amount}
                      </TableCell>
                      <TableCell className="text-foreground-secondary">
                        {entry.reason ?? "—"}
                      </TableCell>
                      <TableCell className="text-xs tabular-nums text-foreground-muted">
                        {formatDateTime(entry.created_at, tz)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              </BusyRegion>
            ) : null}

            {!error && ledgerPagination ? (
              <PaginationControls
                pagination={ledgerPagination}
                onPageChange={setLedgerPage}
                disabled={loading}
              />
            ) : null}
          </TableContainer>
        </div>
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
                onChange={(e) =>
                  setEncashmentValues((c) => ({ ...c, reason: e.target.value }))
                }
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
            <Button
              type="button"
              onClick={() => void handleEncash()}
              disabled={encashmentSaving}
            >
              {encashmentSaving ? "Recording…" : "Record encashment"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
