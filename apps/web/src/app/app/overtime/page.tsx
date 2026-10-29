"use client";

import { AlarmClock } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
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
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { businessToday, formatMinutes } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  OVERTIME_APPROVAL_CHAIN_LABELS,
  OVERTIME_DAY_CLASS_LABELS,
  OVERTIME_STATUSES,
  type OvertimeRecord,
  type OvertimeStatus,
} from "@/lib/overtime/types";
import { cn } from "@/lib/utils";

interface EmployeeOption {
  id: string;
  first_name: string;
  last_name: string | null;
  employee_code: string | null;
}

function employeeDisplayName(employee: EmployeeOption | undefined, employeeId: string): string {
  if (!employee) return employeeId;
  const name = [employee.first_name, employee.last_name].filter(Boolean).join(" ");
  return employee.employee_code ? `${name} (${employee.employee_code})` : name;
}

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
  const [statusFilter, setStatusFilter] = useState<OvertimeStatus | "">("");
  const [employeeFilter, setEmployeeFilter] = useState("");

  const [records, setRecords] = useState<OvertimeRecord[] | null>(null);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const employeeById = useMemo(() => {
    const map = new Map<string, EmployeeOption>();
    for (const emp of employees) map.set(emp.id, emp);
    return map;
  }, [employees]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
      if (statusFilter) params.set("record_status", statusFilter);
      if (view === "MINE" && user?.employee_id) params.set("employee_id", user.employee_id);
      if (view === "TEAM" && employeeFilter) params.set("employee_id", employeeFilter);
      const data = await apiClient.get<OvertimeRecord[]>(`/overtime?${params.toString()}`);
      setRecords(data);
    } catch (err) {
      setRecords(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, statusFilter, view, employeeFilter, user?.employee_id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (view !== "TEAM") return;
    void apiClient
      .getList<EmployeeOption>("/employees", { per_page: 100 })
      .then(({ data }) => setEmployees(data))
      .catch(() => setEmployees([]));
  }, [view]);

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
              <NativeSelect
                value={employeeFilter}
                onChange={(e) => setEmployeeFilter(e.target.value)}
              >
                <option value="">All employees</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {employeeDisplayName(emp, emp.id)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          ) : null}
        </TableToolbar>

        {loading ? <LoadingState label="Loading overtime records…" /> : null}
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
        {!loading && !error && records && records.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={AlarmClock}
              title="No overtime records in this range."
              description="Overtime records appear here automatically once attendance calculation detects overtime."
            />
          </div>
        ) : null}
        {!loading && !error && records && records.length > 0 ? (
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
                      name={employeeDisplayName(
                        employeeById.get(record.employee_id),
                        record.employee_id,
                      )}
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
        ) : null}
      </TableContainer>
    </div>
  );
}
