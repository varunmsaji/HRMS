import { Link2, Plus } from "lucide-react";
import Link from "next/link";
import { useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { AssignPolicyDialog } from "@/components/policy-assignment/assign-policy-dialog";
import {
  EndAssignmentDialog,
  type EndTarget,
} from "@/components/policy-assignment/end-assignment-dialog";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { TableSkeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableToolbar,
} from "@/components/ui/table";
import { usePermissions } from "@/lib/auth/use-permissions";
import {
  assignmentPermissions,
  canEndAssignment,
  needsImpactPreview,
  type PolicyKind,
} from "@/lib/policy-assignment/types";
import { usePolicyFollowers } from "@/lib/policy-assignment/use-policy-followers";

/** "Who follows this": the groups and people a policy applies to, managed from the policy's own
 * screen. The by-group view (Rules by Group) stays the place to compare every kind at once. */
export function PolicyFollowersPanel({
  policyKind,
  policyId,
  policyName,
  leaveTypeId = null,
  today,
  canManage: canManagePolicy,
  cannotAssignReason = null,
}: {
  policyKind: PolicyKind;
  policyId: string;
  policyName: string;
  leaveTypeId?: string | null;
  today: string;
  canManage: boolean;
  /** Why nobody new can be assigned right now (inactive, no published rules), if so. */
  cannotAssignReason?: string | null;
}) {
  const { can } = usePermissions();
  // Changing who follows a policy has its own permission check on the server.
  const canManage = canManagePolicy && assignmentPermissions(policyKind).every((code) => can(code));
  const followers = usePolicyFollowers({ policyKind, policyId, today });
  const [adding, setAdding] = useState(false);
  const [ending, setEnding] = useState<EndTarget | null>(null);
  const { assignments, error, truncated, scopeLabel, reload } = followers;

  const addButton =
    canManage && !cannotAssignReason ? (
      <Button type="button" size="sm" onClick={() => setAdding(true)}>
        <Plus className="h-4 w-4" aria-hidden="true" />
        Add who follows it
      </Button>
    ) : null;

  return (
    <div className="space-y-4">
      {cannotAssignReason && canManage ? (
        <Card>
          <CardContent className="pt-6">
            <p className="text-sm text-foreground-secondary">{cannotAssignReason}</p>
          </CardContent>
        </Card>
      ) : null}

      {error ? (
        <ErrorState
          message={
            error.status === 403
              ? "You do not have permission to see who follows this policy."
              : error.message
          }
          onRetry={reload}
        />
      ) : null}

      {!error && assignments === null ? (
        <div role="status" aria-label="Loading who follows this policy">
          <TableSkeleton rows={3} columns={3} />
        </div>
      ) : null}

      {!error && assignments && assignments.length === 0 ? (
        <EmptyState
          icon={Link2}
          title="Nobody follows this policy yet"
          description="Choose the whole company, a branch, department or other group, or a single person."
          action={addButton}
        />
      ) : null}

      {!error && assignments && assignments.length > 0 ? (
        <TableContainer>
          <TableToolbar>
            <p className="text-sm text-foreground-secondary">
              People in these groups follow this policy unless something more specific is set for
              them.
            </p>
            {addButton}
          </TableToolbar>
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Who</TableHead>
                <TableHead>From</TableHead>
                <TableHead>Until</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {assignments.map((a) => {
                const label = scopeLabel(a);
                return (
                  <TableRow key={a.id}>
                    <TableCell className="font-medium text-foreground">
                      {label}
                      {a.effective_from > today ? (
                        <Badge variant="outline" className="ml-2">
                          Starts later
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell className="tabular-nums text-foreground-secondary">
                      <CompanyDate value={a.effective_from} />
                    </TableCell>
                    <TableCell className="tabular-nums text-foreground-secondary">
                      {a.effective_to ? <CompanyDate value={a.effective_to} /> : "No end date"}
                    </TableCell>
                    <TableCell align="right">
                      {canManage && canEndAssignment(policyKind, a.scope_type, a.effective_to) ? (
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          onClick={() =>
                            setEnding({
                              assignmentId: a.id,
                              version: a.version,
                              effectiveFrom: a.effective_from,
                              description: `${label}: ${policyName}`,
                            })
                          }
                        >
                          End
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      ) : null}

      {truncated ? (
        <p className="text-xs text-foreground-muted">
          Showing the first 100. See every assignment in Rules by Group.
        </p>
      ) : null}

      <p className="text-xs text-foreground-muted">
        {assignments?.some((a) => a.scope_type === "COMPANY")
          ? "The whole-company assignment is the fallback for everyone, so it can't be ended here; replace it by giving the whole company another policy. "
          : ""}
        {needsImpactPreview(policyKind)
          ? "Calendar changes are replaced rather than ended, after a preview of the days they change. "
          : ""}
        To compare every policy a group follows, use{" "}
        <Link
          href="/app/policy-assignments"
          className="font-medium text-primary hover:underline"
        >
          Rules by Group
        </Link>
        .
      </p>

      {adding ? (
        <AssignPolicyDialog
          policyKind={policyKind}
          policyId={policyId}
          policyName={policyName}
          leaveTypeId={leaveTypeId}
          today={today}
          onClose={() => {
            setAdding(false);
            reload();
          }}
          onAssigned={() => {
            setAdding(false);
            reload();
          }}
        />
      ) : null}

      {ending ? (
        <EndAssignmentDialog
          key={ending.assignmentId}
          target={ending}
          today={today}
          onClose={() => setEnding(null)}
          onEnded={() => {
            setEnding(null);
            reload();
          }}
        />
      ) : null}
    </div>
  );
}
