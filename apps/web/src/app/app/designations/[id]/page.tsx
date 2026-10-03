"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { DesignationForm } from "@/components/designation/designation-form";
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
import { ApiError, describeApiError, describeLifecycleError, getFieldError } from "@/lib/api/errors";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import {
  buildUpdatePatch,
  designationToFormValues,
  validateDesignationForm,
  type DesignationFormErrors,
  type DesignationFormValues,
} from "@/lib/designation/validate-designation";
import type { Grade } from "@/lib/grade/types";

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

export default function DesignationDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();

  const [designation, setDesignation] = useState<Designation | null>(null);
  const [departments, setDepartments] = useState<Department[]>([]);
  const [grades, setGrades] = useState<Grade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<DesignationFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<DesignationFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const loadDesignation = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, departmentData, gradeData] = await Promise.all([
        apiClient.get<Designation>(`/designations/${params.id}`),
        apiClient.get<Department[]>("/departments"),
        apiClient.get<Grade[]>("/grades"),
      ]);
      setDesignation(data);
      setDepartments(departmentData);
      setGrades(gradeData);
      return data;
    } catch (err) {
      setDesignation(null);
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
    void loadDesignation();
  }, [loadDesignation]);

  function departmentName(departmentId: string | null): string | null {
    if (!departmentId) return null;
    return departments.find((d) => d.id === departmentId)?.name ?? "Unknown department";
  }

  function gradeName(gradeId: string | null): string | null {
    if (!gradeId) return null;
    return grades.find((g) => g.id === gradeId)?.name ?? "Unknown grade";
  }

  function startEditing() {
    if (!designation) return;
    setFormValues(designationToFormValues(designation));
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
    if (!designation || !formValues) return;

    const clientErrors = validateDesignationForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    const patch = buildUpdatePatch(formValues, designation);
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
      const updated = await apiClient.patch<Designation>(`/designations/${designation.id}`, patch, {
        ifMatch: String(designation.version),
      });
      setDesignation(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Designation saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This designation was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({
            title: getFieldError(err.details, "title"),
            departmentId: getFieldError(err.details, "department_id"),
            gradeId: getFieldError(err.details, "grade_id"),
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
        title: "Could not save designation",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await loadDesignation();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Designation reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!designation) return;
    setStatusChanging(true);
    try {
      if (designation.is_active) {
        const updated = await apiClient.delete<Designation>(`/designations/${designation.id}`, {
          ifMatch: String(designation.version),
        });
        setDesignation(updated);
        toast({ title: "Designation deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<Designation>(
          `/designations/${designation.id}`,
          { is_active: true },
          { ifMatch: String(designation.version) },
        );
        setDesignation(updated);
        toast({ title: "Designation reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      toast({
        title: "Could not update designation status",
        description: describeLifecycleError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/app/designations" className="text-sm text-foreground-secondary hover:underline">
          ← Designations
        </Link>
      </div>

      <PageHeader
        title={designation?.title ?? "Designation"}
        description="Department, grade, and identity details for this designation."
        actions={
          designation && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {designation.is_active ? "Deactivate" : "Reactivate"}
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
          {loading ? <LoadingState label="Loading designation…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this designation."
                  : error.status === 404
                    ? "This designation could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void loadDesignation()}
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

          {!loading && !error && designation && editing && formValues ? (
            <div className="space-y-6">
              <DesignationForm
                values={formValues}
                errors={formErrors}
                onChange={setFormValues}
                departments={departments}
                grades={grades}
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

          {!loading && !error && designation && !editing ? (
            <div className="space-y-8">
              <div>
                <Badge variant={designation.is_active ? "secondary" : "outline"}>
                  {designation.is_active ? "Active" : "Inactive"}
                </Badge>
              </div>
              <section>
                <h3 className="text-sm font-medium text-foreground">Identity</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Designation title" value={designation.title} />
                  <DetailField label="Designation code" value={designation.code} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Department &amp; grade</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Department" value={departmentName(designation.department_id)} />
                  <DetailField label="Grade" value={gradeName(designation.grade_id)} />
                </dl>
              </section>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{designation?.is_active ? "Deactivate designation?" : "Reactivate designation?"}</DialogTitle>
            <DialogDescription>
              {designation?.is_active
                ? "This designation will no longer be available for new activity. You can reactivate it later."
                : "This designation will become available for use again."}
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
              variant={designation?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : designation?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
