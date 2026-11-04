"use client";

import { Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { CompanyDate } from "@/components/common/company-date";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import type {
  PolicyBase,
  PolicyKindConfig,
  PolicyVersionBase,
} from "@/components/policy/policy-kind-config";
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
import { ApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";

function appliesToLabel(policy: PolicyBase): string {
  const groups = policy.assigned_group_count ?? 0;
  const groupText = `${groups} ${groups === 1 ? "group" : "groups"}`;
  if (policy.assigned_company_wide) {
    return groups > 0 ? `Whole company and ${groupText}` : "Whole company";
  }
  return groups > 0 ? groupText : "Not assigned";
}

function PolicyStatus({ policy, today }: { policy: PolicyBase; today: string }) {
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

export function PolicyListPage<
  P extends PolicyBase,
  V extends PolicyVersionBase,
  F extends { effectiveFrom: string },
  E extends object,
  C,
>({ config }: { config: PolicyKindConfig<P, V, F, E, C> }) {
  const { user } = useAuth();
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");
  const [policies, setPolicies] = useState<P[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);
  const { path, ListExtras } = config;

  const loadPolicies = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setPolicies(await apiClient.get<P[]>(path));
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
  }, [path]);

  useEffect(() => {
    void loadPolicies();
  }, [loadPolicies]);

  const plural = config.pluralLabel.toLowerCase();
  const Icon = config.icon;
  const addButton = (label: ReactLabel) => (
    <Button asChild>
      <Link href={`/app${path}/new`}>{label}</Link>
    </Button>
  );

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/settings"
        backLabel="Settings"
        title={config.pluralLabel}
        description={config.listDescription}
        actions={
          policies && policies.length > 0
            ? addButton(
                <>
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  Add Policy
                </>,
              )
            : null
        }
      />

      {ListExtras ? <ListExtras /> : null}

      <TableContainer>
        {loading ? <LoadingState label={`Loading ${plural}…`} /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? `You do not have permission to view ${plural}.`
                  : error.message
              }
              onRetry={() => void loadPolicies()}
            />
          </div>
        ) : null}

        {!loading && !error && policies && policies.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={Icon}
              title={config.emptyListTitle}
              description="Start from a template and publish it in one go."
              action={addButton("Add Policy")}
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
                      href={`/app${path}/${policy.id}`}
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
                    <TableRowAction href={`/app${path}/${policy.id}`}>Open</TableRowAction>
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

type ReactLabel = React.ReactNode;
