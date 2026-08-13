"use client";

import Link from "next/link";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useApiResource } from "@/hooks/use-api-resource";
import { useAuth } from "@/lib/auth/auth-context";
import type { CompanyDashboardSummary, CompanyProfile, SubscriptionSummary } from "@/lib/company/types";

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-md border border-border bg-surface p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-foreground">{value}</p>
      {hint ? <p className="mt-1 text-xs text-foreground-muted">{hint}</p> : null}
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
          <Card>
            <CardHeader>
              <CardTitle className="text-md">Company</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <p className="text-lg font-semibold text-foreground">
                  {profile?.name ?? session?.companies.find((c) => c.id === session.companyId)?.name ?? "Your company"}
                </p>
                <p className="text-sm text-foreground-muted">
                  {profile?.id ?? session?.companyId ?? "—"}
                </p>
              </div>
              <Badge variant="secondary" className="w-fit uppercase">
                {profile?.status ?? "—"}
              </Badge>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-md">Overview</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-5">
                <StatTile
                  label="Setup steps"
                  value={`${dashboard.setup_progress.steps_completed}/${dashboard.setup_progress.steps_total}`}
                  hint={dashboard.setup_progress.status.replaceAll("_", " ").toLowerCase()}
                />
                <StatTile
                  label="Plan"
                  value={dashboard.subscription?.plan_code ?? "—"}
                  hint={dashboard.subscription?.status ?? "No live subscription"}
                />
                <StatTile
                  label="Seat limit"
                  value={formatSeatLimit(subscription?.seat_limit)}
                />
                <StatTile label="Branches" value={formatCount(dashboard.branch_count)} />
                <StatTile label="Departments" value={formatCount(dashboard.department_count)} />
                <StatTile label="Employees" value={formatCount(dashboard.employee_count)} />
              </div>
            </CardContent>
          </Card>

          <div className="grid gap-6 lg:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle className="text-md">Subscription</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {subscription ? (
                  <>
                    <div className="flex items-center justify-between gap-4">
                      <span className="text-foreground-muted">Plan</span>
                      <span className="font-medium text-foreground">
                        {subscription.plan.name} ({subscription.plan.code})
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-4">
                      <span className="text-foreground-muted">Status</span>
                      <Badge variant="secondary" className="uppercase">
                        {subscription.status}
                      </Badge>
                    </div>
                    <div className="flex items-center justify-between gap-4">
                      <span className="text-foreground-muted">Trial ends</span>
                      <span className="font-medium text-foreground">
                        {formatTrial(subscription.trial_ends_at)}
                      </span>
                    </div>
                    <div className="flex items-center justify-between gap-4">
                      <span className="text-foreground-muted">Seat limit</span>
                      <span className="font-medium text-foreground">
                        {formatSeatLimit(subscription.seat_limit)}
                      </span>
                    </div>
                    {subscription.features.length > 0 ? (
                      <div className="pt-2">
                        <p className="mb-2 text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Features
                        </p>
                        <ul className="space-y-1">
                          {subscription.features.map((feature) => (
                            <li
                              key={feature.code}
                              className="flex items-center justify-between gap-3 text-foreground"
                            >
                              <span>
                                {feature.code}
                                <span className="ml-2 text-xs text-foreground-muted">
                                  {feature.source.replaceAll("_", " ").toLowerCase()}
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
                <CardTitle className="text-md">Next actions</CardTitle>
              </CardHeader>
              <CardContent className="space-y-3 text-sm">
                {setupIncomplete ? (
                  <div className="flex items-center justify-between gap-4 rounded-md border border-border p-3">
                    <div>
                      <p className="font-medium text-foreground">Finish company setup</p>
                      <p className="text-foreground-muted">
                        {dashboard.setup_progress.steps_completed} of{" "}
                        {dashboard.setup_progress.steps_total} steps complete
                      </p>
                    </div>
                    <Button asChild size="sm">
                      <Link href="/app/setup">Open setup</Link>
                    </Button>
                  </div>
                ) : (
                  <div className="flex items-center justify-between gap-4 rounded-md border border-border p-3">
                    <div>
                      <p className="font-medium text-foreground">Review company profile</p>
                      <p className="text-foreground-muted">Keep contact and locale details current.</p>
                    </div>
                    <Button asChild size="sm" variant="outline">
                      <Link href="/app/company">Open profile</Link>
                    </Button>
                  </div>
                )}
                <p className="text-foreground-muted">
                  Organisation structure, employees, attendance, leave, and payroll will appear
                  here as those modules ship. Counts shown as "—" are not available yet.
                </p>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
