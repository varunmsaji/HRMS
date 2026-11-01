"use client";

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { PayRunEmployeeDialog } from "@/components/payroll/pay-run-employee-dialog";
import { PayRunStatCards, PreDisbursalChecklist } from "@/components/payroll/pay-run-overview";
import { PayRunStatusBadge } from "@/components/payroll/pay-run-status-badge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
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
import { apiClient, newIdempotencyKey } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import { formatCompanyDate } from "@/lib/dates/company-date";
import { useCompanyDatePattern } from "@/lib/dates/use-company-date";
import type { LegalEntity } from "@/lib/legal-entity/types";
import {
  formatInr,
  formatPayMonth,
  payRunActions,
  type PayAdjustment,
  type PayRun,
  type PayRunEmployee,
} from "@/lib/payroll/types";

type Action = "lock-inputs" | "compute" | "approve" | "finalise" | "mark-paid";

const CONFIRM: Partial<Record<Action, { title: string; description: string; label: string }>> = {
  finalise: {
    title: "Finalise this pay run?",
    description:
      "A finalised pay run can never change, and the month's attendance period can no longer be " +
      "reopened. Later corrections are paid as arrears in a future run.",
    label: "Finalise",
  },
  "mark-paid": {
    title: "Mark this pay run as paid?",
    description: "Records that salaries have been transferred.",
    label: "Mark paid",
  },
};

/** Payroll Phase 5.2 — one pay run: lock inputs from the closed attendance period, compute,
 * resolve errors and acknowledge variances, then approve (a different user — D9), finalise and
 * mark paid. The backend decides every transition; this page only offers the plausible ones. */
