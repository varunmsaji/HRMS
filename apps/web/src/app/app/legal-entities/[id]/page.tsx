"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { LegalEntityForm } from "@/components/legal-entity/legal-entity-form";
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
import type { LegalEntity } from "@/lib/legal-entity/types";
import {
  buildUpdatePatch,
  legalEntityToFormValues,
  validateLegalEntityForm,
  type LegalEntityFormErrors,
  type LegalEntityFormValues,
} from "@/lib/legal-entity/validate-legal-entity";

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

export default function LegalEntityDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();

  const [entity, setEntity] = useState<LegalEntity | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<LegalEntityFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<LegalEntityFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const loadEntity = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<LegalEntity>(`/legal-entities/${params.id}`);
      setEntity(data);
      return data;
    } catch (err) {
      setEntity(null);
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
    void loadEntity();
  }, [loadEntity]);

  function startEditing() {
    if (!entity) return;
    setFormValues(legalEntityToFormValues(entity));
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
    if (!entity || !formValues) return;

    const clientErrors = validateLegalEntityForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    const patch = buildUpdatePatch(formValues, entity);
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
      const updated = await apiClient.patch<LegalEntity>(
        `/legal-entities/${entity.id}`,
        patch,
        { ifMatch: String(entity.version) },
      );
      setEntity(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Company saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This company was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({
            name: getFieldError(err.details, "name"),
            pan: getFieldError(err.details, "pan"),
            gstin: getFieldError(err.details, "gstin"),
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
        title: "Could not save company",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await loadEntity();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Company reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!entity) return;
    setStatusChanging(true);
    try {
      if (entity.is_active) {
        const updated = await apiClient.delete<LegalEntity>(`/legal-entities/${entity.id}`, {
          ifMatch: String(entity.version),
        });
        setEntity(updated);
        toast({ title: "Company deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<LegalEntity>(
          `/legal-entities/${entity.id}`,
          { is_active: true },
          { ifMatch: String(entity.version) },
        );
        setEntity(updated);
        toast({ title: "Company reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "LEGAL_ENTITY_HAS_ACTIVE_BRANCHES") {
        toast({
          title: "Can't deactivate this company",
          description: "It still has active branches assigned to it.",
          variant: "danger",
        });
        setConfirmOpen(false);
        return;
      }
      toast({
        title: "Could not update company status",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/legal-entities"
        backLabel="Legal Entities"
        title={entity?.name ?? "Company"}
        description="Registration and statutory details for this company."
        actions={
          entity && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {entity.is_active ? "Deactivate" : "Reactivate"}
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
          {loading ? <LoadingState label="Loading company…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this company."
                  : error.status === 404
                    ? "This company could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void loadEntity()}
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

          {!loading && !error && entity && editing && formValues ? (
            <div className="space-y-6">
              <LegalEntityForm values={formValues} errors={formErrors} onChange={setFormValues} />
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

          {!loading && !error && entity && !editing ? (
            <div className="space-y-8">
              <div>
                <Badge variant={entity.is_active ? "secondary" : "outline"}>
                  {entity.is_active ? "Active" : "Inactive"}
                </Badge>
              </div>
              <section>
                <h3 className="text-sm font-medium text-foreground">Identity</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Company name" value={entity.name} />
                  <DetailField label="Registered address" value={entity.registered_address} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Statutory identifiers</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="PAN" value={entity.pan} />
                  <DetailField label="GSTIN" value={entity.gstin} />
                  <DetailField label="TAN" value={entity.tan} />
                  <DetailField label="CIN" value={entity.cin} />
                  <DetailField label="PF establishment code" value={entity.pf_code} />
                  <DetailField label="ESI code" value={entity.esi_code} />
                  <DetailField label="Labour welfare fund (LWF) registration" value={entity.lwf_reg} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Authorized signatory</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Signatory name" value={entity.signatory_name} />
                  <DetailField label="Signatory designation" value={entity.signatory_designation} />
                </dl>
              </section>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{entity?.is_active ? "Deactivate company?" : "Reactivate company?"}</DialogTitle>
            <DialogDescription>
              {entity?.is_active
                ? "This company will no longer be available for new activity. You can reactivate it later."
                : "This company will become available for use again."}
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
              variant={entity?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging
                ? "Saving…"
                : entity?.is_active
                  ? "Deactivate"
                  : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
