"use client";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import {
  SetupChecklistList,
  useSetupChecklistState,
} from "@/components/company/setup-checklist-card";
import { Badge } from "@/components/ui/badge";

/** The one place that says what is left to set up. The dashboard banner, the Settings banner and
 * this page all read the same live checklist (`GET /companies/current/setup-checklist`), so the
 * counts always agree. */
export default function CompanySetupPage() {
  const { checklist, loading } = useSetupChecklistState();
  const essentialsDone = checklist ? checklist.required_complete >= checklist.required_total : false;

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Company setup"
        description="What is left to set up, and where to do it."
        actions={
          checklist ? (
            <Badge variant={essentialsDone ? "success" : "secondary"} dot={essentialsDone}>
              {essentialsDone
                ? "Essentials done"
                : `${checklist.required_complete} of ${checklist.required_total} essentials done`}
            </Badge>
          ) : null
        }
      />

      {loading ? <LoadingState label="Loading setup…" /> : null}
      {!loading && !checklist ? (
        <ErrorState
          message="We could not load your setup list. You may not have permission to see it."
          onRetry={() => window.location.reload()}
        />
      ) : null}
      <SetupChecklistList checklist={checklist} />
    </div>
  );
}
