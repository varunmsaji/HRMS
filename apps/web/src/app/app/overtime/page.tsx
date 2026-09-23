"use client";

import { AlarmClock } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { OvertimeStatusBadge } from "@/components/overtime/overtime-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
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
 * records. Every row is already DataScope-filtered server-side — "Mine" and "Team" are just
 * different query filters over the same permission-scoped read, mirroring the Regularizations
 * and Attendance dashboard's own posture. */
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

      <div className="flex gap-2">
        <Button
          type="button"
          variant={view === "MINE" ? "default" : "outline"}
          size="sm"
          onClick={() => setView("MINE")}
        >
          My overtime
        </Button>
        {canApprove ? (
          <Button
            type="button"
            variant={view === "TEAM" ? "default" : "outline"}
            size="sm"
            onClick={() => setView("TEAM")}
          >
            Team overtime
          </Button>
        ) : null}
      </div>

      <Card>
        <CardContent className="grid grid-cols-1 gap-4 pt-6 sm:grid-cols-4">
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
              <NativeSelect value={employeeFilter} onChange={(e) => setEmployeeFilter(e.target.value)}>
                <option value="">All employees</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {employeeDisplayName(emp, emp.id)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading overtime records…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view these overtime records."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}
          {!loading && !error && records && records.length === 0 ? (
            <EmptyState
              icon={AlarmClock}
              title="No overtime records in this range."
              description="Overtime records appear here automatically once attendance calculation detects overtime."
            />
          ) : null}
          {!loading && !error && records && records.length > 0 ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Date</th>
                    <th className="px-3 py-2 text-left font-medium">Employee</th>
                    <th className="px-3 py-2 text-left font-medium">Day class</th>
                    <th className="px-3 py-2 text-right font-medium">Detected</th>
                    <th className="px-3 py-2 text-right font-medium">Approved</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="px-3 py-2 text-left font-medium">Approval chain</th>
                    <th className="px-3 py-2 text-right font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {records.map((record) => (
                    <tr key={record.id} className="hover:bg-accent">
                      <td className="px-3 py-2 text-foreground-secondary">{record.attendance_date}</td>
                      <td className="px-3 py-2 font-medium text-foreground">
                        {employeeDisplayName(employeeById.get(record.employee_id), record.employee_id)}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {record.day_class ? OVERTIME_DAY_CLASS_LABELS[record.day_class] : "—"}
                      </td>
                      <td className="px-3 py-2 text-right text-foreground-secondary">
                        {formatMinutes(record.minutes_detected)}
                      </td>
                      <td className="px-3 py-2 text-right text-foreground-secondary">
                        {formatMinutes(record.minutes_approved)}
                      </td>
                      <td className="px-3 py-2">
                        <OvertimeStatusBadge status={record.status} />
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {OVERTIME_APPROVAL_CHAIN_LABELS[record.approval_chain]}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Link
                          href={`/app/overtime/${record.id}`}
                          className="text-sm font-medium text-primary hover:underline"
                        >
                          View
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
