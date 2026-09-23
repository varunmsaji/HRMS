"use client";

import { CalendarClock } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AttendanceStatusBadge } from "@/components/attendance/attendance-status-badge";
import { PunchEntryDialog } from "@/components/attendance/punch-entry-dialog";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import {
  ATTENDANCE_STATUSES,
  ATTENDANCE_STATUS_LABELS,
  type AttendanceDay,
  type AttendanceStatus,
  type Punch,
} from "@/lib/attendance/types";
import { businessToday, formatMinutes } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";

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

const EXCEPTION_FILTERS = [
  { key: "missing_punch", label: "Missing punch" },
  { key: "config_error", label: "Config error" },
  { key: "pending_approval", label: "Pending approval" },
] as const;
type ExceptionFilterKey = (typeof EXCEPTION_FILTERS)[number]["key"];

function matchesException(day: AttendanceDay, key: ExceptionFilterKey): boolean {
  if (key === "missing_punch") return day.missing_punch;
  if (key === "config_error") return day.attendance_status === "CONFIG_ERROR";
  return day.is_pending_approval;
}

/** Attendance dashboard + daily/team list (architecture §26). `GET /v1/attendance/days` is
 * already DataScope-filtered server-side (SELF/REPORTEES/REPORTEE_TREE/COMPANY) — this page adds
 * no additional access control, only display filters on top of whatever the caller can already
 * see. Team filtering here is limited to what the backend query actually supports
 * (`employee_id`/`date_from`/`date_to`/`attendance_status`); department/branch/designation/shift
 * filters are not exposed since `list_attendance_days` has no such parameters — a known
 * limitation, not an oversight (see the W4 report). */
