"use client";

import { Download, Search, UserPlus, Users, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { DirectorySummaryCards } from "@/components/employee/directory-summary";
import { EmployeeForm } from "@/components/employee/employee-form";
import { EmployeeIdentityCell } from "@/components/employee/employee-identity";
import { EmployeeStatusBadge } from "@/components/employee/employee-status-badge";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { BusyRegion } from "@/components/common/busy-region";
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
  TableCellStack,
  TableContainer,
  TableHead,
  TableEmpty,
  TableHeader,
  TableRow,
  TableRowAction,
  TableToolbar,
} from "@/components/ui/table";
import { Skeleton, TableSkeleton } from "@/components/ui/skeleton";
import { isAbortError, useLatestRequest } from "@/hooks/use-latest-request";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  directoryRowsPath,
  employeesToCsv,
  type DirectoryRow,
  type DirectorySummary,
} from "@/lib/employee/directory";
import { employeeFullName } from "@/lib/employee/names";
import type { Employee } from "@/lib/employee/types";
import {
  EMPTY_EMPLOYEE_FORM_VALUES,
  buildCreatePayload,
  validateEmployeeForm,
  type EmployeeFormErrors,
  type EmployeeFormValues,
} from "@/lib/employee/validate-employee";

function employeeName(employee: Employee): string {
  return employeeFullName(employee);
}

