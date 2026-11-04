"use client";

import { Network, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { DepartmentForm } from "@/components/department/department-form";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
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
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableRowAction,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { useEmployeeDirectory } from "@/lib/employee/use-employee-directory";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import {
  EMPTY_DEPARTMENT_FORM_VALUES,
  buildCreatePayload,
  validateDepartmentForm,
  type DepartmentFormErrors,
  type DepartmentFormValues,
} from "@/lib/department/validate-department";
import type { Employee } from "@/lib/employee/types";

export default function DepartmentsPage() {
  const { toast } = useToast();
  const [departments, setDepartments] = useState<Department[] | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const directory = useEmployeeDirectory({ enabled: createOpen });
  const [formValues, setFormValues] = useState<DepartmentFormValues>(
    EMPTY_DEPARTMENT_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<DepartmentFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadDepartments = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [departmentData, branchData] = await Promise.all([
        apiClient.get<Department[]>("/departments"),
        apiClient.get<Branch[]>("/branches"),
      ]);
      setDepartments(departmentData);
      setBranches(branchData);
    } catch (err) {
      setDepartments(null);
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
    void loadDepartments();
  }, [loadDepartments]);

  function branchName(branchId: string | null): string | null {
    if (!branchId) return null;
    return branches.find((branch) => branch.id === branchId)?.name ?? "Unknown branch";
  }

  function parentName(parentId: string | null): string | null {
    if (!parentId) return null;
    return (
      departments?.find((department) => department.id === parentId)?.name ?? "Unknown department"
    );
  }

  function openCreate() {
    setFormValues(EMPTY_DEPARTMENT_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateDepartmentForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<Department>("/departments", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({ title: "Department added", variant: "success" });
      await loadDepartments();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          name: getFieldError(err.details, "name"),
          branchId: getFieldError(err.details, "branch_id"),
          parentId: getFieldError(err.details, "parent_id"),
          headEmployeeId: getFieldError(err.details, "head_employee_id"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add departments", variant: "danger" });
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        toast({
          title: "Could not add department",
          description: describeApiError(err),
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not add department",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Departments"
        description="Organisational units under your branches — Company → Branch → Department."
        actions={
          departments && departments.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Department
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading departments…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view departments."
                  : error.message
              }
              onRetry={() => void loadDepartments()}
            />
          </div>
        ) : null}

        {!loading && !error && departments && departments.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Network}
              title="No departments have been configured yet."
              description="Add the organisational units your employees will belong to. A department can optionally sit under a branch and under a parent department."
              action={
                <Button type="button" onClick={openCreate}>
                  Add Department
                </Button>
              }
            />
          </div>
        ) : null}

        {!loading && !error && departments && departments.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Department</TableHead>
                <TableHead>Branch / Parent</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {departments.map((department) => (
                <TableRow key={department.id}>
                  <TableCell>
                    <Link
                      href={`/app/departments/${department.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {department.name}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    {[branchName(department.branch_id), parentName(department.parent_id)]
                      .filter(Boolean)
                      .join(" · ") || "No branch · Top-level"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={department.is_active ? "secondary" : "outline"}>
                      {department.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <TableRowAction href={`/app/departments/${department.id}`}>View</TableRowAction>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Department</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <DepartmentForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              branches={branches}
              departments={departments ?? []}
              directory={directory}
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
              {saving ? "Adding…" : "Add department"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
