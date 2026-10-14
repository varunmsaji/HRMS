"use client";

import { Landmark } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { LegalEntityForm } from "@/components/legal-entity/legal-entity-form";
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
import type { LegalEntity } from "@/lib/legal-entity/types";
import {
  EMPTY_LEGAL_ENTITY_FORM_VALUES,
  buildCreatePayload,
  validateLegalEntityForm,
  type LegalEntityFormErrors,
  type LegalEntityFormValues,
} from "@/lib/legal-entity/validate-legal-entity";

export default function LegalEntitiesPage() {
  const { toast } = useToast();
  const [entities, setEntities] = useState<LegalEntity[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<LegalEntityFormValues>(
    EMPTY_LEGAL_ENTITY_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<LegalEntityFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadEntities = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<LegalEntity[]>("/legal-entities");
      setEntities(data);
    } catch (err) {
      setEntities(null);
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
    void loadEntities();
  }, [loadEntities]);

  function openCreate() {
    setFormValues(EMPTY_LEGAL_ENTITY_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateLegalEntityForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<LegalEntity>("/legal-entities", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({ title: "Company added", variant: "success" });
      await loadEntities();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          name: getFieldError(err.details, "name"),
          pan: getFieldError(err.details, "pan"),
          gstin: getFieldError(err.details, "gstin"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({
          title: "You don't have permission to add companies",
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not add company",
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
        title="Companies"
        description="The legally registered company that employs your workforce. Add your locations as branches under it."
        actions={
          entities && entities.length > 0 ? (
            <Link href="/app/branches" className="text-sm text-foreground-secondary hover:underline">
              Manage branches →
            </Link>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading companies…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view companies."
                  : error.message
              }
              onRetry={() => void loadEntities()}
            />
          ) : null}

          {!loading && !error && entities && entities.length === 0 ? (
            <EmptyState
              icon={Landmark}
              title="No companies have been configured yet."
              description="Add the registered company that employs your workforce. You can then add as many branches as you need under it."
              action={
                <Button type="button" onClick={openCreate}>
                  Add Company
                </Button>
              }
            />
          ) : null}

          {!loading && !error && entities && entities.length > 0 ? (
            <ul className="divide-y divide-border">
              {entities.map((entity) => (
                <li key={entity.id} className="py-4 first:pt-0 last:pb-0">
                  <Link
                    href={`/app/legal-entities/${entity.id}`}
                    className="flex items-center justify-between gap-4 rounded-md px-2 py-1 -mx-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">{entity.name}</p>
                      <p className="mt-0.5 text-xs text-foreground-muted">
                        {entity.pan ? `PAN ${entity.pan}` : "No PAN on file"}
                      </p>
                    </div>
                    <Badge variant={entity.is_active ? "secondary" : "outline"}>
                      {entity.is_active ? "Active" : "Inactive"}
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
            <DialogTitle>Add Company</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <LegalEntityForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              idPrefix="create-"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Adding…" : "Add company"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