/** Stands in for a directory detail (designation, department…) that is still being fetched. */
function DetailPlaceholder() {
  return <Skeleton className="h-4 w-20" aria-hidden="true" />;
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

  // The top-bar search links here as `?q=<text>`, so start from it.
  const [searchQuery, setSearchQuery] = useState(() =>
    typeof window === "undefined" ? "" : (new URLSearchParams(window.location.search).get("q") ?? ""),
  );
  const [statusFilter, setStatusFilter] = useState("");
  const [stateFilter, setStateFilter] = useState<"" | "ACTIVE" | "INACTIVE">("");

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<EmployeeFormValues>(EMPTY_EMPLOYEE_FORM_VALUES);
  const [formErrors, setFormErrors] = useState<EmployeeFormErrors>({});
  const [saving, setSaving] = useState(false);

  const beginRequest = useLatestRequest();

  // The text search runs on the server so it spans every page, not just the one on screen. Typing
  // is debounced so one request goes out per pause, not per keystroke.
  const [serverQuery, setServerQuery] = useState(() => searchQuery.trim());
  useEffect(() => {
    const next = searchQuery.trim();
    if (next === serverQuery) return;
    const timer = window.setTimeout(() => {
      setServerQuery(next);
      setPage(1);
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchQuery, serverQuery]);

  const loadEmployees = useCallback(async (targetPage: number, query: string) => {
    const request = beginRequest();
    setLoading(true);
    setError(null);
    try {
      // GET /v1/employees is paginated (API-01) — data-scope-filtered, then paged server-side.
      const { data, pagination: meta } = await apiClient.getList<Employee>(
        "/employees",
        query ? { page: targetPage, q: query } : { page: targetPage },
        { signal: request.signal },
      );
      if (!request.isCurrent()) return;
      setEmployees(data);
      setPagination(meta);
    } catch (err) {
      // Superseded by a newer request (or unmounted): that one owns the state now.
      if (isAbortError(err) || !request.isCurrent()) return;
      setEmployees(null);
      setPagination(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      if (request.isCurrent()) setLoading(false);
    }
  }, [beginRequest]);

  useEffect(() => {
    void loadEmployees(page, serverQuery);
  }, [loadEmployees, page, serverQuery]);

  // Headline counts, and designation / department / manager / shift for the rows on this page.
  const [summary, setSummary] = useState<DirectorySummary | null>(null);
  const [details, setDetails] = useState<Map<string, DirectoryRow>>(new Map());
  useEffect(() => {
    let cancelled = false;
    apiClient
      .get<DirectorySummary>("/employees/directory/summary")
      .then((d) => !cancelled && setSummary(d))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);
  const pageIds = useMemo(() => (employees ?? []).map((e) => e.id), [employees]);
  // Which page of rows `details` belongs to, so the cells can show a placeholder — not a "—" that
  // looks like missing data — until this page's details have arrived (or failed to).
  const pageKey = useMemo(() => pageIds.join(","), [pageIds]);
  const [detailsFor, setDetailsFor] = useState("");
  const detailsReady = pageIds.length === 0 || detailsFor === pageKey;
  useEffect(() => {
    if (pageIds.length === 0) return;
    let cancelled = false;
    apiClient
      .get<DirectoryRow[]>(directoryRowsPath(pageIds))
      .then((rows) => {
        if (cancelled) return;
        setDetails(new Map(rows.map((r) => [r.employee_id, r])));
        setDetailsFor(pageKey);
      })
      .catch(() => {
        if (cancelled) return;
        setDetails(new Map());
        setDetailsFor(pageKey);
      });
    return () => {
      cancelled = true;
    };
  }, [pageIds, pageKey]);

  // A new `employees` array (next page, new search) or a changed filter means different rows: count
  // those so the table can fade in fresh instead of snapping (adjusting state during render).
  const [seenEmployees, setSeenEmployees] = useState(employees);
  const [rowsGeneration, setRowsGeneration] = useState(0);
  if (seenEmployees !== employees) {
    setSeenEmployees(employees);
    setRowsGeneration((g) => g + 1);
  }

  const availableStatuses = useMemo(() => {
    if (!employees) return [];
    return Array.from(new Set(employees.map((e) => e.status).filter(Boolean))).sort();
  }, [employees]);

  // Text search is done by the server (it spans every page); only the status dropdowns filter here,
  // and those apply to the rows on the current page.
  const filteredEmployees = useMemo(() => {
    if (!employees) return null;
    return employees.filter((employee) => {
      if (statusFilter && employee.status !== statusFilter) return false;
      if (stateFilter === "ACTIVE" && !employee.is_active) return false;
      if (stateFilter === "INACTIVE" && employee.is_active) return false;
      return true;
    });
  }, [employees, statusFilter, stateFilter]);

  function exportCsv() {
    const csv = employeesToCsv(
      (filteredEmployees ?? []).map((e) => {
        const d = details.get(e.id);
        return {
          code: e.employee_code,
          name: employeeName(e),
          email: e.personal_email,
          mobile: e.personal_mobile,
          status: e.status,
          designation: d?.designation ?? null,
          department: d?.department ?? null,
          manager: d?.manager_name ?? null,
          shift: d?.shift_name ?? null,
        };
      }),
    );
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = "employees.csv";
    a.click();
    URL.revokeObjectURL(url);
  }

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
          !error && employees ? (
            <Badge variant="secondary" className="tabular-nums">
              {totalCount} {totalCount === 1 ? "record" : "records"}
            </Badge>
          ) : undefined
        }
        actions={
          employees && totalCount > 0 ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={exportCsv}>
                <Download className="h-4 w-4" aria-hidden="true" />
                Export CSV
              </Button>
              {canCreate ? (
                <Button type="button" onClick={openCreate}>
                  <UserPlus className="h-4 w-4" aria-hidden="true" />
                  Add Employee
                </Button>
              ) : null}
            </div>
          ) : null
        }
      />

      <DirectorySummaryCards summary={summary} />

      <TableContainer>
        {!error && employees && employees.length > 0 ? (
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
                  Page {pagination.page} of {pagination.total_pages}
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
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  onClick={resetFilters}
                  className="animate-in fade-in-0 zoom-in-95 duration-motion-fast"
                >
                  <X className="h-3.5 w-3.5" aria-hidden="true" />
                  Clear
                </Button>
              ) : null}
            </div>
          </TableToolbar>
        ) : null}

        {loading && employees === null ? (
          <div role="status" aria-label="Loading employees">
            <TableSkeleton rows={8} columns={7} />
            <span className="sr-only">Loading employees…</span>
          </div>
        ) : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view the employee directory."
                  : error.message
              }
              onRetry={() => void loadEmployees(page, serverQuery)}
            />
          </div>
        ) : null}

        {!error && employees && employees.length === 0 ? (
          <div className="animate-in fade-in-0 p-6 duration-motion-slow">
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

        {!error && employees && employees.length > 0 && filteredEmployees ? (
          filteredEmployees.length === 0 ? (
            <div className="animate-in fade-in-0 p-6 duration-motion-slow">
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
            <BusyRegion busy={loading} label="Refreshing employees…">
            <div
              key={`${rowsGeneration}-${statusFilter}-${stateFilter}`}
              className="animate-in fade-in-0 duration-motion-base"
            >
            <Table>
              <TableHeader>
                <TableRow className="hover:bg-transparent">
                  <TableHead>Employee</TableHead>
                  <TableHead className="hidden md:table-cell">Role</TableHead>
                  <TableHead className="hidden lg:table-cell">Reporting manager</TableHead>
                  <TableHead className="hidden lg:table-cell">Shift</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead className="hidden sm:table-cell">State</TableHead>
                  <TableHead align="right">
                    <span className="sr-only">Actions</span>
                  </TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredEmployees.map((employee) => {
                  const detail = details.get(employee.id);
                  return (
                    <TableRow key={employee.id}>
                      <TableCell>
                        <EmployeeIdentityCell
                          name={employeeName(employee) || "—"}
                          code={employee.employee_code}
                          href={`/app/employees/${employee.id}`}
                        />
                      </TableCell>
                      <TableCell className="hidden md:table-cell">
                        {detailsReady ? (
                          <TableCellStack
                            primary={detail?.designation ?? <TableEmpty label="No designation" />}
                            secondary={detail?.department}
                          />
                        ) : (
                          <DetailPlaceholder />
                        )}
                      </TableCell>
                      <TableCell nowrap className="hidden text-foreground-secondary lg:table-cell">
                        {!detailsReady ? (
                          <DetailPlaceholder />
                        ) : (
                          (detail?.manager_name ?? <TableEmpty label="No reporting manager" />)
                        )}
                      </TableCell>
                      <TableCell nowrap className="hidden text-foreground-secondary lg:table-cell">
                        {!detailsReady ? (
                          <DetailPlaceholder />
                        ) : (
                          (detail?.shift_name ?? <TableEmpty label="No shift" />)
                        )}
                      </TableCell>
                      <TableCell nowrap>
                        <EmployeeStatusBadge status={employee.status} />
                      </TableCell>
                      <TableCell nowrap className="hidden sm:table-cell">
                        <Badge variant={employee.is_active ? "secondary" : "outline"}>
                          {employee.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </TableCell>
                      <TableCell align="right" nowrap>
                        <TableRowAction href={`/app/employees/${employee.id}`} />
                      </TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
            </div>
            </BusyRegion>
          )
        ) : null}

        {!error && pagination ? (
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
