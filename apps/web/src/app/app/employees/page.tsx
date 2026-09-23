"use client";

import { Users } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmployeeForm } from "@/components/employee/employee-form";
import { EmployeeStatusBadge } from "@/components/employee/employee-status-badge";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PaginationControls } from "@/components/common/pagination-controls";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
  return employee.display_name?.trim() || [employee.first_name, employee.last_name].filter(Boolean).join(" ");
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
      if (err instanceof ApiError && err.status === 409 && err.code === "EMPLOYEE_SEAT_LIMIT_EXCEEDED") {
        toast({
          title: "Could not add employee",
          description: "Your plan's employee seat limit has been reached.",
          variant: "danger",
        });
        return;
      }
      toast({ title: "Could not add employee", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  const canCreate = can("EMPLOYEE.CREATE");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Employees"
        description="Everyone in your organisation, from pre-joining through exit."
        actions={
          employees && (pagination?.total ?? employees.length) > 0 && canCreate ? (
            <Button type="button" onClick={openCreate}>
              Add Employee
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading employees…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view the employee directory."
                  : error.message
              }
              onRetry={() => void loadEmployees(page)}
            />
          ) : null}

          {!loading && !error && employees && employees.length === 0 ? (
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
          ) : null}

          {!loading && !error && employees && employees.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    <th className="py-2 pr-4">Employee</th>
                    <th className="py-2 pr-4">Code</th>
                    <th className="py-2 pr-4">Personal email</th>
                    <th className="py-2 pr-4">Personal mobile</th>
                    <th className="py-2 pr-4">Status</th>
                    <th className="py-2 pr-0">State</th>
                  </tr>
                </thead>
                <tbody>
                  {employees.map((employee) => (
                    <tr key={employee.id} className="border-b border-border last:border-0">
                      <td className="py-0">
                        <Link
                          href={`/app/employees/${employee.id}`}
                          className="block rounded-md px-0 py-3 pr-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          <span className="font-medium text-foreground">{employeeName(employee) || "—"}</span>
                        </Link>
                      </td>
                      <td className="py-3 pr-4 text-foreground-secondary">{employee.employee_code}</td>
                      <td className="py-3 pr-4 text-foreground-secondary">{employee.personal_email ?? "—"}</td>
                      <td className="py-3 pr-4 text-foreground-secondary">{employee.personal_mobile ?? "—"}</td>
                      <td className="py-3 pr-4">
                        <EmployeeStatusBadge status={employee.status} />
                      </td>
                      <td className="py-3 pr-0">
                        <Badge variant={employee.is_active ? "secondary" : "outline"}>
                          {employee.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}

          {!loading && !error && pagination ? (
            <PaginationControls pagination={pagination} onPageChange={setPage} disabled={loading} />
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Employee</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <EmployeeForm values={formValues} errors={formErrors} onChange={setFormValues} idPrefix="create-" />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
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