export default function AttendanceDashboardPage() {
  const { user } = useAuth();
  const { can } = usePermissions();

  const [date, setDate] = useState(businessToday(user?.company_timezone ?? "Asia/Kolkata"));
  const [statusFilter, setStatusFilter] = useState<AttendanceStatus | "">("");
  const [employeeFilter, setEmployeeFilter] = useState("");
  const [exceptionFilters, setExceptionFilters] = useState<Set<ExceptionFilterKey>>(new Set());

  const [days, setDays] = useState<AttendanceDay[] | null>(null);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [punchOpen, setPunchOpen] = useState(false);

  const employeeById = useMemo(() => {
    const map = new Map<string, EmployeeOption>();
    for (const emp of employees) map.set(emp.id, emp);
    return map;
  }, [employees]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ date_from: date, date_to: date });
      if (employeeFilter) params.set("employee_id", employeeFilter);
      if (statusFilter) params.set("attendance_status", statusFilter);
      const data = await apiClient.get<AttendanceDay[]>(`/attendance/days?${params.toString()}`);
      setDays(data);
    } catch (err) {
      setDays(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [date, employeeFilter, statusFilter]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    void apiClient
      .getList<EmployeeOption>("/employees", { per_page: 100 })
      .then(({ data }) => setEmployees(data))
      .catch(() => setEmployees([]));
  }, []);

  function toggleException(key: ExceptionFilterKey) {
    setExceptionFilters((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  const visibleDays = useMemo(() => {
    if (!days) return [];
    if (exceptionFilters.size === 0) return days;
    return days.filter((day) => Array.from(exceptionFilters).every((key) => matchesException(day, key)));
  }, [days, exceptionFilters]);

  const summary = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const day of days ?? []) {
      counts[day.attendance_status] = (counts[day.attendance_status] ?? 0) + 1;
    }
    const missingPunch = (days ?? []).filter((d) => d.missing_punch).length;
    const overtime = (days ?? []).filter((d) => d.is_overtime).length;
    const configError = (days ?? []).filter((d) => d.attendance_status === "CONFIG_ERROR").length;
    const weeklyOffOrHoliday = (days ?? []).filter(
      (d) => d.calendar_day_type === "WEEKLY_OFF" || d.calendar_day_type === "HOLIDAY",
    ).length;
    return {
      total: (days ?? []).length,
      present: (counts.PRESENT ?? 0) + (counts.WFH ?? 0) + (counts.ON_DUTY ?? 0),
      absent: counts.ABSENT ?? 0,
      halfDay: counts.HALF_DAY ?? 0,
      weeklyOffOrHoliday,
      missingPunch,
      overtime,
      configError,
    };
  }, [days]);

  function onPunchRecorded(_punch: Punch) {
    void load();
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Attendance"
        description="Daily status, exceptions, and punches across the employees you can see."
        actions={
          can("ATTENDANCE.PUNCH") || can("ATTENDANCE.PUNCH_ON_BEHALF") ? (
            <Button type="button" onClick={() => setPunchOpen(true)}>
              Record punch
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="grid grid-cols-2 gap-4 pt-6 sm:grid-cols-4 lg:grid-cols-7">
          {(
            [
              ["Present", summary.present, "text-success"],
              ["Absent", summary.absent, "text-danger"],
              ["Half day", summary.halfDay, "text-warning"],
              ["Weekly off / Holiday", summary.weeklyOffOrHoliday, "text-info"],
              ["Missing punch", summary.missingPunch, "text-warning"],
              ["Overtime", summary.overtime, "text-info"],
              ["Config error", summary.configError, "text-danger"],
            ] as const
          ).map(([label, value, tone]) => (
            <div key={label}>
              <p className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</p>
              <p className={`mt-1 text-2xl font-semibold ${tone}`}>{value}</p>
            </div>
          ))}
        </CardContent>
      </Card>

      <Card>
        <CardContent className="space-y-4 pt-6">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-4">
            <FormField id="dashboard-date" label="Date">
              <Input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
            </FormField>
            <FormField id="dashboard-employee" label="Employee">
              <NativeSelect value={employeeFilter} onChange={(e) => setEmployeeFilter(e.target.value)}>
                <option value="">All employees</option>
                {employees.map((emp) => (
                  <option key={emp.id} value={emp.id}>
                    {employeeDisplayName(emp, emp.id)}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
            <FormField id="dashboard-status" label="Status">
              <NativeSelect
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as AttendanceStatus | "")}
              >
                <option value="">All statuses</option>
                {ATTENDANCE_STATUSES.map((status) => (
                  <option key={status} value={status}>
                    {ATTENDANCE_STATUS_LABELS[status]}
                  </option>
                ))}
              </NativeSelect>
            </FormField>
          </div>
          <div className="flex flex-wrap gap-4">
            {EXCEPTION_FILTERS.map((filter) => (
              <label key={filter.key} className="flex items-center gap-2 text-sm text-foreground-secondary">
                <input
                  type="checkbox"
                  checked={exceptionFilters.has(filter.key)}
                  onChange={() => toggleException(filter.key)}
                  className="h-4 w-4 rounded border-input"
                />
                {filter.label}
              </label>
            ))}
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading attendance…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view attendance."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}
          {!loading && !error && visibleDays.length === 0 ? (
            <EmptyState
              icon={CalendarClock}
              title="No attendance days match these filters."
              description="Try a different date or clear the filters."
            />
          ) : null}
          {!loading && !error && visibleDays.length > 0 ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Employee</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="px-3 py-2 text-left font-medium">Calendar day</th>
                    <th className="px-3 py-2 text-left font-medium">Worked</th>
                    <th className="px-3 py-2 text-left font-medium">OT</th>
                    <th className="px-3 py-2 text-left font-medium">Exceptions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {visibleDays.map((day) => (
                    <tr key={day.id} className="hover:bg-accent">
                      <td className="px-3 py-2">
                        <Link
                          href={`/app/attendance/${day.id}`}
                          className="font-medium text-foreground hover:underline"
                        >
                          {employeeDisplayName(employeeById.get(day.employee_id), day.employee_id)}
                        </Link>
                      </td>
                      <td className="px-3 py-2">
                        <AttendanceStatusBadge status={day.attendance_status} />
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">{day.calendar_day_type ?? "—"}</td>
                      <td className="px-3 py-2 text-foreground-secondary">{formatMinutes(day.worked_minutes)}</td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {day.is_overtime ? formatMinutes(day.ot_minutes_detected) : "—"}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {day.missing_punch ? "Missing punch " : ""}
                        {day.attendance_status === "CONFIG_ERROR" ? "Config error " : ""}
                        {day.is_pending_approval ? "Pending approval " : ""}
                        {!day.missing_punch && day.attendance_status !== "CONFIG_ERROR" && !day.is_pending_approval
                          ? "—"
                          : ""}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <PunchEntryDialog open={punchOpen} onOpenChange={setPunchOpen} onRecorded={onPunchRecorded} />
    </div>
  );
}
