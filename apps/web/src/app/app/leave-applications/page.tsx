"use client";

import { CalendarOff } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { LeaveApplicationDialog } from "@/components/leave-application/leave-application-dialog";
import { LeaveApplicationStatusBadge } from "@/components/leave-application/leave-application-status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  LEAVE_APPLICATION_STATUSES,
  type LeaveApplication,
  type LeaveApplicationStatus,
} from "@/lib/leave-application/types";
import type { LeaveType } from "@/lib/leave-type/types";

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

/** `/v1/leave-applications` list/filter + create (LEAVE_DECISION_LOG.md LD-02/LD-05). Every row
 * here is already DataScope-filtered server-side — "Mine" and "Team" are just different query
 * filters over the same permission-scoped read, mirroring `RegularizationsPage`'s posture. */
export default function LeaveApplicationsPage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const canApprove = can("LEAVE.APPLICATION_APPROVE");
  const canSubmitSelf = can("LEAVE.APPLICATION_SUBMIT");
  const canSubmitOnBehalf = can("LEAVE.APPLICATION_SUBMIT_ON_BEHALF");

  const [view, setView] = useState<ViewMode>(canApprove ? "TEAM" : "MINE");
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [dateFrom, setDateFrom] = useState(addDays(today, -30));
  const [dateTo, setDateTo] = useState(addDays(today, 90));
  const [statusFilter, setStatusFilter] = useState<LeaveApplicationStatus | "">("");
  const [employeeFilter, setEmployeeFilter] = useState("");

  const [applications, setApplications] = useState<LeaveApplication[] | null>(null);
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([]);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const employeeById = useMemo(() => {
    const map = new Map<string, EmployeeOption>();
    for (const emp of employees) map.set(emp.id, emp);
    return map;
  }, [employees]);

  const leaveTypeById = useMemo(() => {
    const map = new Map<string, LeaveType>();
    for (const lt of leaveTypes) map.set(lt.id, lt);
    return map;
  }, [leaveTypes]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params = new URLSearchParams({ date_from: dateFrom, date_to: dateTo });
      if (statusFilter) params.set("application_status", statusFilter);
      if (view === "MINE" && user?.employee_id) params.set("employee_id", user.employee_id);
      if (view === "TEAM" && employeeFilter) params.set("employee_id", employeeFilter);
      const data = await apiClient.get<LeaveApplication[]>(
        `/leave-applications?${params.toString()}`,
      );
      setApplications(data);
    } catch (err) {
      setApplications(null);
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
    void apiClient
      .get<LeaveType[]>("/leave-types")
      .then(setLeaveTypes)
      .catch(() => setLeaveTypes([]));
  }, []);

  useEffect(() => {
    if (view !== "TEAM") return;
    void apiClient
      .get<EmployeeOption[]>("/employees")
      .then(setEmployees)
      .catch(() => setEmployees([]));
  }, [view]);

  function onCreated(_application: LeaveApplication) {
    void load();
  }

  const canCreate = view === "MINE" ? canSubmitSelf : canSubmitOnBehalf;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Leave Applications"
        description="Employee, manager, and HR leave requests — submit, review, and approve."
        actions={
          canCreate ? (
            <Button type="button" onClick={() => setDialogOpen(true)}>
              Apply for leave
            </Button>
          ) : undefined
        }
      />

      <div className="flex gap-2">
        <Button
          type="button"
          variant={view === "MINE" ? "default" : "outline"}
          size="sm"
          onClick={() => setView("MINE")}
        >
          My applications
        </Button>
        {canApprove || canSubmitOnBehalf ? (
          <Button
            type="button"
            variant={view === "TEAM" ? "default" : "outline"}
            size="sm"
            onClick={() => setView("TEAM")}
          >
            Team applications
          </Button>
        ) : null}
      </div>

      <Card>
        <CardContent className="grid grid-cols-1 gap-4 pt-6 sm:grid-cols-4">
          <FormField id="leave-applications-date-from" label="From">
            <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </FormField>
          <FormField id="leave-applications-date-to" label="To">
            <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </FormField>
          <FormField id="leave-applications-status" label="Status">
            <NativeSelect
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as LeaveApplicationStatus | "")}
            >
              <option value="">All statuses</option>
              {LEAVE_APPLICATION_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          {view === "TEAM" ? (
            <FormField id="leave-applications-employee" label="Employee">
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
          {loading ? <LoadingState label="Loading leave applications…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view these applications."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}
          {!loading && !error && applications && applications.length === 0 ? (
            <EmptyState
              icon={CalendarOff}
              title="No leave applications in this range."
              description={
                canCreate ? "Apply for leave to get started." : "Nothing to review right now."
              }
              action={
                canCreate ? (
                  <Button type="button" onClick={() => setDialogOpen(true)}>
                    Apply for leave
                  </Button>
                ) : undefined
              }
            />
          ) : null}
          {!loading && !error && applications && applications.length > 0 ? (
            <div className="overflow-x-auto rounded-md border border-border">
              <table className="w-full text-sm">
                <thead className="bg-surface-secondary text-xs uppercase tracking-wide text-foreground-muted">
                  <tr>
                    <th className="px-3 py-2 text-left font-medium">Dates</th>
                    <th className="px-3 py-2 text-left font-medium">Employee</th>
                    <th className="px-3 py-2 text-left font-medium">Type</th>
                    <th className="px-3 py-2 text-right font-medium">Days</th>
                    <th className="px-3 py-2 text-left font-medium">Status</th>
                    <th className="px-3 py-2 text-left font-medium">Stage</th>
                    <th className="px-3 py-2 text-right font-medium">Detail</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {applications.map((application) => (
                    <tr key={application.id} className="hover:bg-accent">
                      <td className="px-3 py-2 text-foreground-secondary">
                        {application.start_date === application.end_date
                          ? application.start_date
                          : `${application.start_date} – ${application.end_date}`}
                      </td>
                      <td className="px-3 py-2 font-medium text-foreground">
                        {employeeDisplayName(
                          employeeById.get(application.employee_id),
                          application.employee_id,
                        )}
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {leaveTypeById.get(application.leave_type_id)?.name ?? application.leave_type_id}
                      </td>
                      <td className="px-3 py-2 text-right text-foreground-secondary">
                        {application.total_days}
                      </td>
                      <td className="px-3 py-2">
                        <LeaveApplicationStatusBadge status={application.status} />
                      </td>
                      <td className="px-3 py-2 text-foreground-secondary">
                        {application.approval_stage ?? "—"}
                      </td>
                      <td className="px-3 py-2 text-right">
                        <Link
                          href={`/app/leave-applications/${application.id}`}
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

      <LeaveApplicationDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={view === "TEAM" ? "ON_BEHALF" : "SELF"}
        employeeId={view === "TEAM" ? employeeFilter || undefined : undefined}
        employeeLabel={
          view === "TEAM" && employeeFilter
            ? employeeDisplayName(employeeById.get(employeeFilter), employeeFilter)
            : undefined
        }
        onCreated={onCreated}
      />
    </div>
  );
}
