"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { OnboardingStatusBadge } from "@/components/onboarding/onboarding-status-badge";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { Branch } from "@/lib/branch/types";
import type { Department } from "@/lib/department/types";
import type { Designation } from "@/lib/designation/types";
import type { LegalEntity } from "@/lib/legal-entity/types";
import type { OnboardingCase } from "@/lib/onboarding/types";

interface ReferenceData {
  branches: Branch[];
  departments: Department[];
  designations: Designation[];
  legalEntities: LegalEntity[];
}

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  const display = value && value.trim() ? value : "Not set";
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className={`mt-0.5 text-sm ${value && value.trim() ? "text-foreground" : "text-foreground-muted"}`}>
        {display}
      </dd>
    </div>
  );
}

function nameIn<T extends { id: string; name?: string; title?: string }>(
  list: T[] | undefined,
  id: string | null,
): string {
  if (!id) return "";
  const item = list?.find((entry) => entry.id === id);
  return item?.name ?? item?.title ?? "Unknown";
}

export default function OnboardingCaseDetailPage() {
  const params = useParams<{ id: string }>();

  const [onboardingCase, setOnboardingCase] = useState<OnboardingCase | null>(null);
  const [refs, setRefs] = useState<ReferenceData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [data, branches, departments, designations, legalEntities] = await Promise.all([
        apiClient.get<OnboardingCase>(`/onboarding-cases/${params.id}`),
        apiClient.get<Branch[]>("/branches").catch(() => []),
        apiClient.get<Department[]>("/departments").catch(() => []),
        apiClient.get<Designation[]>("/designations").catch(() => []),
        apiClient.get<LegalEntity[]>("/legal-entities").catch(() => []),
      ]);
      setOnboardingCase(data);
      setRefs({ branches, departments, designations, legalEntities });
    } catch (err) {
      setOnboardingCase(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return <LoadingState label="Loading onboarding case…" />;
  }

  if (error || !onboardingCase) {
    return (
      <ErrorState
        message={
          error?.status === 404
            ? "This onboarding case could not be found."
            : error?.status === 403
              ? "You do not have permission to view this onboarding case."
              : error?.message ?? "Something went wrong."
        }
        onRetry={() => void load()}
      />
    );
  }

  const candidateName = [onboardingCase.candidate_first_name, onboardingCase.candidate_last_name]
    .filter(Boolean)
    .join(" ");

  return (
    <div className="space-y-6">
      <PageHeader
        title={candidateName || "Onboarding case"}
        description="HR-started onboarding case — sending the candidate link, section review, and activation land in later phases."
        actions={
          <Link href="/app/onboarding" className="text-sm text-foreground-secondary hover:underline">
            ← Back to onboarding
          </Link>
        }
      />

      <Card>
        <CardContent className="space-y-6 pt-6">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-medium text-foreground">Status</h3>
            <OnboardingStatusBadge status={onboardingCase.status} />
          </div>

          <dl className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <DetailField label="Candidate first name" value={onboardingCase.candidate_first_name} />
            <DetailField label="Candidate last name" value={onboardingCase.candidate_last_name} />
            <DetailField label="Personal email" value={onboardingCase.personal_email} />
            <DetailField label="Personal mobile" value={onboardingCase.personal_mobile} />
            <DetailField label="Proposed joining date" value={onboardingCase.proposed_joining_date} />
            <DetailField label="Legal entity" value={nameIn(refs?.legalEntities, onboardingCase.legal_entity_id)} />
            <DetailField label="Branch" value={nameIn(refs?.branches, onboardingCase.branch_id)} />
            <DetailField label="Department" value={nameIn(refs?.departments, onboardingCase.department_id)} />
            <DetailField label="Designation" value={nameIn(refs?.designations, onboardingCase.designation_id)} />
          </dl>
        </CardContent>
      </Card>
    </div>
  );
}
