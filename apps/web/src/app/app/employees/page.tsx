"use client";

import { Search, UserPlus, Users, X } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmployeeForm } from "@/components/employee/employee-form";
import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { EmployeeStatusBadge } from "@/components/employee/employee-status-badge";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
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
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Employee } from "@/lib/employee/types";
import {
  EMPTY_EMPLOYEE_FORM_VALUES,
  buildCreatePayload,
  validateEmployeeForm,
  type EmployeeFormErrors,
  type EmployeeFormValues,
} from "@/lib/employee/validate-employee";

function employeeName(employee: Employee): string {
  return (
    employee.display_name?.trim() ||
    [employee.first_name, employee.last_name].filter(Boolean).join(" ")
  );
}

export default function EmployeesPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const router = useRouter();
  const [employees, setEmployees] = useState<Employee[] | null>(null);
  const [pagination, setPagination] = useState<PaginationMeta | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [stateFilter, setStateFilter] = useState<"" | "ACTIVE" | "INACTIVE">("");

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<EmployeeFormValues>(EMPTY_EMPLOYEE_FORM_VALUES);
  const [formErrors, setFormErrors] = useState<EmployeeFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadEmployees = useCallback(async (targetPage: number) => {
    setLoading(true);
    setError(null);
    try {
      // GET /v1/employees is paginated (API-01) — data-scope-filtered, then paged server-side.
      const { data, pagination: meta } = await apiClient.getList<Employee>("/employees", {
        page: targetPage,
      });
      setEmployees(data);
      setPagination(meta);
    } catch (err) {
      setEmployees(null);
      setPagination(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadEmployees(page);
  }, [loadEmployees, page]);

  const availableStatuses = useMemo(() => {
    if (!employees) return [];
    return Array.from(new Set(employees.map((e) => e.status).filter(Boolean))).sort();
  }, [employees]);

  const filteredEmployees = useMemo(() => {
    if (!employees) return null;
    const q = searchQuery.trim().toLowerCase();
    return employees.filter((employee) => {
      if (statusFilter && employee.status !== statusFilter) return false;
      if (stateFilter === "ACTIVE" && !employee.is_active) return false;
      if (stateFilter === "INACTIVE" && employee.is_active) return false;
      if (!q) return true;
      const name = employeeName(employee).toLowerCase();
      const code = (employee.employee_code ?? "").toLowerCase();
      const email = (employee.personal_email ?? "").toLowerCase();
      const mobile = (employee.personal_mobile ?? "").toLowerCase();
      return name.includes(q) || code.includes(q) || email.includes(q) || mobile.includes(q);
    });
  }, [employees, searchQuery, statusFilter, stateFilter]);

  const hasFilters = Boolean(searchQuery.trim() || statusFilter || stateFilter);

  function resetFilters() {
    setSearchQuery("");
    setStatusFilter("");
    setStateFilter("");
  }

  function openCreate() {
    setFormValues(EMPTY_EMPLOYEE_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateEmployeeForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      const created = await apiClient.post<Employee>("/employees", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({
        title: "Employee added",
        description: `Employee code ${created.employee_code} has been generated.`,
        variant: "success",
      });
      router.push(`/app/employees/${created.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          firstName: getFieldError(err.details, "first_name"),
          personalEmail: getFieldError(err.details, "personal_email"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add employees", variant: "danger" });
        return;
      }
      if (
        err instanceof ApiError &&
        err.status === 409 &&
        err.code === "EMPLOYEE_SEAT_LIMIT_EXCEEDED"
      ) {
        toast({
          title: "Could not add employee",
          description: "Your plan's employee seat limit has been reached.",
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not add employee",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  const canCreate = can("EMPLOYEE.CREATE");
  const totalCount = pagination?.total ?? employees?.length ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Employees"
        description="Everyone in your organisation, from pre-joining through exit."
        badge={
          !loading && !error && employees ? (
            <Badge variant="secondary" className="tabular-nums">
              {totalCount} {totalCount === 1 ? "record" : "records"}
            </Badge>
          ) : undefined
        }
        actions={
          employees && totalCount > 0 && canCreate ? (
            <Button type="button" onClick={openCreate}>
              <UserPlus className="h-4 w-4" aria-hidden="true" />
              Add Employee
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {!loading && !error && employees && employees.length > 0 ? (
          <TableToolbar>
            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
              <div className="relative w-full sm:w-64">
                <Search
                  className="pointer-events-none absolute left-2.5 top-2.5 h-4 w-4 text-foreground-muted"
                  aria-hidden="true"
                />
                <Input
                  type="search"
                  aria-label="Filter current page"
                  placeholder="Filter current page…"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-8"
                />
              </div>
              {pagination && pagination.total_pages > 1 ? (
                <span className="text-xs text-foreground-muted">
                  Filtering page {pagination.page} of {pagination.total_pages}
                </span>
              ) : null}
            </div>

            <div className="flex w-full flex-wrap items-center gap-2 sm:w-auto">
              {availableStatuses.length > 1 ? (
                <NativeSelect
                  aria-label="Filter by employment status"
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  className="flex-1 sm:w-40 sm:flex-none"
                >
                  <option value="">All statuses</option>
                  {availableStatuses.map((status) => (
                    <option key={status} value={status}>
                      {status.replaceAll("_", " ")}
                    </option>
                  ))}
                </NativeSelect>
              ) : null}

              <NativeSelect
                aria-label="Filter by record state"
                value={stateFilter}
                onChange={(e) => setStateFilter(e.target.value as "" | "ACTIVE" | "INACTIVE")}
                className="flex-1 sm:w-36 sm:flex-none"
              >
                <option value="">All states</option>
                <option value="ACTIVE">Active only</option>
                <option value="INACTIVE">Inactive only</option>
              </NativeSelect>

              {hasFilters ? (
                <Button type="button" variant="ghost" size="sm" onClick={resetFilters}>
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                  Clear
                </Button>
              ) : null}
            </div>
          </TableToolbar>
        ) : null}

        {loading ? <LoadingState label="Loading employees…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view the employee directory."
                  : error.message
              }
              onRetry={() => void loadEmployees(page)}
            />
          </div>
        ) : null}

        {!loading && !error && employees && employees.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Users}
              title="No employees yet."
              description="Add your first employee to start building the directory. Employment, assignment, compensation, statutory, and banking details are added afterwards from the employee's own page."
              action={
                canCreate ? (
                  <Button type="button" onClick={openCreate}>
                    Add Employee
                  </Button>
                ) : undefined
              }
            />
          </div>
        ) : null}

        {!loading && !error && employees && employees.length > 0 && filteredEmployees ? (
          filteredEmployees.length === 0 ? (
            <div className="p-6">
              <EmptyState
                icon={Search}
                title="No employees match your filter."
                description="Try clearing the search query or status filter."
                action={
                  <Button type="button" variant="outline" size="sm" onClick={resetFilters}>
                    Reset filters
                  </Button>
                }
              />
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Employee</TableHead>
                  <TableHead className="hidden sm:table-cell">Code</TableHead>
                  <TableHead className="hidden md:table-cell">Personal email</TableHead>
                  <TableHead className="hidden lg:table-cell">Personal mobile</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="hidden sm:table-cell">State</TableHead>
                  <TableHead align="right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredEmployees.map((employee) => (
                  <TableRow key={employee.id}>
                    <TableCell>
                      <EmployeeIdentityCell
                        name={employeeName(employee) || "—"}
                        subtitle={
                          <span className="md:hidden">
                            {employee.employee_code}
                            {employee.personal_email ? ` · ${employee.personal_email}` : ""}
                          </span>
                        }
                        href={`/app/employees/${employee.id}`}
                      />
                    </TableCell>
                    <TableCell className="hidden font-mono text-xs text-foreground-secondary sm:table-cell">
                      {employee.employee_code}
                    </TableCell>
                    <TableCell className="hidden text-foreground-secondary md:table-cell">
                      {employee.personal_email ?? "—"}
                    </TableCell>
                    <TableCell className="hidden tabular-nums text-foreground-secondary lg:table-cell">
                      {employee.personal_mobile ?? "—"}
                    </TableCell>
                    <TableCell>
                      <EmployeeStatusBadge status={employee.status} />
                    </TableCell>
                    <TableCell className="hidden sm:table-cell">
                      <Badge variant={employee.is_active ? "secondary" : "outline"}>
                        {employee.is_active ? "Active" : "Inactive"}
                      </Badge>
                    </TableCell>
                    <TableCell align="right">
                      <Link
                        href={`/app/employees/${employee.id}`}
                        className="text-xs font-medium text-primary hover:underline"
                      >
                        View
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )
        ) : null}

        {!loading && !error && pagination ? (
          <PaginationControls
            pagination={pagination}
            onPageChange={setPage}
            disabled={loading}
          />
        ) : null}
      </TableContainer>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Employee</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <EmployeeForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              idPrefix="create-"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Adding…" : "Add employee"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
