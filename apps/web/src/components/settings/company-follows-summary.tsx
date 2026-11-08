import { AlertTriangle } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { ErrorState } from "@/components/common/error-state";
import { Badge } from "@/components/ui/badge";
import { TableSkeleton } from "@/components/ui/skeleton";
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
import { ApiError } from "@/lib/api/errors";
import {
  coveragePath,
  coverageRowKey,
  coverageRowLabel,
  type PolicyCoverage,
  type PolicyCoverageRow,
  type PolicyKind,
} from "@/lib/policy-assignment/types";

/** The web screen for one policy, opened where you choose who follows it. */
export function policyFollowersHref(kind: PolicyKind, policyId: string): string {
  switch (kind) {
    case "WORK_CALENDAR":
      return `/app/work-calendars/${policyId}?tab=followers`;
    case "WEEKLY_OFF":
      return `/app/weekly-off-patterns/${policyId}`;
    case "ATTENDANCE_POLICY":
      return `/app/attendance-policies/${policyId}?tab=followers`;
    case "OVERTIME_POLICY":
      return `/app/overtime-policies/${policyId}?tab=followers`;
    case "REGULARIZATION_POLICY":
      return `/app/regularization-policies/${policyId}?tab=followers`;
    case "LEAVE_POLICY":
      return `/app/leave-policies/${policyId}?tab=followers`;
  }
}

const LIST_HREF: Record<PolicyKind, string> = {
  WORK_CALENDAR: "/app/work-calendars",
  WEEKLY_OFF: "/app/weekly-off-patterns",
  ATTENDANCE_POLICY: "/app/attendance-policies",
  OVERTIME_POLICY: "/app/overtime-policies",
  REGULARIZATION_POLICY: "/app/regularization-policies",
  LEAVE_POLICY: "/app/leave-policies",
};

/** Kinds where having nothing company-wide is normal, and what happens instead. */
const WHEN_UNSET: Partial<Record<PolicyKind, string>> = {
  WEEKLY_OFF: "Not set. Each work calendar's own weekly offs apply.",
  OVERTIME_POLICY: "Not set. Skip this if you don't pay overtime.",
};

/** What the whole company follows today for some kinds of policy: one place to spot a gap, with
 * a link straight to the policy where its followers are changed. */
export function CompanyFollowsSummary({
  kinds,
  today,
}: {
  kinds: PolicyKind[];
  today: string;
}) {
  const [result, setResult] = useState<{
    coverage: PolicyCoverage | null;
    error: ApiError | null;
  } | null>(null);
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let current = true;
    apiClient
      .get<PolicyCoverage>(coveragePath("COMPANY", null, today))
      .then((coverage) => {
        if (current) setResult({ coverage, error: null });
      })
      .catch((err: unknown) => {
        if (!current) return;
        setResult({
          coverage: null,
          error:
            err instanceof ApiError
              ? err
              : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        });
      });
    return () => {
      current = false;
    };
  }, [today, refresh]);

  if (!result) {
    return (
      <div role="status" aria-label="Loading what the company follows">
        <TableSkeleton rows={kinds.length} columns={2} />
      </div>
    );
  }
  if (result.error || !result.coverage) {
    return (
      <ErrorState
        message={
          result.error?.status === 403
            ? "You do not have permission to see who follows which policies."
            : (result.error?.message ?? "Something went wrong.")
        }
        onRetry={() => {
          setResult(null);
          setRefresh((n) => n + 1);
        }}
      />
    );
  }

  const rows: PolicyCoverageRow[] = kinds.flatMap((kind) =>
    result.coverage!.rows.filter((row) => row.policy_kind === kind),
  );

  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-border px-6 py-8 text-center text-sm text-foreground-secondary">
        Nothing to assign yet.
        {kinds.includes("LEAVE_POLICY") ? " Add a leave type first; each one gets its own policy." : ""}
      </p>
    );
  }

  return (
    <TableContainer>
      <Table>
        <TableHeader>
          <TableRow className="hover:bg-transparent">
            <TableHead>Rules</TableHead>
            <TableHead>Whole company follows</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => {
            const applied = row.applied;
            const unsetNote = WHEN_UNSET[row.policy_kind];
            return (
              <TableRow key={coverageRowKey(row)}>
                <TableCell className="font-medium text-foreground">{coverageRowLabel(row)}</TableCell>
                <TableCell>
                  {applied ? (
                    <>
                      <Link
                        href={policyFollowersHref(row.policy_kind, applied.policy_id)}
                        className="text-sm font-medium text-primary hover:underline"
                      >
                        {applied.policy_name ?? "Unnamed policy"}
                      </Link>
                      <p className="mt-0.5 text-xs text-foreground-muted">
                        Since <CompanyDate value={applied.effective_from} />. Open it to change who
                        follows it.
                      </p>
                      {!applied.has_rules ? (
                        <p className="mt-0.5 text-xs text-danger">
                          This policy has no published rules for today.
                        </p>
                      ) : null}
                    </>
                  ) : unsetNote ? (
                    <p className="text-sm text-foreground-secondary">{unsetNote}</p>
                  ) : (
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline" className="gap-1 border-warning/40 text-warning">
                        <AlertTriangle className="h-3 w-3" aria-hidden="true" />
                        Not set
                      </Badge>
                      <Link
                        href={LIST_HREF[row.policy_kind]}
                        className="text-sm font-medium text-primary hover:underline"
                      >
                        Pick or create one, then assign it to the whole company
                      </Link>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
