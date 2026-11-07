"use client";

import { useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { useToast } from "@/components/common/toast";
import { ConcurrencyConflictBanner } from "@/components/employee/concurrency-conflict-banner";
import { RecordFormFields } from "@/components/employee/record-form-fields";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApiResource } from "@/hooks/use-api-resource";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  IDENTITY_DISPLAY,
  IDENTITY_FORM,
  UPDATE_SENSITIVE,
  buildChangedPayload,
  formatRecordValue,
  validateRecord,
  valuesFromRow,
  type RecordFormValues,
  type RecordRow,
} from "@/lib/employee/record-sections";

/** The employee's identity documents (PAN, Aadhaar, UAN, father's / husband's name) — mirrors
 * the mobile Identity section. Holders of EMPLOYEE.UPDATE_SENSITIVE edit it in place; only the
 * changed fields are sent, with the record's version as If-Match. */
export function IdentityPanel({ employeeId }: { employeeId: string }) {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canUpdate = can(UPDATE_SENSITIVE);
  const path = `/employees/${employeeId}/identity`;
  const { data, loading, error, notImplemented, retry } = useApiResource<RecordRow>(path);

  const [editOpen, setEditOpen] = useState(false);
  const [values, setValues] = useState<RecordFormValues>(() => valuesFromRow(IDENTITY_FORM, null));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  function openEdit() {
    setValues(valuesFromRow(IDENTITY_FORM, data));
    setErrors({});
    setStaleMessage(null);
    setEditOpen(true);
  }

  async function handleSave() {
    const clientErrors = validateRecord(IDENTITY_FORM, values);
    if (Object.keys(clientErrors).length > 0) {
      setErrors(clientErrors);
      return;
    }
    const changed = buildChangedPayload(IDENTITY_FORM, values, data);
    if (Object.keys(changed).length === 0) {
      setEditOpen(false);
      return;
    }
    setSaving(true);
    setErrors({});
    setStaleMessage(null);
    try {
      await apiClient.patch(path, changed, { ifMatch: String(data?.version) });
      setEditOpen(false);
      toast({ title: "Identity saved", variant: "success" });
      retry();
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE") {
        setStaleMessage("This identity record was changed by someone else since you opened this form.");
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        const fieldErrors: Record<string, string> = {};
        for (const f of IDENTITY_FORM) {
          const message = getFieldError(err.details, f.key);
          if (message) fieldErrors[f.key] = message;
        }
        if (Object.keys(fieldErrors).length > 0) {
          setErrors(fieldErrors);
          return;
        }
      }
      if (err instanceof ApiError && err.status === 403) {
        setEditOpen(false);
        toast({ title: "You don't have permission to do that", variant: "danger" });
        return;
      }
      toast({ title: "Could not save identity", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="rounded-md border border-info/30 bg-info-subtle p-3 text-xs text-foreground-secondary">
        Identity documents are restricted — visible only to holders of EMPLOYEE.VIEW_SENSITIVE.
      </div>

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading identity…" />
          </CardContent>
        </Card>
      ) : null}

      {!loading && (error || notImplemented) ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error?.status === 403
                  ? "You do not have permission to view this employee's identity documents."
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
              <h3 className="text-sm font-medium text-foreground">Identity documents</h3>
              {canUpdate ? (
                <Button type="button" size="sm" onClick={openEdit}>
                  Edit identity
                </Button>
              ) : null}
            </div>
            <dl className="mt-4 grid grid-cols-1 gap-4 sm:grid-cols-2">
              {IDENTITY_DISPLAY.map((field) => (
                <div key={field.key}>
                  <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{field.label}</dt>
                  <dd className="mt-0.5 text-sm text-foreground">{formatRecordValue(field, data[field.key])}</dd>
                </div>
              ))}
            </dl>
          </CardContent>
        </Card>
      ) : null}

      <Dialog open={editOpen} onOpenChange={(open) => (!saving ? setEditOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit identity</DialogTitle>
          </DialogHeader>
          {staleMessage ? (
            <ConcurrencyConflictBanner
              message={staleMessage}
              onReload={() => {
                setEditOpen(false);
                retry();
              }}
              onCancel={() => setStaleMessage(null)}
            />
          ) : null}
          <RecordFormFields fields={IDENTITY_FORM} values={values} errors={errors} onChange={setValues} idPrefix="identity-" />
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setEditOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleSave()} disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
