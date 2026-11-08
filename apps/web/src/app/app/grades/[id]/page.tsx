"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { GradeForm } from "@/components/grade/grade-form";
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
import type { Grade } from "@/lib/grade/types";
import {
  buildUpdatePatch,
  gradeToFormValues,
  validateGradeForm,
  type GradeFormErrors,
  type GradeFormValues,
} from "@/lib/grade/validate-grade";

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

function formatRupees(value: number | null): string | null {
  if (value === null) return null;
  return `₹${(value / 100).toLocaleString("en-IN")}`;
}

export default function GradeDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();

  const [grade, setGrade] = useState<Grade | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<GradeFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<GradeFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const loadGrade = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Grade>(`/grades/${params.id}`);
      setGrade(data);
      return data;
    } catch (err) {
      setGrade(null);
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
    void loadGrade();
  }, [loadGrade]);

  function startEditing() {
    if (!grade) return;
    setFormValues(gradeToFormValues(grade));
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
    if (!grade || !formValues) return;

    const clientErrors = validateGradeForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    const patch = buildUpdatePatch(formValues, grade);
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
      const updated = await apiClient.patch<Grade>(`/grades/${grade.id}`, patch, {
        ifMatch: String(grade.version),
      });
      setGrade(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Grade saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This grade was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({
            name: getFieldError(err.details, "name"),
            maxCtc: getFieldError(err.details, "max_ctc"),
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
        title: "Could not save grade",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await loadGrade();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Grade reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!grade) return;
    setStatusChanging(true);
    try {
      if (grade.is_active) {
        const updated = await apiClient.delete<Grade>(`/grades/${grade.id}`, {
          ifMatch: String(grade.version),
        });
        setGrade(updated);
        toast({ title: "Grade deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<Grade>(
          `/grades/${grade.id}`,
          { is_active: true },
          { ifMatch: String(grade.version) },
        );
        setGrade(updated);
        toast({ title: "Grade reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      toast({
        title: "Could not update grade status",
        description: describeLifecycleError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/grades"
        backLabel="Grades"
        title={grade?.name ?? "Grade"}
        description="Compensation band and override details for this grade."
        actions={
          grade && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {grade.is_active ? "Deactivate" : "Reactivate"}
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
          {loading ? <LoadingState label="Loading grade…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this grade."
                  : error.status === 404
                    ? "This grade could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void loadGrade()}
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

          {!loading && !error && grade && editing && formValues ? (
            <div className="space-y-6">
              <GradeForm values={formValues} errors={formErrors} onChange={setFormValues} />
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

          {!loading && !error && grade && !editing ? (
            <div className="space-y-8">
              <div>
                <Badge variant={grade.is_active ? "secondary" : "outline"}>
                  {grade.is_active ? "Active" : "Inactive"}
                </Badge>
              </div>
              <section>
                <h3 className="text-sm font-medium text-foreground">Identity</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Grade code" value={grade.code} />
                  <DetailField label="Grade name" value={grade.name} />
                  <DetailField label="Level" value={grade.level === null ? null : String(grade.level)} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Compensation band</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Min CTC" value={formatRupees(grade.min_ctc)} />
                  <DetailField label="Max CTC" value={formatRupees(grade.max_ctc)} />
                  <DetailField label="Approval limit" value={formatRupees(grade.approval_limit)} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Overrides</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField
                    label="Notice period"
                    value={grade.notice_period_days === null ? null : `${grade.notice_period_days} days`}
                  />
                  <DetailField
                    label="Probation"
                    value={grade.probation_days === null ? null : `${grade.probation_days} days`}
                  />
                </dl>
              </section>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{grade?.is_active ? "Deactivate grade?" : "Reactivate grade?"}</DialogTitle>
            <DialogDescription>
              {grade?.is_active
                ? "This grade will no longer be available for new activity. You can reactivate it later."
                : "This grade will become available for use again."}
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
              variant={grade?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : grade?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