export default function PayRunDetailPage() {
  const params = useParams<{ id: string }>();
  const router = useRouter();
  const { toast } = useToast();
  const { can } = usePermissions();
  const datePattern = useCompanyDatePattern();
  const canProcess = can("PAYROLL.RUN_PROCESS");
  const canApprove = can("PAYROLL.RUN_APPROVE");
  const canBankAdvice = can("PAYROLL.BANK_ADVICE_DOWNLOAD");

  const [query, setQuery] = useState("");
  const [run, setRun] = useState<PayRun | null>(null);
  const [employees, setEmployees] = useState<PayRunEmployee[]>([]);
  const [entityName, setEntityName] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState<"ALL" | "ISSUES" | "VARIANCE">("ALL");

  const [confirm, setConfirm] = useState<Action | null>(null);
  const [detailEmployeeId, setDetailEmployeeId] = useState<string | null>(null);
  const [ackEmployee, setAckEmployee] = useState<PayRunEmployee | null>(null);
  const [ackReason, setAckReason] = useState("");
  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [rollbackTo, setRollbackTo] = useState<"DRAFT" | "INPUTS_LOCKED">("INPUTS_LOCKED");
  const [rollbackReason, setRollbackReason] = useState("");
  const [payDateOpen, setPayDateOpen] = useState(false);
  const [payDate, setPayDate] = useState("");
  const [dialogError, setDialogError] = useState<string | null>(null);
  const [corrections, setCorrections] = useState<PayAdjustment[]>([]);
  const [correctEmployee, setCorrectEmployee] = useState<PayRunEmployee | null>(null);
  const correctionKey = useRef<string | null>(null);
  const [correctDelta, setCorrectDelta] = useState("");
  const [correctReason, setCorrectReason] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [runData, employeeData] = await Promise.all([
        apiClient.get<PayRun>(`/payroll/pay-runs/${params.id}`),
        apiClient.get<PayRunEmployee[]>(`/payroll/pay-runs/${params.id}/employees`),
      ]);
      setRun(runData);
      setEmployees(employeeData);
      if (runData.status === "FINALISED" || runData.status === "PAID") {
        apiClient
          .get<PayAdjustment[]>(`/payroll/adjustments?source_pay_run_id=${runData.id}`)
          .then(setCorrections)
          .catch(() => setCorrections([]));
      } else {
        setCorrections([]);
      }
      apiClient
        .get<LegalEntity>(`/legal-entities/${runData.legal_entity_id}`)
        .then((entity) => setEntityName(entity.name))
        .catch(() => setEntityName(null));
    } catch (err) {
      setRun(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  function explain(err: unknown): string {
    if (err instanceof ApiError && err.code === "PAY_RUN_BLOCKED") {
      const reasons = err.details[0]?.context?.reasons as { message: string }[] | undefined;
      if (reasons?.length) return reasons.map((r) => r.message).join("; ");
    }
    return describeApiError(err);
  }

  async function runAction(action: Action) {
    if (!run) return;
    setBusy(true);
    try {
      await apiClient.post<PayRun>(`/payroll/pay-runs/${run.id}/${action}`, undefined, {
        ifMatch: String(run.version),
      });
      setConfirm(null);
      await load();
    } catch (err) {
      toast({ title: "Action failed", description: explain(err), variant: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function handleRollback() {
    if (!run) return;
    setBusy(true);
    setDialogError(null);
    try {
      await apiClient.post<PayRun>(
        `/payroll/pay-runs/${run.id}/rollback`,
        { to_status: rollbackTo, reason: rollbackReason.trim() },
        { ifMatch: String(run.version) },
      );
      setRollbackOpen(false);
      await load();
    } catch (err) {
      setDialogError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleAcknowledge() {
    if (!run || !ackEmployee) return;
    setBusy(true);
    setDialogError(null);
    try {
      await apiClient.post<PayRunEmployee>(
        `/payroll/pay-runs/${run.id}/employees/${ackEmployee.employee_id}/acknowledge-variance`,
        { reason: ackReason.trim() },
      );
      setAckEmployee(null);
      await load();
    } catch (err) {
      setDialogError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handlePayDate() {
    if (!run) return;
    setBusy(true);
    setDialogError(null);
    try {
      await apiClient.patch<PayRun>(
        `/payroll/pay-runs/${run.id}`,
        { pay_date: payDate },
        { ifMatch: String(run.version) },
      );
      setPayDateOpen(false);
      await load();
    } catch (err) {
      setDialogError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function handleCorrect() {
    if (!run || !correctEmployee) return;
    setBusy(true);
    setDialogError(null);
    try {
      correctionKey.current ??= newIdempotencyKey();
      await apiClient.post<PayAdjustment>(
        "/payroll/adjustments",
        {
          source_pay_run_id: run.id,
          employee_id: correctEmployee.employee_id,
          paid_days_delta: correctDelta.trim(),
          reason: correctReason.trim(),
        },
        { headers: { "Idempotency-Key": correctionKey.current } },
      );
      correctionKey.current = null;
      setCorrectEmployee(null);
      toast({
        title: "Correction recorded",
        description: "It is paid in the next pay run.",
        variant: "success",
      });
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status >= 400 && err.status < 500) {
        correctionKey.current = null;
      }
      setDialogError(describeApiError(err));
    } finally {
      setBusy(false);
    }
  }

  async function withdrawCorrection(correction: PayAdjustment) {
    setBusy(true);
    try {
      await apiClient.delete(`/payroll/adjustments/${correction.id}`);
      await load();
    } catch (err) {
      toast({ title: "Could not withdraw", description: describeApiError(err), variant: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function downloadBankAdvice() {
    if (!run) return;
    setBusy(true);
    try {
      const file = await apiClient.download(`/payroll/pay-runs/${run.id}/bank-advice`);
      const url = URL.createObjectURL(file.blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.filename ?? `bank-advice-${run.month}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      toast({ title: "Could not download", description: describeApiError(err), variant: "danger" });
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    if (!run) return;
    setBusy(true);
    try {
      await apiClient.delete(`/payroll/pay-runs/${run.id}`);
      router.push("/app/payroll/pay-runs");
    } catch (err) {
      toast({ title: "Could not delete", description: describeApiError(err), variant: "danger" });
      setBusy(false);
    }
  }

  if (loading && !run) return <LoadingState label="Loading pay run…" />;
  if (error || !run) {
    return (
      <ErrorState
        message={
          error?.status === 403
            ? "You do not have permission to view pay runs."
            : (error?.message ?? "Pay run not found.")
        }
        onRetry={() => void load()}
      />
    );
  }

  const actions = payRunActions(run.status);
  const computed = !["DRAFT", "INPUTS_LOCKED"].includes(run.status);
  const q = query.trim().toLowerCase();
  const visible = employees.filter(
    (employee) =>
      (filter === "ISSUES"
        ? employee.issues.length > 0
        : filter === "VARIANCE"
          ? employee.variance_flagged
          : true) &&
      (!q ||
        (employee.employee_name ?? "").toLowerCase().includes(q) ||
        (employee.employee_code ?? "").toLowerCase().includes(q)),
  );
  const confirmCopy = confirm ? CONFIRM[confirm] : undefined;

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/payroll/pay-runs"
        backLabel="Pay Runs"
        title={`Pay run — ${formatPayMonth(run.month)}`}
        description={`${entityName ?? "Company"} · ${formatCompanyDate(run.period_start, datePattern)} to ${formatCompanyDate(run.period_end, datePattern)}`}
        badge={<PayRunStatusBadge status={run.status} />}
        actions={
          <div className="flex flex-wrap items-center gap-2">
            {canProcess && actions.lockInputs ? (
              <Button type="button" disabled={busy} onClick={() => void runAction("lock-inputs")}>
                Lock inputs
              </Button>
            ) : null}
            {canProcess && actions.compute ? (
              <Button
                type="button"
                variant={run.status === "COMPUTED" ? "outline" : "default"}
                disabled={busy}
                onClick={() => void runAction("compute")}
              >
                {run.status === "COMPUTED" ? "Recompute" : "Compute"}
              </Button>
            ) : null}
            {canApprove && actions.approve ? (
              <Button type="button" disabled={busy} onClick={() => void runAction("approve")}>
                Approve
              </Button>
            ) : null}
            {canApprove && actions.finalise ? (
              <Button type="button" disabled={busy} onClick={() => setConfirm("finalise")}>
                Finalise
              </Button>
            ) : null}
            {canApprove && actions.markPaid ? (
              <Button type="button" disabled={busy} onClick={() => setConfirm("mark-paid")}>
                Mark paid
              </Button>
            ) : null}
            {canProcess && actions.rollbackTo.length > 0 ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => {
                  setRollbackTo(actions.rollbackTo[0]);
                  setRollbackReason("");
                  setDialogError(null);
                  setRollbackOpen(true);
                }}
              >
                Roll back
              </Button>
            ) : null}
            {canBankAdvice && (run.status === "FINALISED" || run.status === "PAID") ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => void downloadBankAdvice()}
              >
                Bank advice (CSV)
              </Button>
            ) : null}
            {canProcess && actions.remove ? (
              <Button
                type="button"
                variant="outline"
                disabled={busy}
                onClick={() => void handleDelete()}
              >
                Delete
              </Button>
            ) : null}
          </div>
        }
      />

      <PayRunStatCards run={run} computed={computed} />

      <PreDisbursalChecklist run={run} />

      <div className="overflow-hidden rounded-lg border border-border bg-surface">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-border bg-surface-secondary/50 px-4 py-2.5 text-xs text-foreground-secondary">
          <span className="tabular-nums">
            Pay date <CompanyDate value={run.pay_date} />
            {canProcess && actions.editPayDate ? (
              <button
                type="button"
                className="ml-2 font-medium text-primary hover:underline"
                onClick={() => {
                  setPayDate(run.pay_date);
                  setDialogError(null);
                  setPayDateOpen(true);
                }}
              >
                Change
              </button>
            ) : null}
          </span>
          {run.attendance_period_id ? (
            <Link
              href={`/app/attendance-periods/${run.attendance_period_id}`}
              className="font-medium text-primary hover:underline"
            >
              Attendance period
            </Link>
          ) : null}
          {run.variance_threshold_percent ? (
            <span className="tabular-nums">
              Variance threshold {run.variance_threshold_percent}%
            </span>
          ) : null}
          {run.last_rollback_reason ? (
            <span>Last rolled back: {run.last_rollback_reason}</span>
          ) : null}
        </div>
      </div>

      {run.status === "DRAFT" ? (
        <div className="rounded-lg border border-info-border bg-info-subtle px-4 py-3 text-xs text-foreground-secondary">
          Lock the inputs once this month&apos;s attendance period for the company is closed.
          Everything the pay is computed from is copied into the run at that moment.
        </div>
      ) : null}

      {run.status === "COMPUTED" && (run.error_count > 0 || run.variance_open_count > 0) ? (
        <div
          role="status"
          className="rounded-lg border border-warning-border bg-warning-subtle px-4 py-3 text-sm text-foreground"
        >
          Before approval:{" "}
          {[
            run.error_count > 0 ? `${run.error_count} employee(s) with errors to fix` : null,
            run.variance_open_count > 0
              ? `${run.variance_open_count} flagged variance(s) to acknowledge`
              : null,
          ]
            .filter(Boolean)
            .join(", ")}
          . The user who computed the run cannot approve it.
        </div>
      ) : null}

      {employees.length > 0 ? (
        <TableContainer>
          <TableToolbar>
            <div className="relative w-full max-w-xs">
              <Search
                className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-foreground-muted"
                aria-hidden="true"
              />
              <Input
                type="search"
                aria-label="Search employees"
                placeholder="Search by name or code…"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                className="pl-8"
              />
            </div>
            <div className="w-full max-w-xs">
              <NativeSelect
                aria-label="Filter employees"
                value={filter}
                onChange={(e) => setFilter(e.target.value as typeof filter)}
              >
                <option value="ALL">All employees ({employees.length})</option>
                <option value="ISSUES">With issues</option>
                <option value="VARIANCE">Flagged variance</option>
              </NativeSelect>
            </div>
          </TableToolbar>

          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Employee</TableHead>
                <TableHead align="right">Paid days</TableHead>
                <TableHead align="right">LOP</TableHead>
                <TableHead align="right">Gross</TableHead>
                <TableHead align="right">Deductions</TableHead>
                <TableHead align="right">Net</TableHead>
                <TableHead>Variance</TableHead>
                <TableHead>Issues</TableHead>
                <TableHead align="right">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {visible.map((employee) => (
                <TableRow key={employee.id}>
                  <TableCell>
                    <EmployeeIdentityCell
                      name={employee.employee_name ?? "Employee"}
                      code={employee.employee_code}
                      subtitle={employee.pay_basis === "DAILY_WAGE" ? "daily-wage" : undefined}
                      size="sm"
                    />
                  </TableCell>
                  <TableCell align="right" numeric>
                    {employee.paid_days ?? "—"}
                  </TableCell>
                  <TableCell align="right" numeric className="text-foreground-secondary">
                    {employee.lop_days ?? "—"}
                  </TableCell>
                  <TableCell align="right" numeric>
                    {employee.is_computed ? formatInr(employee.gross_minor) : "—"}
                  </TableCell>
                  <TableCell align="right" numeric className="text-danger">
                    {employee.is_computed && employee.deductions_minor > 0
                      ? `−${formatInr(employee.deductions_minor)}`
                      : "—"}
                  </TableCell>
                  <TableCell align="right" numeric className="font-semibold text-foreground">
                    {employee.is_computed ? formatInr(employee.net_minor) : "—"}
                  </TableCell>
                  <TableCell>
                    {employee.variance_flagged ? (
                      <div className="space-y-1">
                        <Badge variant={employee.variance_reason ? "outline" : "warning"}>
                          {employee.variance_percent !== null
                            ? `${employee.variance_percent}%`
                            : "Changed"}
                        </Badge>
                        {employee.variance_reason ? (
                          <div className="text-xs text-foreground-muted">
                            {employee.variance_reason}
                          </div>
                        ) : canProcess && run.status === "COMPUTED" ? (
                          <button
                            type="button"
                            className="block text-xs font-medium text-primary hover:underline"
                            onClick={() => {
                              setAckEmployee(employee);
                              setAckReason("");
                              setDialogError(null);
                            }}
                          >
                            Acknowledge
                          </button>
                        ) : null}
                      </div>
                    ) : employee.variance_percent !== null ? (
                      <span className="tabular-nums text-foreground-muted">
                        {employee.variance_percent}%
                      </span>
                    ) : (
                      <span className="text-foreground-muted">—</span>
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {employee.issues.map((issue) => (
                        <Badge
                          key={`${issue.code}-${issue.message}`}
                          variant={issue.severity === "ERROR" ? "danger" : "warning"}
                          title={issue.message}
                        >
                          {issue.code.replaceAll("_", " ").toLowerCase()}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell align="right">
                    <div className="flex justify-end gap-3">
                      <button
                        type="button"
                        className="text-xs font-medium text-primary hover:underline"
                        onClick={() => setDetailEmployeeId(employee.employee_id)}
                      >
                        View
                      </button>
                      {computed && employee.is_computed ? (
                        <Link
                          href={`/app/payroll/pay-runs/${run.id}/payslips/${employee.employee_id}`}
                          className="text-xs font-medium text-primary hover:underline"
                        >
                          Payslip
                        </Link>
                      ) : null}
                      {canProcess &&
                      (run.status === "FINALISED" || run.status === "PAID") &&
                      employee.paid_days !== null ? (
                        <button
                          type="button"
                          className="text-xs font-medium text-primary hover:underline"
                          onClick={() => {
                            setCorrectEmployee(employee);
                            correctionKey.current = null;
                            setCorrectDelta("");
                            setCorrectReason("");
                            setDialogError(null);
                          }}
                        >
                          Correct days
                        </button>
                      ) : null}
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}

      {corrections.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Day corrections for this month</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <ul className="divide-y divide-border text-sm">
              {corrections.map((correction) => {
                const employee = employees.find((e) => e.employee_id === correction.employee_id);
                return (
                  <li
                    key={correction.id}
                    className="flex flex-wrap items-center justify-between gap-2 px-5 py-3"
                  >
                    <span>
                      <span className="font-medium text-foreground">
                        {employee?.employee_name ?? "Employee"}
                      </span>{" "}
                      <span className="tabular-nums">
                        {Number(correction.paid_days_delta) > 0 ? "+" : ""}
                        {correction.paid_days_delta} day(s)
                      </span>{" "}
                      · <span className="text-foreground-muted">{correction.reason}</span>
                    </span>
                    <span className="flex items-center gap-2">
                      <Badge variant={correction.status === "APPLIED" ? "success" : "warning"}>
                        {correction.status === "APPLIED" ? "Paid as arrears" : "Pending — next run"}
                      </Badge>
                      {canProcess && correction.status === "PENDING" ? (
                        <button
                          type="button"
                          className="text-xs font-medium text-primary hover:underline"
                          disabled={busy}
                          onClick={() => void withdrawCorrection(correction)}
                        >
                          Withdraw
                        </button>
                      ) : null}
                    </span>
                  </li>
                );
              })}
            </ul>
          </CardContent>
        </Card>
      ) : null}

      <Dialog
        open={correctEmployee !== null}
        onOpenChange={(next) => !busy && !next && setCorrectEmployee(null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Correct paid days</DialogTitle>
            <DialogDescription>
              {correctEmployee
                ? `${correctEmployee.employee_name ?? "Employee"} was paid for ${correctEmployee.paid_days} of ${correctEmployee.payable_days} days in ${formatPayMonth(run.month)}. `
                : null}
              This month is finalised and its attendance stays closed — the difference is paid (or
              recovered) as arrears in the next pay run.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <FormField
              id="correct-delta"
              label="Change in paid days"
              required
              description="e.g. 1, 0.5 or -1"
            >
              <Input
                inputMode="decimal"
                value={correctDelta}
                onChange={(e) => setCorrectDelta(e.target.value)}
              />
            </FormField>
            <FormField
              id="correct-reason"
              label="Reason"
              required
              error={dialogError ?? undefined}
            >
              <Input
                value={correctReason}
                maxLength={1000}
                onChange={(e) => setCorrectReason(e.target.value)}
              />
            </FormField>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setCorrectEmployee(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={
                busy || !/^-?\d+(\.5|\.0)?$/.test(correctDelta.trim()) || !correctReason.trim()
              }
              onClick={() => void handleCorrect()}
            >
              Record correction
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <PayRunEmployeeDialog
        runId={run.id}
        employeeId={detailEmployeeId}
        onOpenChange={(open) => !open && setDetailEmployeeId(null)}
      />

      <Dialog open={confirm !== null} onOpenChange={(next) => !busy && !next && setConfirm(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{confirmCopy?.title}</DialogTitle>
            <DialogDescription>{confirmCopy?.description}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirm(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={busy}
              onClick={() => confirm && void runAction(confirm)}
            >
              {busy ? "Working…" : confirmCopy?.label}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={ackEmployee !== null}
        onOpenChange={(next) => !busy && !next && setAckEmployee(null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Acknowledge variance</DialogTitle>
            <DialogDescription>
              {ackEmployee
                ? `${ackEmployee.employee_name ?? "Employee"}: net pay ${
                    ackEmployee.previous_net_minor !== null
                      ? formatInr(ackEmployee.previous_net_minor)
                      : "—"
                  } last run → ${formatInr(ackEmployee.net_minor)} now. Say why.`
                : null}
            </DialogDescription>
          </DialogHeader>
          <FormField
            id="variance-reason"
            label="Reason"
            required
            error={dialogError ?? undefined}
          >
            <Input
              value={ackReason}
              maxLength={1000}
              onChange={(e) => setAckReason(e.target.value)}
            />
          </FormField>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setAckEmployee(null)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={busy || !ackReason.trim()}
              onClick={() => void handleAcknowledge()}
            >
              Acknowledge
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rollbackOpen} onOpenChange={(next) => !busy && setRollbackOpen(next)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Roll back pay run</DialogTitle>
            <DialogDescription>
              Back to inputs locked discards the computed pay; back to draft also discards the
              input snapshot, so the inputs are read again when they are next locked.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <FormField id="rollback-to" label="Roll back to">
              <NativeSelect
                value={rollbackTo}
                onChange={(e) =>
                  setRollbackTo(e.target.value as "DRAFT" | "INPUTS_LOCKED")
                }
              >
                {actions.rollbackTo.map((target) => (
                  <option key={target} value={target}>
                    {target === "DRAFT" ? "Draft" : "Inputs locked"}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField
              id="rollback-reason"
              label="Reason"
              required
              error={dialogError ?? undefined}
            >
              <Input
                value={rollbackReason}
                maxLength={1000}
                onChange={(e) => setRollbackReason(e.target.value)}
              />
            </FormField>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setRollbackOpen(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={busy || !rollbackReason.trim()}
              onClick={() => void handleRollback()}
            >
              Roll back
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={payDateOpen} onOpenChange={(next) => !busy && setPayDateOpen(next)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle>Pay date</DialogTitle>
            <DialogDescription>When salaries for this month are paid.</DialogDescription>
          </DialogHeader>
          <FormField id="pay-date" label="Pay date" required error={dialogError ?? undefined}>
            <Input
              type="date"
              value={payDate}
              onChange={(e) => setPayDate(e.target.value)}
            />
          </FormField>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setPayDateOpen(false)}
              disabled={busy}
            >
              Cancel
            </Button>
            <Button
              type="button"
              disabled={busy || !payDate}
              onClick={() => void handlePayDate()}
            >
              Save
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
