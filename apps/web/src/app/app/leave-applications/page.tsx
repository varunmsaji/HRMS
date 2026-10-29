"use client";

import { CalendarOff, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { LeaveApplicationDialog } from "@/components/leave-application/leave-application-dialog";
import { LeaveApplicationStatusBadge } from "@/components/leave-application/leave-application-status-badge";
import { Button } from "@/components/ui/button";
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
import type { PaginationMeta } from "@/lib/api/types";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  LEAVE_APPLICATION_STATUSES,
  type LeaveApplication,
  type LeaveApplicationStatus,
} from "@/lib/leave-application/types";
import type { LeaveType } from "@/lib/leave-type/types";
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
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
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

  const load = useCallback(
    async (targetPage: number) => {
      setLoading(true);
      setError(null);
      try {
        const { data, pagination: meta } = await apiClient.getList<LeaveApplication>(
          "/leave-applications",
          {
            page: targetPage,
            date_from: dateFrom,
            date_to: dateTo,
            application_status: statusFilter || undefined,
            employee_id:
              view === "MINE"
                ? (user?.employee_id ?? undefined)
                : view === "TEAM"
                  ? employeeFilter || undefined
                  : undefined,
          },
        );
        setApplications(data);
        setPagination(meta);
      } catch (err) {
        setApplications(null);
        setPagination(null);
        setError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      } finally {
        setLoading(false);
      }
    },
    [dateFrom, dateTo, statusFilter, view, employeeFilter, user?.employee_id],
  );

  useEffect(() => {
    setPage(1);
  }, [dateFrom, dateTo, statusFilter, view, employeeFilter]);

  useEffect(() => {
    void load(page);
  }, [load, page]);

  useEffect(() => {
    void apiClient
      .get<LeaveType[]>("/leave-types")
      .then(setLeaveTypes)
      .catch(() => setLeaveTypes([]));
  }, []);

  useEffect(() => {
    if (view !== "TEAM") return;
    void apiClient
      .getList<EmployeeOption>("/employees", { per_page: 100 })
      .then(({ data }) => setEmployees(data))
      .catch(() => setEmployees([]));
  }, [view]);

  function onCreated(_application: LeaveApplication) {
    void load(page);
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
              <Plus className="h-4 w-4" aria-hidden="true" />
              Apply for leave
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="Application scope"
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
            My applications
          </button>
          {canApprove || canSubmitOnBehalf ? (
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
              Team applications
            </button>
          ) : null}
        </div>
      </div>

      <TableContainer>
        <TableToolbar className="grid grid-cols-1 gap-3 sm:grid-cols-4">
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

        {loading ? <LoadingState label="Loading leave applications…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view these applications."
                  : error.message
              }
              onRetry={() => void load(page)}
            />
          </div>
        ) : null}

        {!loading && !error && applications && applications.length === 0 ? (
          <div className="p-6">
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
          </div>
        ) : null}

        {!loading && !error && applications && applications.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Dates</TableHead>
                <TableHead>Employee</TableHead>
                <TableHead>Type</TableHead>
                <TableHead align="right">Days</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Stage</TableHead>
                <TableHead align="right">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {applications.map((application) => {
                const emp = employeeById.get(application.employee_id);
                const empLabel = employeeDisplayName(emp, application.employee_id);
                return (
                  <TableRow key={application.id}>
                    <TableCell className="whitespace-nowrap tabular-nums text-foreground-secondary">
                      {application.start_date === application.end_date ? (
                        <CompanyDate value={application.start_date} />
                      ) : (
                        <>
                          <CompanyDate value={application.start_date} /> –{" "}
                          <CompanyDate value={application.end_date} />
                        </>
                      )}
                    </TableCell>
                    <TableCell>
                      <EmployeeIdentityCell name={empLabel} size="sm" />
                    </TableCell>
                    <TableCell className="text-foreground-secondary">
                      {leaveTypeById.get(application.leave_type_id)?.name ??
                        application.leave_type_id}
                    </TableCell>
                    <TableCell align="right" numeric className="font-medium text-foreground">
                      {application.total_days}
                    </TableCell>
                    <TableCell>
                      <LeaveApplicationStatusBadge status={application.status} />
                    </TableCell>
                    <TableCell className="text-xs text-foreground-secondary">
                      {application.approval_stage ?? "—"}
                    </TableCell>
                    <TableCell align="right">
                      <Link
                        href={`/app/leave-applications/${application.id}`}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        View
                      </Link>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        ) : null}

        {!loading && !error && pagination ? (
          <PaginationControls
            pagination={pagination}
            onPageChange={setPage}
            disabled={loading}
          />
        ) : null}
      </TableContainer>

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
