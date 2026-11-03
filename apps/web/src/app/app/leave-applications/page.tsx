"use client";

import { CalendarOff, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { BusyRegion } from "@/components/common/busy-region";
import { PageHeader } from "@/components/common/page-header";
import { ScopeTabs } from "@/components/common/scope-tabs";
import { PaginationControls } from "@/components/common/pagination-controls";
import { LeaveApplicationDialog } from "@/components/leave-application/leave-application-dialog";
import { LeaveDecisionCenter } from "@/components/leave-application/decision-center";
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
import { TableSkeleton } from "@/components/ui/skeleton";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { EmployeeSelect } from "@/components/employee/employee-select";
import { apiClient } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { useEmployeeNames } from "@/lib/employee/use-employee-names";
import { ApiError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { initialQueryValue } from "@/lib/dashboard/overview";
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

function addDays(iso: string, days: number): string {
  const date = new Date(`${iso}T00:00:00Z`);
  date.setUTCDate(date.getUTCDate() + days);
  return date.toISOString().slice(0, 10);
}

type ViewMode = "MINE" | "TEAM" | "DECISIONS";

/** `/v1/leave-applications` list/filter + create (LEAVE_DECISION_LOG.md LD-02/LD-05). Every row
 * here is already DataScope-filtered server-side — "Mine" and "Team" are just different query
 * filters over the same permission-scoped read, mirroring `RegularizationsPage`'s posture. */
export default function LeaveApplicationsPage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const canApprove = can("LEAVE.APPLICATION_APPROVE");
  const canSubmitSelf = can("LEAVE.APPLICATION_SUBMIT");
  const canSubmitOnBehalf = can("LEAVE.APPLICATION_SUBMIT_ON_BEHALF");

  // The company account has no employee record, so it has no applications of its own.
  const hasOwnRecord = Boolean(user?.employee_id);
  const [view, setView] = useState<ViewMode>(
    canApprove ? "DECISIONS" : hasOwnRecord ? "MINE" : "TEAM",
  );
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [dateFrom, setDateFrom] = useState(addDays(today, -30));
  const [dateTo, setDateTo] = useState(addDays(today, 90));
  const [statusFilter, setStatusFilter] = useState<LeaveApplicationStatus | "">(() =>
    initialQueryValue("status", LEAVE_APPLICATION_STATUSES),
  );
  const [employeeFilter, setEmployeeFilter] = useState("");

  const [applications, setApplications] = useState<LeaveApplication[] | null>(null);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
  const [leaveTypes, setLeaveTypes] = useState<LeaveType[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

  const directory = useEmployeeDirectory({ enabled: view === "TEAM" });
  const rowEmployeeIds = useMemo(
    () => (applications ?? []).map((a) => a.employee_id),
    [applications],
  );
  const employeeName = useEmployeeNames(rowEmployeeIds, directory.employees);

  const leaveTypeById = useMemo(() => {
    const map = new Map<string, LeaveType>();
    for (const lt of leaveTypes) map.set(lt.id, lt);
    return map;
  }, [leaveTypes]);

  const beginRequest = useLatestRequest();

  const load = useCallback(
    async (targetPage: number) => {
      const request = beginRequest();
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
          { signal: request.signal },
        );
        if (!request.isCurrent()) return;
        setApplications(data);
        setPagination(meta);
      } catch (err) {
        if (isAbortError(err) || !request.isCurrent()) return;
        setApplications(null);
        setPagination(null);
        setError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
      } finally {
        if (request.isCurrent()) setLoading(false);
      }
    },
    [beginRequest, dateFrom, dateTo, statusFilter, view, employeeFilter, user?.employee_id],
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
        <ScopeTabs
          label="Application scope"
          value={view}
          onChange={setView}
          options={[
            { value: "MINE", label: "My applications", show: hasOwnRecord },
            { value: "DECISIONS", label: "Decision center", show: canApprove },
            { value: "TEAM", label: "Team applications", show: canApprove || canSubmitOnBehalf },
          ]}
        />
      </div>

      {view === "DECISIONS" ? <LeaveDecisionCenter /> : null}

      {view !== "DECISIONS" ? (
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
              <EmployeeSelect
                directory={directory}
                value={employeeFilter}
                emptyLabel="All employees"
                onChange={setEmployeeFilter}
              />
            </FormField>
          ) : null}
        </TableToolbar>

        {loading && applications === null ? (
          <div role="status" aria-label="Loading leave applications">
            <TableSkeleton rows={8} columns={6} />
            <span className="sr-only">Loading leave applications…</span>
          </div>
        ) : null}

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

        {!error && applications && applications.length === 0 ? (
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

        {!error && applications && applications.length > 0 ? (
          <BusyRegion busy={loading} label="Refreshing…">
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
                const empLabel = employeeName(application.employee_id);
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
</BusyRegion>
        ) : null}

        {!error && pagination ? (
          <PaginationControls
            pagination={pagination}
            onPageChange={setPage}
            disabled={loading}
          />
        ) : null}
      </TableContainer>
      ) : null}

      <LeaveApplicationDialog
        open={dialogOpen}
        onOpenChange={setDialogOpen}
        mode={view === "TEAM" ? "ON_BEHALF" : "SELF"}
        employeeId={view === "TEAM" ? employeeFilter || undefined : undefined}
        employeeLabel={
          view === "TEAM" && employeeFilter
            ? employeeName(employeeFilter)
            : undefined
        }
        onCreated={onCreated}
      />
    </div>
  );
}
