"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { DepartmentForm } from "@/components/department/department-form";
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
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import {
  buildUpdatePatch,
  departmentToFormValues,
  validateDepartmentForm,
  type DepartmentFormErrors,
  type DepartmentFormValues,
} from "@/lib/department/validate-department";

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  const display = value && value.trim() ? value : "Not configured";
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className={`mt-0.5 text-sm ${value && value.trim() ? "text-foreground" : "text-foreground-muted"}`}>
        {display}
      </dd>
    </div>
  );
}

export default function DepartmentDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();

  const [department, setDepartment] = useState<Department | null>(null);
  const [branches, setBranches] = useState<Branch[]>([]);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<DepartmentFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<DepartmentFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const loadDepartment = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, branchData, departmentData] = await Promise.all([
        apiClient.get<Department>(`/departments/${params.id}`),
        apiClient.get<Branch[]>("/branches"),
        apiClient.get<Department[]>("/departments"),
      ]);
      setDepartment(data);
      setBranches(branchData);
      setDepartments(departmentData);
      return data;
    } catch (err) {
      setDepartment(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
      return null;
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void loadDepartment();
  }, [loadDepartment]);

  function branchName(branchId: string | null): string | null {
    if (!branchId) return null;
    return branches.find((branch) => branch.id === branchId)?.name ?? "Unknown branch";
  }

  function parentName(parentId: string | null): string | null {
    if (!parentId) return null;
    return departments.find((d) => d.id === parentId)?.name ?? "Unknown department";
  }

  function startEditing() {
    if (!department) return;
    setFormValues(departmentToFormValues(department));
    setFormErrors({});
    setStaleMessage(null);
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setFormValues(null);
    setFormErrors({});
    setStaleMessage(null);
  }

  async function handleSave() {
    if (!department || !formValues) return;

    const clientErrors = validateDepartmentForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    const patch = buildUpdatePatch(formValues, department);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      setFormValues(null);
      toast({ title: "No changes to save", variant: "default" });
      return;
    }

    setSaving(true);
    setFormErrors({});
    setStaleMessage(null);
    try {
      const updated = await apiClient.patch<Department>(`/departments/${department.id}`, patch, {
        ifMatch: String(department.version),
      });
      setDepartment(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Department saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This department was changed by someone else.");
          return;
        }
        if (err.status === 409 && (err.code === "DEPARTMENT_CYCLE_DETECTED" || err.code === "DEPARTMENT_MAX_DEPTH_EXCEEDED")) {
          setFormErrors({
            parentId:
              err.code === "DEPARTMENT_CYCLE_DETECTED"
                ? "This parent department would create a cycle in the hierarchy."
                : "This parent department would exceed the maximum hierarchy depth of 5.",
          });
          return;
        }
        if (err.status === 422) {
          setFormErrors({
            name: getFieldError(err.details, "name"),
            branchId: getFieldError(err.details, "branch_id"),
            parentId: getFieldError(err.details, "parent_id"),
          });
          return;
        }
        if (err.status === 403) {
          setError(err);
          setEditing(false);
          return;
        }
      }
      toast({
        title: "Could not save department",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await loadDepartment();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Department reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!department) return;
    setStatusChanging(true);
    try {
      if (department.is_active) {
        const updated = await apiClient.delete<Department>(`/departments/${department.id}`, {
          ifMatch: String(department.version),
        });
        setDepartment(updated);
        toast({ title: "Department deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<Department>(
          `/departments/${department.id}`,
          { is_active: true },
          { ifMatch: String(department.version) },
        );
        setDepartment(updated);
        toast({ title: "Department reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      toast({
        title: "Could not update department status",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/app/departments" className="text-sm text-foreground-secondary hover:underline">
          ← Departments
        </Link>
      </div>

      <PageHeader
        title={department?.name ?? "Department"}
        description="Hierarchy and branch details for this department."
        actions={
          department && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {department.is_active ? "Deactivate" : "Reactivate"}
              </Button>
              <Button type="button" onClick={startEditing}>
                Edit
              </Button>
            </div>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading department…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this department."
                  : error.status === 404
                    ? "This department could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void loadDepartment()}
            />
          ) : null}

          {staleMessage ? (
            <div className="mb-4 rounded-md border border-warning/30 bg-warning/5 p-4" role="alert">
              <p className="text-sm font-medium text-foreground">{staleMessage}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button type="button" size="sm" onClick={() => void reloadLatest()}>
                  Reload latest
                </Button>
                <Button type="button" size="sm" variant="outline" onClick={cancelEditing}>
                  Cancel current changes
                </Button>
              </div>
            </div>
          ) : null}

          {!loading && !error && department && editing && formValues ? (
            <div className="space-y-6">
              <DepartmentForm
                values={formValues}
                errors={formErrors}
                onChange={setFormValues}
                branches={branches}
                departments={departments}
                excludeDepartmentId={department.id}
              />
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                  {saving ? "Saving…" : "Save changes"}
                </Button>
                <Button type="button" variant="outline" onClick={cancelEditing} disabled={saving}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}

          {!loading && !error && department && !editing ? (
            <div className="space-y-8">
              <div>
                <Badge variant={department.is_active ? "secondary" : "outline"}>
                  {department.is_active ? "Active" : "Inactive"}
                </Badge>
              </div>
              <section>
                <h3 className="text-sm font-medium text-foreground">Identity</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Department name" value={department.name} />
                  <DetailField label="Department code" value={department.code} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Hierarchy</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Branch" value={branchName(department.branch_id)} />
                  <DetailField label="Parent department" value={parentName(department.parent_id)} />
                </dl>
              </section>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{department?.is_active ? "Deactivate department?" : "Reactivate department?"}</DialogTitle>
            <DialogDescription>
              {department?.is_active
                ? "This department will no longer be available for new activity. You can reactivate it later."
                : "This department will become available for use again."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={statusChanging}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={department?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : department?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
