"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { BranchForm } from "@/components/branch/branch-form";
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
import {
  INDIA_STATE_CODES,
  branchToFormValues,
  buildUpdatePatch,
  validateBranchForm,
  type BranchFormErrors,
  type BranchFormValues,
} from "@/lib/branch/validate-branch";
import type { LegalEntity } from "@/lib/legal-entity/types";

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

export default function BranchDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();

  const [branch, setBranch] = useState<Branch | null>(null);
  const [legalEntities, setLegalEntities] = useState<LegalEntity[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<BranchFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<BranchFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const loadBranch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, entities] = await Promise.all([
        apiClient.get<Branch>(`/branches/${params.id}`),
        apiClient.get<LegalEntity[]>("/legal-entities"),
      ]);
      setBranch(data);
      setLegalEntities(entities);
      return data;
    } catch (err) {
      setBranch(null);
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
    void loadBranch();
  }, [loadBranch]);

  function legalEntityName(legalEntityId: string): string {
    return legalEntities.find((entity) => entity.id === legalEntityId)?.name ?? "Unknown legal entity";
  }

  function startEditing() {
    if (!branch) return;
    setFormValues(branchToFormValues(branch));
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
    if (!branch || !formValues) return;

    const clientErrors = validateBranchForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    const patch = buildUpdatePatch(formValues, branch);
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
      const updated = await apiClient.patch<Branch>(`/branches/${branch.id}`, patch, {
        ifMatch: String(branch.version),
      });
      setBranch(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Branch saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This branch was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({
            legalEntityId: getFieldError(err.details, "legal_entity_id"),
            name: getFieldError(err.details, "name"),
            stateCode: getFieldError(err.details, "state_code"),
            pincode: getFieldError(err.details, "pincode"),
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
        title: "Could not save branch",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await loadBranch();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Branch reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!branch) return;
    setStatusChanging(true);
    try {
      if (branch.is_active) {
        const updated = await apiClient.delete<Branch>(`/branches/${branch.id}`, {
          ifMatch: String(branch.version),
        });
        setBranch(updated);
        toast({ title: "Branch deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<Branch>(
          `/branches/${branch.id}`,
          { is_active: true },
          { ifMatch: String(branch.version) },
        );
        setBranch(updated);
        toast({ title: "Branch reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "BRANCH_HAS_ACTIVE_DEPARTMENTS") {
        toast({
          title: "Can't deactivate this branch",
          description: "It still has active departments assigned to it.",
          variant: "danger",
        });
        setConfirmOpen(false);
        return;
      }
      toast({
        title: "Could not update branch status",
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
        <Link href="/app/branches" className="text-sm text-foreground-secondary hover:underline">
          ← Branches
        </Link>
      </div>

      <PageHeader
        title={branch?.name ?? "Branch"}
        description="Location and geofence details for this branch."
        actions={
          branch && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {branch.is_active ? "Deactivate" : "Reactivate"}
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
          {loading ? <LoadingState label="Loading branch…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this branch."
                  : error.status === 404
                    ? "This branch could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void loadBranch()}
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

          {!loading && !error && branch && editing && formValues ? (
            <div className="space-y-6">
              <BranchForm
                values={formValues}
                errors={formErrors}
                onChange={setFormValues}
                legalEntities={legalEntities}
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

          {!loading && !error && branch && !editing ? (
            <div className="space-y-8">
              <div>
                <Badge variant={branch.is_active ? "secondary" : "outline"}>
                  {branch.is_active ? "Active" : "Inactive"}
                </Badge>
              </div>
              <section>
                <h3 className="text-sm font-medium text-foreground">Identity</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Legal entity" value={legalEntityName(branch.legal_entity_id)} />
                  <DetailField label="Branch name" value={branch.name} />
                  <DetailField label="Branch code" value={branch.code} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Address</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Address line 1" value={branch.address_line1} />
                  <DetailField label="Address line 2" value={branch.address_line2} />
                  <DetailField label="City" value={branch.city} />
                  <DetailField
                    label="State / union territory"
                    value={branch.state_code ? INDIA_STATE_CODES[branch.state_code] : null}
                  />
                  <DetailField label="PIN code" value={branch.pincode} />
                  <DetailField label="Timezone" value={branch.timezone} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Geofence</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-3">
                  <DetailField label="Latitude" value={branch.latitude} />
                  <DetailField label="Longitude" value={branch.longitude} />
                  <DetailField
                    label="Geofence radius (m)"
                    value={branch.geofence_radius_m != null ? String(branch.geofence_radius_m) : null}
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
            <DialogTitle>{branch?.is_active ? "Deactivate branch?" : "Reactivate branch?"}</DialogTitle>
            <DialogDescription>
              {branch?.is_active
                ? "This branch will no longer be available for new activity. You can reactivate it later."
                : "This branch will become available for use again."}
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
              variant={branch?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : branch?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
