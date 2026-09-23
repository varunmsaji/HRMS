"use client";

import { UserPlus } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { OnboardingCaseForm } from "@/components/onboarding/onboarding-case-form";
import { OnboardingStatusBadge } from "@/components/onboarding/onboarding-status-badge";
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
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { OnboardingCase } from "@/lib/onboarding/types";
import {
  EMPTY_ONBOARDING_CASE_FORM_VALUES,
  buildCreatePayload,
  validateOnboardingCaseForm,
  type OnboardingCaseFormErrors,
  type OnboardingCaseFormValues,
} from "@/lib/onboarding/validate-onboarding";

interface ReferenceData {
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
}

function candidateName(onboardingCase: OnboardingCase): string {
  return [onboardingCase.candidate_first_name, onboardingCase.candidate_last_name]
    .filter(Boolean)
    .join(" ");
}

export default function OnboardingPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const router = useRouter();
  const [cases, setCases] = useState<OnboardingCase[] | null>(null);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<OnboardingCaseFormValues>(
    EMPTY_ONBOARDING_CASE_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<OnboardingCaseFormErrors>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, branches, departments, designations] = await Promise.all([
        apiClient.get<OnboardingCase[]>("/onboarding-cases"),
        apiClient.get<Branch[]>("/branches").catch(() => []),
        apiClient.get<Department[]>("/departments").catch(() => []),
        apiClient.get<Designation[]>("/designations").catch(() => []),
      ]);
      setCases(data);
      setRefs({ branches, departments, designations });
    } catch (err) {
      setCases(null);
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
    void load();
  }, [load]);

  function openCreate() {
    setFormValues(EMPTY_ONBOARDING_CASE_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateOnboardingCaseForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      const created = await apiClient.post<OnboardingCase>(
        "/onboarding-cases",
        buildCreatePayload(formValues),
      );
      setCreateOpen(false);
      toast({
        title: "Onboarding started",
        description: `Case created for ${created.candidate_first_name}.`,
        variant: "success",
      });
      router.push(`/app/onboarding/${created.id}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({
          candidateFirstName: getFieldError(err.details, "candidate_first_name"),
          personalEmail: getFieldError(err.details, "personal_email"),
          proposedJoiningDate: getFieldError(err.details, "proposed_joining_date"),
          designationId: getFieldError(err.details, "designation_id"),
          departmentId: getFieldError(err.details, "department_id"),
          branchId: getFieldError(err.details, "branch_id"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to start onboarding", variant: "danger" });
        return;
      }
      if (err instanceof ApiError && err.status === 409 && err.code === "DUPLICATE_ACTIVE_ONBOARDING_CASE") {
        setFormErrors({ personalEmail: "An active onboarding case already exists for this email." });
        return;
      }
      toast({ title: "Could not start onboarding", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  const canCreate = can("ONBOARDING.CREATE");

  return (
    <div className="space-y-6">
      <PageHeader
        title="Onboarding"
        description="Start onboarding for a known new hire; they fill in their own details, you review and activate."
        actions={
          cases && cases.length > 0 && canCreate ? (
            <Button type="button" onClick={openCreate}>
              Start Onboarding
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading onboarding cases…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view onboarding cases."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}

          {!loading && !error && cases && cases.length === 0 ? (
            <EmptyState
              icon={UserPlus}
              title="No onboarding cases yet."
              description="Start onboarding for a new hire to send them a secure link where they fill in their own personal, address, bank, and statutory details for you to review."
              action={
                canCreate ? (
                  <Button type="button" onClick={openCreate}>
                    Start Onboarding
                  </Button>
                ) : undefined
              }
            />
          ) : null}

          {!loading && !error && cases && cases.length > 0 ? (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[640px] border-collapse text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    <th className="py-2 pr-4">Candidate</th>
                    <th className="py-2 pr-4">Personal email</th>
                    <th className="py-2 pr-4">Proposed joining date</th>
                    <th className="py-2 pr-0">Status</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.map((onboardingCase) => (
                    <tr key={onboardingCase.id} className="border-b border-border last:border-0">
                      <td className="py-0">
                        <Link
                          href={`/app/onboarding/${onboardingCase.id}`}
                          className="block rounded-md px-0 py-3 pr-4 hover:underline focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                        >
                          <span className="font-medium text-foreground">
                            {candidateName(onboardingCase) || "—"}
                          </span>
                        </Link>
                      </td>
                      <td className="py-3 pr-4 text-foreground-secondary">
                        {onboardingCase.personal_email}
                      </td>
                      <td className="py-3 pr-4 text-foreground-secondary">
                        {onboardingCase.proposed_joining_date}
                      </td>
                      <td className="py-3 pr-0">
                        <OnboardingStatusBadge status={onboardingCase.status} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Start Onboarding</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <OnboardingCaseForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              branches={refs?.branches ?? []}
              departments={refs?.departments ?? []}
              designations={refs?.designations ?? []}
              idPrefix="create-"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setCreateOpen(false)} disabled={saving}>
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Starting…" : "Start onboarding"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
