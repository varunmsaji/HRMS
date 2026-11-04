"use client";

import { ClipboardList, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { FaceEnrollmentPolicyCard } from "@/components/attendance/face-enrollment-policy-card";
import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeader,
  TableRow,
  TableRowAction,
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { ApiError } from "@/lib/api/errors";
import type { AttendancePolicy } from "@/lib/attendance-policy/types";

function appliesToLabel(policy: AttendancePolicy): string {
  const groups = policy.assigned_group_count ?? 0;
  const groupText = `${groups} ${groups === 1 ? "group" : "groups"}`;
  if (policy.assigned_company_wide) {
    return groups > 0 ? `Whole company and ${groupText}` : "Whole company";
  }
  return groups > 0 ? groupText : "Not assigned";
}

function PolicyStatus({ policy, today }: { policy: AttendancePolicy; today: string }) {
  if (!policy.is_active) return <Badge variant="outline">Inactive</Badge>;
  return (
    <span className="flex flex-col items-start gap-1">
      {policy.live_from ? (
        <Badge variant="secondary">
          {policy.live_from > today ? "New rules from " : "Live since "}
          <CompanyDate value={policy.live_from} />
        </Badge>
      ) : (
        <Badge variant="outline">{policy.has_draft ? "Draft" : "No rules yet"}</Badge>
      )}
      {policy.live_from && policy.has_draft ? (
        <span className="text-xs text-foreground-muted">Unpublished changes</span>
      ) : null}
    </span>
  );
}

export default function AttendancePoliciesPage() {
  const { can } = usePermissions();
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [policies, setPolicies] = useState<AttendancePolicy[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);


  const loadPolicies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<AttendancePolicy[]>("/attendance-policies");
      setPolicies(data);
    } catch (err) {
      setPolicies(null);
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
    void loadPolicies();
  }, [loadPolicies]);

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title="Attendance Policies"
        description="The rules that turn punches into a day's result: hours worked, lateness, missing punches and location checks."
        actions={
          policies && policies.length > 0 ? (
            <Button asChild>
              <Link href="/app/attendance-policies/new">
                <Plus className="h-4 w-4" aria-hidden="true" />
                Add Policy
              </Link>
            </Button>
          ) : null
        }
      />

      {can("ATTENDANCE.FACE_ENROLLMENT_MANAGE") ? <FaceEnrollmentPolicyCard /> : null}

      <TableContainer>
        {loading ? <LoadingState label="Loading attendance policies…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view attendance policies."
                  : error.message
              }
              onRetry={() => void loadPolicies()}
            />
          </div>
        ) : null}

        {!loading && !error && policies && policies.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={ClipboardList}
              title="No attendance policies have been configured yet."
              description="Start from a template and publish it in one go."
              action={
                <Button asChild>
                  <Link href="/app/attendance-policies/new">Add Policy</Link>
                </Button>
              }
            />
          </div>
        ) : null}

        {!loading && !error && policies && policies.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Policy</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Applies to</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {policies.map((policy) => (
                <TableRow key={policy.id}>
                  <TableCell>
                    <Link
                      href={`/app/attendance-policies/${policy.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {policy.name}
                    </Link>
                  </TableCell>
                  <TableCell>
                    <PolicyStatus policy={policy} today={today} />
                  </TableCell>
                  <TableCell className="text-sm text-foreground-secondary">
                    {appliesToLabel(policy)}
                  </TableCell>
                  <TableCell align="right">
                    <TableRowAction href={`/app/attendance-policies/${policy.id}`}>Open</TableRowAction>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>
    </div>
  );
}
