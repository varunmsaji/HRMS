"use client";

import { FileClock, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { RegularizationRequestDialog } from "@/components/regularization/regularization-request-dialog";
import { RegularizationStatusBadge } from "@/components/regularization/regularization-status-badge";
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
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  REGULARIZATION_STATUSES,
  REGULARIZATION_TYPES,
  REGULARIZATION_TYPE_LABELS,
  type RegularizationRequest,
  type RegularizationStatus,
  type RegularizationType,
} from "@/lib/regularization/types";
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

/** `/v1/regularizations` list/filter + create (architecture §13/§25, WD-28). Every row here is
 * already DataScope-filtered server-side — "Mine" and "Team" are just different query filters
 * over the same permission-scoped read, mirroring the Attendance dashboard's own posture. */
export default function RegularizationsPage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  const canApprove = can("ATTENDANCE.REGULARIZATION_APPROVE");
  const canSubmitSelf = can("ATTENDANCE.REGULARIZATION_REQUEST");
  const canSubmitOnBehalf = can("ATTENDANCE.REGULARIZATION_REQUEST_ON_BEHALF");

  const [view, setView] = useState<ViewMode>(canApprove ? "TEAM" : "MINE");
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [dateFrom, setDateFrom] = useState(addDays(today, -30));
  const [dateTo, setDateTo] = useState(today);
  const [statusFilter, setStatusFilter] = useState<RegularizationStatus | "">("");
  const [typeFilter, setTypeFilter] = useState<RegularizationType | "">("");
  const [employeeFilter, setEmployeeFilter] = useState("");

  const [requests, setRequests] = useState<RegularizationRequest[] | null>(null);
  const [employees, setEmployees] = useState<EmployeeOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);

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
      if (statusFilter) params.set("request_status", statusFilter);
      if (typeFilter) params.set("request_type", typeFilter);
      if (view === "MINE" && user?.employee_id) params.set("employee_id", user.employee_id);
      if (view === "TEAM" && employeeFilter) params.set("employee_id", employeeFilter);
      const data = await apiClient.get<RegularizationRequest[]>(
        `/regularizations?${params.toString()}`,
      );
      setRequests(data);
    } catch (err) {
      setRequests(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [dateFrom, dateTo, statusFilter, typeFilter, view, employeeFilter, user?.employee_id]);

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

  function onCreated(_request: RegularizationRequest) {
    void load();
  }

  const canCreate = view === "MINE" ? canSubmitSelf : canSubmitOnBehalf;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Regularizations"
        description="Employee, manager, and HR corrections to attendance — request, review, and approve."
        actions={
          canCreate ? (
            <Button type="button" onClick={() => setDialogOpen(true)}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              New request
            </Button>
          ) : undefined
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div
          role="group"
          aria-label="Regularization scope"
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
            My requests
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
              Team requests
            </button>
          ) : null}
        </div>
      </div>

      <TableContainer>
        <TableToolbar className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <FormField id="regularizations-date-from" label="From">
            <Input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)} />
          </FormField>
          <FormField id="regularizations-date-to" label="To">
            <Input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)} />
          </FormField>
          <FormField id="regularizations-status" label="Status">
            <NativeSelect
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as RegularizationStatus | "")}
            >
              <option value="">All statuses</option>
              {REGULARIZATION_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          <FormField id="regularizations-type" label="Type">
            <NativeSelect
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as RegularizationType | "")}
            >
              <option value="">All types</option>
              {REGULARIZATION_TYPES.map((type) => (
                <option key={type} value={type}>
                  {REGULARIZATION_TYPE_LABELS[type]}
                </option>
              ))}
            </NativeSelect>
          </FormField>
          {view === "TEAM" ? (
            <FormField
              id="regularizations-employee"
              label="Employee"
              className="sm:col-span-2"
            >
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

        {loading ? <LoadingState label="Loading regularization requests…" /> : null}
        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view these requests."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </div>
        ) : null}
        {!loading && !error && requests && requests.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={FileClock}
              title="No regularization requests in this range."
              description={
                canCreate
                  ? "Raise a request to correct a missing or incorrect punch."
                  : "Nothing to review right now."
              }
              action={
                canCreate ? (
                  <Button type="button" onClick={() => setDialogOpen(true)}>
                    New request
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : null}
        {!loading && !error && requests && requests.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Date</TableHead>
                <TableHead>Employee</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Stage</TableHead>
                <TableHead align="right">Detail</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {requests.map((request) => (
                <TableRow key={request.id}>
                  <TableCell className="tabular-nums text-foreground-secondary">
                    <CompanyDate value={request.attendance_date} />
                  </TableCell>
                  <TableCell>
                    <EmployeeIdentityCell
                      name={employeeDisplayName(
                        employeeById.get(request.employee_id),
                        request.employee_id,
                      )}
                      size="sm"
                    />
                  </TableCell>
                  <TableCell className="text-foreground-secondary">
                    {REGULARIZATION_TYPE_LABELS[request.request_type]}
                  </TableCell>
                  <TableCell>
                    <RegularizationStatusBadge status={request.status} />
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    {request.approval_stage ?? "—"}
                  </TableCell>
                  <TableCell align="right">
                    <Link
                      href={`/app/regularizations/${request.id}`}
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

      <RegularizationRequestDialog
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
