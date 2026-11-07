"use client";

import { useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { RecordFormFields } from "@/components/employee/record-form-fields";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApiResource } from "@/hooks/use-api-resource";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  UPDATE_SENSITIVE,
  buildCreatePayload,
  emptyValues,
  formatRecordValue,
  validateRecord,
  type ListSectionConfig,
  type RecordFormValues,
  type RecordRow,
} from "@/lib/employee/record-sections";

interface RecordListPanelProps {
  employeeId: string;
  section: ListSectionConfig;
}

/** One list section of the employee record (experience, education, dependents) — mirrors the
 * mobile app's section: the rows as cards, "Add …" and a per-row Delete for holders of
 * EMPLOYEE.UPDATE_SENSITIVE. Deletes send the row's version as If-Match. */
export function RecordListPanel({ employeeId, section }: RecordListPanelProps) {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canUpdate = can(UPDATE_SENSITIVE);
  const base = `/employees/${employeeId}${section.path}`;
  const { data, loading, error, notImplemented, retry } = useApiResource<RecordRow[]>(`${base}?per_page=100`);

  const [addOpen, setAddOpen] = useState(false);
  const [values, setValues] = useState<RecordFormValues>(() => emptyValues(section.form));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState<RecordRow | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);

  function openAdd() {
    setValues(emptyValues(section.form));
    setErrors({});
    setAddOpen(true);
  }

  async function handleAdd() {
    const clientErrors = validateRecord(section.form, values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }
    setSaving(true);
    setErrors({});
    try {
      await apiClient.post(base, buildCreatePayload(section.form, values));
      setAddOpen(false);
      toast({ title: section.savedToast, variant: "success" });
      retry();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        const fieldErrors: Record<string, string> = {};
        for (const f of section.form) {
          const message = getFieldError(err.details, f.key);
          if (message) fieldErrors[f.key] = message;
        }
        if (Object.keys(fieldErrors).length > 0) {
          setErrors(fieldErrors);
          return;
        }
      }
      if (err instanceof ApiError && err.status === 403) {
        setAddOpen(false);
        toast({ title: "You don't have permission to do that", variant: "danger" });
        return;
      }
      toast({ title: `Could not save`, description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete() {
    if (!deleting) return;
    setDeleteBusy(true);
    try {
      await apiClient.delete(`${base}/${deleting.id}`, { ifMatch: String(deleting.version) });
      toast({ title: "Deleted", variant: "success" });
    } catch (err) {
      const stale = err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE";
      toast({
        title: stale ? "This entry was changed by someone else. Reloading." : "Could not delete",
        description: stale ? undefined : describeApiError(err),
        variant: "danger",
      });
    } finally {
      setDeleteBusy(false);
      setDeleting(null);
      retry();
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-md border border-info/30 bg-info-subtle p-3 text-xs text-foreground-secondary">{section.note}</div>

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label={`Loading ${section.title.toLowerCase()}…`} />
          </CardContent>
        </Card>
      ) : null}

      {!loading && (error || notImplemented) ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error?.status === 403
                  ? `You do not have permission to view this employee's ${section.title.toLowerCase()}.`
                  : (error?.message ?? "This section is not available.")
              }
              onRetry={retry}
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && data ? (
        <Card>
          <CardContent className="pt-6">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-medium text-foreground">{section.title}</h3>
              {canUpdate ? (
                <Button type="button" size="sm" onClick={openAdd}>
                  {section.addLabel}
                </Button>
              ) : null}
            </div>
            {data.length === 0 ? (
              <EmptyState className="mt-4" title={section.emptyTitle} />
            ) : (
              <ul className="mt-3 divide-y divide-border">
                {data.map((row) => (
                  <li key={String(row.id)} className="py-3 first:pt-0 last:pb-0">
                    <div className="flex items-start justify-between gap-4">
                      <p className="text-sm font-medium text-foreground">{section.cardTitle(row)}</p>
                      {canUpdate ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          aria-label={`Delete ${section.cardTitle(row)}`}
                          onClick={() => setDeleting(row)}
                        >
                          Delete
                        </Button>
                      ) : null}
                    </div>
                    <dl className="mt-2 grid grid-cols-1 gap-x-6 gap-y-1 sm:grid-cols-2">
                      {section.display.map((field) => (
                        <div key={field.key} className="flex justify-between gap-3 text-sm">
                          <dt className="text-foreground-muted">{field.label}</dt>
                          <dd className="text-right text-foreground">{formatRecordValue(field, row[field.key])}</dd>
                        </div>
                      ))}
                    </dl>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={addOpen} onOpenChange={(open) => (!saving ? setAddOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>{section.addLabel}</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <RecordFormFields fields={section.form} values={values} errors={errors} onChange={setValues} idPrefix={`${section.key}-`} />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setAddOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleAdd()} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={deleting !== null} onOpenChange={(open) => (!open && !deleteBusy ? setDeleting(null) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{section.deleteConfirm}</DialogTitle>
            <DialogDescription>{deleting ? section.cardTitle(deleting) : ""}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDeleting(null)} disabled={deleteBusy}>
              Cancel
            </Button>
            <Button type="button" variant="destructive" onClick={() => void handleDelete()} disabled={deleteBusy}>
              {deleteBusy ? "Deleting…" : "Delete"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
