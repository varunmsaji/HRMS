"use client";

import { Building } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { BranchForm } from "@/components/branch/branch-form";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
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
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import {
  EMPTY_BRANCH_FORM_VALUES,
  buildCreatePayload,
  validateBranchForm,
  type BranchFormErrors,
  type BranchFormValues,
} from "@/lib/branch/validate-branch";
import type { CompanyProfile } from "@/lib/company/types";
import type { LegalEntity } from "@/lib/legal-entity/types";

export default function BranchesPage() {
  const { toast } = useToast();
  const [branches, setBranches] = useState<Branch[] | null>(null);
  const [legalEntities, setLegalEntities] = useState<LegalEntity[]>([]);
  const [company, setCompany] = useState<CompanyProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<BranchFormValues>(EMPTY_BRANCH_FORM_VALUES);
  const [formErrors, setFormErrors] = useState<BranchFormErrors>({});
  const [saving, setSaving] = useState(false);

  // First-run-only: replaces the old "go to Companies first" dead end. Most companies only
  // ever have one company, so we collect just its name here, inline, instead of making the
  // user understand a separate top-level concept before they can add their first branch.
  const [quickSetupOpen, setQuickSetupOpen] = useState(false);
  const [quickSetupName, setQuickSetupName] = useState("");
  const [quickSetupError, setQuickSetupError] = useState<string | undefined>(undefined);
  const [quickSetupSaving, setQuickSetupSaving] = useState(false);

  const loadBranches = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [branchData, entityData, companyData] = await Promise.all([
        apiClient.get<Branch[]>("/branches"),
        apiClient.get<LegalEntity[]>("/legal-entities"),
        apiClient.get<CompanyProfile>("/companies/current").catch(() => null),
      ]);
      setBranches(branchData);
      setLegalEntities(entityData);
      setCompany(companyData);
    } catch (err) {
      setBranches(null);
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
    void loadBranches();
  }, [loadBranches]);

  function legalEntityName(legalEntityId: string): string {
    return legalEntities.find((entity) => entity.id === legalEntityId)?.name ?? "Unknown company";
  }

  function openCreate() {
    setFormValues({
      ...EMPTY_BRANCH_FORM_VALUES,
      // The common case: exactly one company, so there's nothing to pick — pre-fill it and
      // the form hides the selector (see `hideLegalEntitySelector` below).
      legalEntityId: legalEntities.length === 1 ? legalEntities[0].id : "",
    });
    setFormErrors({});
    setCreateOpen(true);
  }

  function openQuickSetup() {
    setQuickSetupName(company?.legal_name || company?.name || "");
    setQuickSetupError(undefined);
    setQuickSetupOpen(true);
  }

  async function handleQuickSetup() {
    const name = quickSetupName.trim();
    if (!name) {
      setQuickSetupError("Enter your company's registered name.");
      return;
    }

    setQuickSetupSaving(true);
    setQuickSetupError(undefined);
    try {
      const created = await apiClient.post<LegalEntity>("/legal-entities", { name });
      setLegalEntities((prev) => [...prev, created]);
      setQuickSetupOpen(false);
      // Straight into "Add Branch" — that's what the user was actually trying to do.
      setFormValues({ ...EMPTY_BRANCH_FORM_VALUES, legalEntityId: created.id });
      setFormErrors({});
      setCreateOpen(true);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setQuickSetupError(getFieldError(err.details, "name") ?? "Enter a valid name.");
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setQuickSetupOpen(false);
        toast({
          title: "You don't have permission to set up the company",
          variant: "danger",
        });
        return;
      }
      toast({
        title: "Could not set up your company",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setQuickSetupSaving(false);
    }
  }

  async function handleCreate() {
    const clientErrors = validateBranchForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<Branch>("/branches", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({ title: "Branch added", variant: "success" });
      await loadBranches();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          legalEntityId: getFieldError(err.details, "legal_entity_id"),
          name: getFieldError(err.details, "name"),
          stateCode: getFieldError(err.details, "state_code"),
          pincode: getFieldError(err.details, "pincode"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add branches", variant: "danger" });
        return;
      }
      toast({
        title: "Could not add branch",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  const hasNoLegalEntities = !loading && !error && legalEntities.length === 0;

  return (
    <div className="space-y-6">
      <PageHeader
        title="Branches"
        description="Physical work locations under your companies."
        actions={
          branches && branches.length > 0 ? (
            <Button type="button" onClick={openCreate} disabled={hasNoLegalEntities}>
              Add Branch
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading branches…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view branches."
                  : error.message
              }
              onRetry={() => void loadBranches()}
            />
          ) : null}

          {hasNoLegalEntities && branches && branches.length === 0 ? (
            <EmptyState
              icon={Building}
              title="Let's set up your company."
              description="Tell us your company's registered name, then add your first branch. Takes a few seconds — you can fill in registration numbers (PAN, GST, etc.) later from Companies."
              action={
                <Button type="button" onClick={openQuickSetup}>
                  Get started
                </Button>
              }
            />
          ) : null}

          {!hasNoLegalEntities && !loading && !error && branches && branches.length === 0 ? (
            <EmptyState
              icon={Building}
              title="No branches have been configured yet."
              description="Add the physical work locations under your companies. You can add more than one branch per company."
              action={
                <Button type="button" onClick={openCreate}>
                  Add Branch
                </Button>
              }
            />
          ) : null}

          {!loading && !error && branches && branches.length > 0 ? (
            <ul className="divide-y divide-border">
              {branches.map((branch) => (
                <li key={branch.id} className="py-4 first:pt-0 last:pb-0">
                  <Link
                    href={`/app/branches/${branch.id}`}
                    className="flex items-center justify-between gap-4 rounded-md px-2 py-1 -mx-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">{branch.name}</p>
                      <p className="mt-0.5 text-xs text-foreground-muted">
                        {legalEntityName(branch.legal_entity_id)}
                        {branch.city ? ` · ${branch.city}` : ""}
                      </p>
                    </div>
                    <Badge variant={branch.is_active ? "secondary" : "outline"}>
                      {branch.is_active ? "Active" : "Inactive"}
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
            <DialogTitle>Add Branch</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <BranchForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              legalEntities={legalEntities}
              idPrefix="create-"
              hideLegalEntitySelector={legalEntities.length === 1}
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Adding…" : "Add branch"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={quickSetupOpen}
        onOpenChange={(open) => (!quickSetupSaving ? setQuickSetupOpen(open) : null)}
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Set up your company</DialogTitle>
          </DialogHeader>
          <FormField
            id="quick-setup-legal-name"
            label="Registered company name"
            required
            error={quickSetupError}
            description="Your company's legal/registered name. You can add PAN, GST, and other registration numbers later."
          >
            <Input
              value={quickSetupName}
              onChange={(e) => setQuickSetupName(e.target.value)}
              autoFocus
            />
          </FormField>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setQuickSetupOpen(false)}
              disabled={quickSetupSaving}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleQuickSetup()} disabled={quickSetupSaving}>
              {quickSetupSaving ? "Saving…" : "Continue"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
