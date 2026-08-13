"use client";

import { Network } from "lucide-react";
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
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import {
  EMPTY_DEPARTMENT_FORM_VALUES,
  buildCreatePayload,
  validateDepartmentForm,
  type DepartmentFormErrors,
  type DepartmentFormValues,
} from "@/lib/department/validate-department";

export default function DepartmentsPage() {
  const { toast } = useToast();
  const [departments, setDepartments] = useState<Department[] | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<DepartmentFormValues>(EMPTY_DEPARTMENT_FORM_VALUES);
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
    return departments?.find((department) => department.id === parentId)?.name ?? "Unknown department";
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
        title="Departments"
        description="Organisational units under your branches — Legal Entity → Branch → Department."
        actions={
          departments && departments.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              Add Department
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading departments…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view departments."
                  : error.message
              }
              onRetry={() => void loadDepartments()}
            />
          ) : null}

          {!loading && !error && departments && departments.length === 0 ? (
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
          ) : null}

          {!loading && !error && departments && departments.length > 0 ? (
            <ul className="divide-y divide-border">
              {departments.map((department) => (
                <li key={department.id} className="py-4 first:pt-0 last:pb-0">
                  <Link
                    href={`/app/departments/${department.id}`}
                    className="flex items-center justify-between gap-4 rounded-md px-2 py-1 -mx-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">{department.name}</p>
                      <p className="mt-0.5 text-xs text-foreground-muted">
                        {[branchName(department.branch_id), parentName(department.parent_id)]
                          .filter(Boolean)
                          .join(" · ") || "No branch · Top-level"}
                      </p>
                    </div>
                    <Badge variant={department.is_active ? "secondary" : "outline"}>
                      {department.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

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
              idPrefix="create-"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
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
