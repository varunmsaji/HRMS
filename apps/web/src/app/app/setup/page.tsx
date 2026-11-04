"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { SetupChecklistList } from "@/components/company/setup-checklist-card";
import { SetupProgress } from "@/components/company/setup-progress";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import type { CompanySetupProgressSummary } from "@/lib/company/types";

/** Where each documented setup step sends the user to finish it. Only one step exists in
 * this module's V1 delivery (docs/modules/company/04_API_Design.md §5); sibling steps add
 * their own entry here without touching the rest of this page. */
const STEP_DESTINATIONS: Record<string, { label: string; href: string }> = {
  COMPANY_PROFILE: { label: "Go to company profile", href: "/app/company" },
};

export default function CompanySetupPage() {
  const [progress, setProgress] = useState<CompanySetupProgressSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const loadProgress = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<CompanySetupProgressSummary>(
        "/companies/current/setup-progress",
      );
      setProgress(data);
    } catch (err) {
      setProgress(null);
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
    void loadProgress();
  }, [loadProgress]);

  const isComplete = progress?.status === "COMPLETE";
  const nextStep = progress?.current_step ? STEP_DESTINATIONS[progress.current_step] : undefined;
  const completedCount = progress?.steps.filter((step) => step.is_complete).length ?? 0;
  const totalCount = progress?.steps.length ?? 0;

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Company setup"
        description="What is left to set up, and where to do it."
        actions={
          progress ? (
            <Badge variant={isComplete ? "success" : "secondary"} dot={isComplete}>
              {isComplete
                ? "Registration complete"
                : `${completedCount} of ${totalCount} registration steps done`}
            </Badge>
          ) : null
        }
      />

      <SetupChecklistList />

      <Card>
        <CardContent className="space-y-4 pt-6">
          <h2 className="text-sm font-semibold text-foreground">Registration</h2>
          {loading ? <LoadingState label="Loading setup progress…" /> : null}
          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view company setup progress."
                  : error.message
              }
              onRetry={() => void loadProgress()}
            />
          ) : null}

          {!loading && !error && progress ? (
            <>
              {!isComplete && nextStep ? (
                <div className="rounded-md border border-border bg-muted/40 p-4">
                  <p className="text-sm font-medium text-foreground">Next step</p>
                  <p className="mt-1 text-sm text-foreground-secondary">
                    Finish setting up “{progress.steps.find((s) => s.code === progress.current_step)?.label}”
                    to keep onboarding moving.
                  </p>
                  <Button asChild size="sm" className="mt-3">
                    <Link href={nextStep.href}>{nextStep.label}</Link>
                  </Button>
                </div>
              ) : null}
              <SetupProgress steps={progress.steps} />
            </>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
