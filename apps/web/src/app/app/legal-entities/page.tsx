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
} from "@/components/ui/table";
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
        backHref="/app/settings"
        backLabel="Settings"
        title="Companies"
        description="The legally registered company that employs your workforce. Add your locations as branches under it."
        actions={
          entities && entities.length > 0 ? (
            <Link
              href="/app/branches"
              className="text-sm font-medium text-primary hover:underline"
            >
              Manage branches →
            </Link>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading companies…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view companies."
                  : error.message
              }
              onRetry={() => void loadEntities()}
            />
          </div>
        ) : null}

        {!loading && !error && entities && entities.length === 0 ? (
          <div className="p-6">
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
          </div>
        ) : null}

        {!loading && !error && entities && entities.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Company</TableHead>
                <TableHead>Registration / PAN</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {entities.map((entity) => (
                <TableRow key={entity.id}>
                  <TableCell>
                    <Link
                      href={`/app/legal-entities/${entity.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {entity.name}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-xs text-foreground-secondary">
                    {entity.pan ? `PAN ${entity.pan}` : "No PAN on file"}
                  </TableCell>
                  <TableCell>
                    <Badge variant={entity.is_active ? "secondary" : "outline"}>
                      {entity.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <Link
                      href={`/app/legal-entities/${entity.id}`}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      View
                    </Link>
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
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={saving}
            >
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
