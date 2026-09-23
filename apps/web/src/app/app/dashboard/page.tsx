"use client";

import {
  Building2,
  CheckCircle2,
  CreditCard,
  Layers3,
  ListChecks,
  Users,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import type { ComponentType, ReactNode } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useApiResource } from "@/hooks/use-api-resource";
import { useAuth } from "@/lib/auth/auth-context";
import { cn } from "@/lib/utils";
import type { CompanyDashboardSummary, CompanyProfile, SubscriptionSummary } from "@/lib/company/types";

function StatTile({
  label,
  value,
  hint,
  icon: Icon,
  emphasis = false,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: ComponentType<{ className?: string }>;
  emphasis?: boolean;
}) {
  return (
    <div className="group rounded-lg border border-border bg-surface p-4 transition-shadow duration-motion-fast hover:shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <p className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</p>
        <span
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-md",
            emphasis ? "bg-primary-subtle text-primary" : "bg-muted text-foreground-secondary",
          )}
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-foreground">{value}</p>
      {hint ? <p className="mt-1 text-xs text-foreground-muted">{hint}</p> : null}
    </div>
  );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2">
      <span className="text-foreground-muted">{label}</span>
      <span className="font-medium text-foreground">{children}</span>
    </div>
  );
}

/** `null` counts (sub-domains that don't exist yet) render as "—", never a fabricated 0. */
function formatCount(value: number | null): string {
  return value === null ? "—" : value.toLocaleString();
}

function formatSeatLimit(value: number | null | undefined): string {
  if (value === undefined) return "—";
  if (value === null) return "Unlimited";
  return value.toLocaleString();
}

function formatTrial(endsAt: string | null | undefined): string {
  if (!endsAt) return "—";
  try {
    return new Date(endsAt).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return endsAt;
  }
}

