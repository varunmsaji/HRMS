"use client";

import { AlarmClock } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { BusyRegion } from "@/components/common/busy-region";
import { PaginationControls } from "@/components/common/pagination-controls";
import { PageHeader } from "@/components/common/page-header";
import { OvertimeStatusBadge } from "@/components/overtime/overtime-status-badge";
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
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { initialQueryValue } from "@/lib/dashboard/overview";
import { businessToday, formatMinutes } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";
import {
  OVERTIME_APPROVAL_CHAIN_LABELS,
  OVERTIME_DAY_CLASS_LABELS,
  OVERTIME_STATUSES,
  type OvertimeRecord,
  type OvertimeStatus,
} from "@/lib/overtime/types";
import { cn } from "@/lib/utils";

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

type ViewMode = "MINE" | "TEAM";

/** `/v1/overtime` list/filter (architecture §13/§25). Overtime records are system-detected —
 * there is no create flow here, only viewing and, for approvers, reviewing already-existing
 * records. */
export default function OvertimePage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const canApprove = can("ATTENDANCE.OVERTIME_APPROVE");

  const [view, setView] = useState<ViewMode>(canApprove ? "TEAM" : "MINE");
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [dateFrom, setDateFrom] = useState(addDays(today, -30));
  const [dateTo, setDateTo] = useState(today);
  const [statusFilter, setStatusFilter] = useState<OvertimeStatus | "">(() =>
    initialQueryValue("status", OVERTIME_STATUSES),
  );
  const [employeeFilter, setEmployeeFilter] = useState("");

  const [records, setRecords] = useState<OvertimeRecord[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [page, setPage] = useState(1);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const beginRequest = useLatestRequest();
  const directory = useEmployeeDirectory({ enabled: view === "TEAM" });
  const rowEmployeeIds = useMemo(() => (records ?? []).map((r) => r.employee_id), [records]);
  const employeeName = useEmployeeNames(rowEmployeeIds, directory.employees);

  const load = useCallback(async () => {
    const request = beginRequest();
    setLoading(true);
    setError(null);
    try {
      const query: Record<string, string | undefined> = { date_from: dateFrom, date_to: dateTo };
      if (statusFilter) query.record_status = statusFilter;
      if (view === "MINE" && user?.employee_id) query.employee_id = user.employee_id;
      if (view === "TEAM" && employeeFilter) query.employee_id = employeeFilter;
      const { data, pagination: meta } = await apiClient.getList<OvertimeRecord>(
        "/overtime",
        { ...query, page, per_page: 100 },
        { signal: request.signal },
      );
      if (!request.isCurrent()) return;
      setRecords(data);
      setPagination(meta);
    } catch (err) {
      if (isAbortError(err) || !request.isCurrent()) return;
      setRecords(null);
      setPagination(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [beginRequest, page, dateFrom, dateTo, statusFilter, view, employeeFilter, user?.employee_id]);

  // Any filter change goes back to the first page (the in-flight request is cancelled).
  useEffect(() => {
    setPage(1);
  }, [dateFrom, dateTo, statusFilter, view, employeeFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="space-y-6">
      <PageHeader
        title="Overtime"
        description="System-detected overtime — reviewed and, where a policy requires it, approved or rejected."
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="Overtime scope"
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
            My overtime
          </button>
          {canApprove ? (
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
              Team overtime
            </button>
          ) : null}
        </div>
      </div>

      <TableContainer>
        <TableToolbar className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <FormField id="overtime-date-from" label="From">
            <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </FormField>
          <FormField id="overtime-date-to" label="To">
            <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </FormField>
          <FormField id="overtime-status" label="Status">
            <NativeSelect
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as OvertimeStatus | "")}
            >
              <option value="">All statuses</option>
              {OVERTIME_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          {view === "TEAM" ? (
            <FormField id="overtime-employee" label="Employee">
              <EmployeeSelect
                directory={directory}
                value={employeeFilter}
                emptyLabel="All employees"
                onChange={setEmployeeFilter}
              />
            </FormField>
          ) : null}
        </TableToolbar>

        {loading && records === null ? (
          <div role="status" aria-label="Loading overtime records">
            <TableSkeleton rows={8} columns={6} />
            <span className="sr-only">Loading overtime records…</span>
          </div>
        ) : null}
        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view these overtime records."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </div>
        ) : null}
        {!error && records && records.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={AlarmClock}
              title="No overtime records in this range."
              description="Overtime records appear here automatically once attendance calculation detects overtime."
            />
          </div>
        ) : null}
        {!error && records && records.length > 0 ? (
          <BusyRegion busy={loading} label="Refreshing…">
<Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Date</TableHead>
                <TableHead>Employee</TableHead>
                <TableHead>Day class</TableHead>
                <TableHead align="right">Detected</TableHead>
                <TableHead align="right">Approved</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Approval chain</TableHead>
                <TableHead align="right">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {records.map((record) => (
                <TableRow key={record.id}>
                  <TableCell className="tabular-nums text-foreground-secondary">
                    <CompanyDate value={record.attendance_date} />
                  </TableCell>
                  <TableCell>
                    <EmployeeIdentityCell
                      name={employeeName(record.employee_id)}
                      size="sm"
                    />
                  </TableCell>
                  <TableCell className="text-foreground-secondary">
                    {record.day_class ? OVERTIME_DAY_CLASS_LABELS[record.day_class] : "—"}
                  </TableCell>
                  <TableCell align="right" numeric className="text-foreground-secondary">
                    {formatMinutes(record.minutes_detected)}
                  </TableCell>
                  <TableCell align="right" numeric className="font-medium text-foreground">
                    {formatMinutes(record.minutes_approved)}
                  </TableCell>
                  <TableCell>
                    <OvertimeStatusBadge status={record.status} />
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    {OVERTIME_APPROVAL_CHAIN_LABELS[record.approval_chain]}
                  </TableCell>
                  <TableCell align="right">
                    <Link
                      href={`/app/overtime/${record.id}`}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      View
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
</BusyRegion>
        ) : null}
      {!error && pagination ? (
          <PaginationControls pagination={pagination} onPageChange={setPage} disabled={loading} />
        ) : null}
      </TableContainer>
    </div>
  );
}