export default function CompanyDashboardPage() {
  const { session } = useAuth();
  const {
    data: dashboard,
    loading: dashboardLoading,
    error: dashboardError,
    retry: retryDashboard,
  } = useApiResource<CompanyDashboardSummary>("/dashboards/company");

  const {
    data: subscription,
    loading: subscriptionLoading,
    error: subscriptionError,
    retry: retrySubscription,
  } = useApiResource<SubscriptionSummary>("/companies/current/subscription");

  const {
    data: profile,
    loading: profileLoading,
    error: profileError,
    retry: retryProfile,
  } = useApiResource<CompanyProfile>("/companies/current");

  const loading = dashboardLoading || subscriptionLoading || profileLoading;
  const error = dashboardError ?? subscriptionError ?? profileError;

  const setupIncomplete = dashboard?.setup_progress.status !== "COMPLETE";
  const setupHref =
    dashboard?.setup_progress.status === "COMPLETE" ? "/app/company" : "/app/setup";

  const companyName =
    profile?.name ?? session?.companies.find((c) => c.id === session.companyId)?.name ?? "Your company";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="An at-a-glance view of your company, plan, and setup progress."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href={setupHref}>{setupIncomplete ? "Continue setup" : "Company profile"}</Link>
          </Button>
        }
      />

      {loading ? <LoadingState label="Loading dashboard…" /> : null}

      {error && !loading ? (
        <ErrorState
          message={
            error.status === 403
              ? "You do not have permission to view the company dashboard."
              : error.message
          }
          onRetry={() => {
            retryDashboard();
            retrySubscription();
            retryProfile();
          }}
        />
      ) : null}

      {!loading && !error && dashboard ? (
        <>
          {setupIncomplete ? (
            <Card className="border-primary/20 bg-primary-subtle/40">
              <CardContent className="flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between">
                <div className="flex items-start gap-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary-subtle text-primary">
                    <ListChecks className="h-5 w-5" aria-hidden="true" />
                  </span>
                  <div className="min-w-0">
                    <p className="font-semibold text-foreground">Finish setting up {companyName}</p>
                    <p className="mt-0.5 text-sm text-foreground-muted">
                      {dashboard.setup_progress.steps_completed} of {dashboard.setup_progress.steps_total}{" "}
                      steps complete
                    </p>
                    <Progress
                      value={dashboard.setup_progress.steps_completed}
                      max={dashboard.setup_progress.steps_total}
                      className="mt-3 w-full max-w-xs"
                    />
                  </div>
                </div>
                <Button asChild size="sm" className="shrink-0">
                  <Link href="/app/setup">Open setup</Link>
                </Button>
              </CardContent>
            </Card>
          ) : (
            <Card className="border-success/20 bg-success-subtle/40">
              <CardContent className="flex items-center gap-3 p-5">
                <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-success-subtle text-success">
                  <CheckCircle2 className="h-5 w-5" aria-hidden="true" />
                </span>
                <div>
                  <p className="font-semibold text-foreground">Setup complete</p>
                  <p className="mt-0.5 text-sm text-foreground-muted">
                    {companyName} is fully configured. Keep contact and locale details current in the
                    company profile.
                  </p>
                </div>
              </CardContent>
            </Card>
          )}

          <div>
            <h2 className="mb-3 text-sm font-medium text-foreground-secondary">Overview</h2>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
              <StatTile
                label="Employees"
                value={formatCount(dashboard.employee_count)}
                icon={Users}
                emphasis
              />
              <StatTile label="Branches" value={formatCount(dashboard.branch_count)} icon={Building2} />
              <StatTile
                label="Departments"
                value={formatCount(dashboard.department_count)}
                icon={Layers3}
              />
              <StatTile
                label="Seat limit"
                value={formatSeatLimit(subscription?.seat_limit)}
                icon={Users}
              />
              <StatTile
                label="Plan"
                value={dashboard.subscription?.plan_code ?? "—"}
                hint={dashboard.subscription?.status ?? "No live subscription"}
                icon={CreditCard}
              />
            </div>
          </div>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-md">Subscription</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                {subscription ? (
                  <>
                    <div className="divide-y divide-border">
                      <DetailRow label="Plan">
                        {subscription.plan.name} ({subscription.plan.code})
                      </DetailRow>
                      <DetailRow label="Status">
                        <Badge variant="secondary" className="uppercase">
                          {subscription.status}
                        </Badge>
                      </DetailRow>
                      <DetailRow label="Trial ends">{formatTrial(subscription.trial_ends_at)}</DetailRow>
                      <DetailRow label="Seat limit">{formatSeatLimit(subscription.seat_limit)}</DetailRow>
                    </div>
                    {subscription.features.length > 0 ? (
                      <div className="pt-3">
                        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Features
                        </p>
                        <ul className="space-y-2">
                          {subscription.features.map((feature) => (
                            <li key={feature.code} className="flex items-center justify-between gap-3">
                              <span className="flex items-center gap-2 text-foreground">
                                {feature.is_enabled ? (
                                  <CheckCircle2 className="h-4 w-4 shrink-0 text-success" aria-hidden="true" />
                                ) : (
                                  <XCircle className="h-4 w-4 shrink-0 text-foreground-disabled" aria-hidden="true" />
                                )}
                                <span>
                                  {feature.code}
                                  <span className="ml-2 text-xs text-foreground-muted">
                                    {feature.source.replaceAll("_", " ").toLowerCase()}
                                  </span>
                                </span>
                              </span>
                              <span className="text-foreground-muted">
                                {feature.is_enabled ? "On" : "Off"}
                                {feature.limit_value != null ? ` · ${feature.limit_value}` : ""}
                              </span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </>
                ) : (
                  <p className="text-foreground-muted">No live subscription is available.</p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle className="text-md">Company</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                <div className="flex items-center gap-3 pb-3">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-primary-subtle text-sm font-semibold uppercase text-primary">
                    {companyName.slice(0, 2)}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-foreground">{companyName}</p>
                    <p className="truncate text-xs text-foreground-muted">
                      {profile?.id ?? session?.companyId ?? "—"}
                    </p>
                  </div>
                  <Badge variant="secondary" className="ml-auto shrink-0 uppercase">
                    {profile?.status ?? "—"}
                  </Badge>
                </div>
                <div className="divide-y divide-border border-t border-border">
                  <DetailRow label="Branches">{formatCount(dashboard.branch_count)}</DetailRow>
                  <DetailRow label="Departments">{formatCount(dashboard.department_count)}</DetailRow>
                  <DetailRow label="Employees">{formatCount(dashboard.employee_count)}</DetailRow>
                </div>
                <p className="pt-3 text-xs text-foreground-muted">
                  Organisation structure, attendance, leave, and payroll will appear here as those
                  modules ship. Counts shown as "—" are not available yet.
                </p>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
