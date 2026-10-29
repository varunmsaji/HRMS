"use client";

import {
  ArrowRight,
  Banknote,
  Building2,
  CalendarClock,
  CalendarRange,
  CheckCircle2,
  CreditCard,
  Layers3,
  ListChecks,
  Palmtree,
  UserPlus,
  Users,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { useEffect, type ComponentType, type ReactNode } from "react";

import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useApiResource } from "@/hooks/use-api-resource";
import { useAuth } from "@/lib/auth/auth-context";
import { formatCompanyDateInZone } from "@/lib/dates/company-date";
import { rememberCompanyDateFormat } from "@/lib/dates/use-company-date";
import { cn } from "@/lib/utils";
import type {
  CompanyDashboardSummary,
  CompanyProfile,
  SubscriptionSummary,
} from "@/lib/company/types";

function SummaryMetric({
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
    <div className="flex flex-col justify-between p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
          {label}
        </p>
        <span
          className={cn(
            "flex h-6 w-6 shrink-0 items-center justify-center rounded-sm",
            emphasis
              ? "bg-primary-subtle text-primary"
              : "bg-muted text-foreground-secondary",
          )}
        >
          <Icon className="h-3.5 w-3.5" aria-hidden="true" />
        </span>
      </div>
      <div className="mt-2">
        <p className="text-xl font-semibold tracking-tight tabular-nums text-foreground">
          {value}
        </p>
        {hint ? <p className="mt-0.5 text-xs text-foreground-muted">{hint}</p> : null}
      </div>
    </div>
  );
}

function DetailRow({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-2.5 text-sm">
      <span className="shrink-0 text-foreground-secondary">{label}</span>
      <span className="min-w-0 text-right font-medium tabular-nums text-foreground">{children}</span>
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

function formatTrial(
  endsAt: string | null | undefined,
  tz: string | null | undefined,
  pattern: string | null | undefined,
): string {
  if (!endsAt || !tz) return "—";
  return formatCompanyDateInZone(endsAt, tz, pattern);
}

const WORKFLOW_ACTIONS = [
  {
    href: "/app/employees",
    label: "Employee Directory",
    description: "Manage employee records, assignments, and compensation.",
    icon: Users,
  },
  {
    href: "/app/attendance",
    label: "Attendance Command",
    description: "Review daily check-ins, exceptions, and overtime.",
    icon: CalendarClock,
  },
  {
    href: "/app/leave-applications",
    label: "Leave Requests",
    description: "Review and approve pending employee leave applications.",
    icon: Palmtree,
  },
  {
    href: "/app/payroll/pay-runs",
    label: "Payroll Runs",
    description: "Lock attendance inputs, compute salary, and finalise pay runs.",
    icon: Banknote,
  },
  {
    href: "/app/onboarding",
    label: "Onboarding Cases",
    description: "Invite new hires and verify pre-joining documentation.",
    icon: UserPlus,
  },
  {
    href: "/app/work-calendars",
    label: "Work Calendars",
    description: "Configure working weeks, holidays, and dated exceptions.",
    icon: CalendarRange,
  },
];

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

  useEffect(() => {
    if (profile?.locale?.date_format) rememberCompanyDateFormat(profile.locale.date_format);
  }, [profile?.locale?.date_format]);

  const loading = dashboardLoading || subscriptionLoading || profileLoading;
  const error = dashboardError ?? subscriptionError ?? profileError;

  const setupIncomplete = dashboard?.setup_progress.status !== "COMPLETE";
  const setupHref =
    dashboard?.setup_progress.status === "COMPLETE" ? "/app/company" : "/app/setup";

  const companyName =
    profile?.name ??
    session?.companies.find((c) => c.id === session.companyId)?.name ??
    "Your company";

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="Operational overview of your organisation, workforce capacity, and platform readiness."
        actions={
          <Button asChild variant="outline" size="sm">
            <Link href={setupHref}>
              {setupIncomplete ? "Continue setup" : "Company profile"}
            </Link>
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
            <div className="flex flex-col gap-4 rounded-lg border border-primary-border bg-primary-subtle/50 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-primary-border bg-surface text-primary">
                  <ListChecks className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">
                    Finish setting up {companyName}
                  </p>
                  <p className="mt-0.5 text-xs text-foreground-secondary">
                    {dashboard.setup_progress.steps_completed} of{" "}
                    {dashboard.setup_progress.steps_total} steps complete
                  </p>
                  <Progress
                    value={dashboard.setup_progress.steps_completed}
                    max={dashboard.setup_progress.steps_total}
                    className="mt-2.5 w-full max-w-xs"
                  />
                </div>
              </div>
              <Button asChild size="sm" className="shrink-0">
                <Link href="/app/setup">Open setup</Link>
              </Button>
            </div>
          ) : (
            <div className="flex items-start gap-3 rounded-lg border border-success-border bg-success-subtle/60 px-4 py-3">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden="true" />
              <div className="min-w-0 flex-1 text-xs">
                <p className="font-semibold text-foreground">Setup complete</p>
                <p className="mt-0.5 break-words text-foreground-secondary">
                  {companyName} is configured. Keep contact and locale details current in the
                  company profile.
                </p>
              </div>
            </div>
          )}

          <section aria-label="Organisation metrics">
            <div className="grid grid-cols-2 gap-px overflow-hidden rounded-lg border border-border bg-border sm:grid-cols-3 lg:grid-cols-5 [&>*]:bg-surface">
              <SummaryMetric
                label="Employees"
                value={formatCount(dashboard.employee_count)}
                icon={Users}
                emphasis
              />
              <SummaryMetric
                label="Branches"
                value={formatCount(dashboard.branch_count)}
                icon={Building2}
              />
              <SummaryMetric
                label="Departments"
                value={formatCount(dashboard.department_count)}
                icon={Layers3}
              />
              <SummaryMetric
                label="Seat limit"
                value={formatSeatLimit(subscription?.seat_limit)}
                icon={Users}
              />
              <div className="col-span-2 sm:col-span-1">
                <SummaryMetric
                  label="Plan"
                  value={dashboard.subscription?.plan_code ?? "—"}
                  hint={dashboard.subscription?.status ?? "No live subscription"}
                  icon={CreditCard}
                />
              </div>
            </div>
          </section>

          <section aria-label="Operational workspaces">
            <h2 className="mb-3 text-xs font-semibold uppercase tracking-wider text-foreground-muted">
              Operational Workspaces
            </h2>
            <div className="grid min-w-0 gap-3 sm:grid-cols-2 lg:grid-cols-3 [&>*]:min-w-0">
              {WORKFLOW_ACTIONS.map((action) => {
                const Icon = action.icon;
                return (
                  <Link
                    key={action.href}
                    href={action.href}
                    className="group flex items-start justify-between gap-3 rounded-lg border border-border bg-surface p-4 transition-colors duration-motion-instant hover:border-border-strong hover:bg-surface-secondary/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <div className="flex items-start gap-3 min-w-0">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-border bg-surface-secondary text-foreground-secondary group-hover:border-primary-border group-hover:bg-primary-subtle group-hover:text-primary">
                        <Icon className="h-4 w-4" aria-hidden="true" />
                      </span>
                      <div className="min-w-0">
                        <p className="text-sm font-semibold text-foreground group-hover:text-primary">
                          {action.label}
                        </p>
                        <p className="mt-0.5 text-xs leading-relaxed text-foreground-secondary">
                          {action.description}
                        </p>
                      </div>
                    </div>
                    <ArrowRight
                      className="mt-1 h-4 w-4 shrink-0 text-foreground-disabled transition-transform group-hover:translate-x-0.5 group-hover:text-primary"
                      aria-hidden="true"
                    />
                  </Link>
                );
              })}
            </div>
          </section>

          <div className="grid min-w-0 gap-6 lg:grid-cols-2 [&>*]:min-w-0">
            <Card>
              <CardHeader>
                <CardTitle>Subscription &amp; Entitlements</CardTitle>
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
                      <DetailRow label="Trial ends">
                        {formatTrial(
                          subscription.trial_ends_at,
                          profile?.timezone,
                          profile?.locale?.date_format,
                        )}
                      </DetailRow>
                      <DetailRow label="Seat limit">
                        {formatSeatLimit(subscription.seat_limit)}
                      </DetailRow>
                    </div>
                    {subscription.features.length > 0 ? (
                      <div className="mt-4 border-t border-border pt-4">
                        <p className="mb-2.5 text-2xs font-semibold uppercase tracking-wider text-foreground-muted">
                          Features
                        </p>
                        <ul className="space-y-2">
                          {subscription.features.map((feature) => (
                            <li
                              key={feature.code}
                              className="flex items-center justify-between gap-3 text-xs"
                            >
                              <span className="flex min-w-0 items-center gap-2 text-foreground">
                                {feature.is_enabled ? (
                                  <CheckCircle2
                                    className="h-3.5 w-3.5 shrink-0 text-success"
                                    aria-hidden="true"
                                  />
                                ) : (
                                  <XCircle
                                    className="h-3.5 w-3.5 shrink-0 text-foreground-disabled"
                                    aria-hidden="true"
                                  />
                                )}
                                <span className="min-w-0 break-all font-mono font-medium">
                                  {feature.code}
                                  <span className="ml-2 font-sans text-xs font-normal text-foreground-muted">
                                    {feature.source.replaceAll("_", " ").toLowerCase()}
                                  </span>
                                </span>
                              </span>
                              <span className="tabular-nums text-foreground-secondary">
                                {feature.is_enabled ? "On" : "Off"}
                                {feature.limit_value != null
                                  ? ` · ${feature.limit_value}`
                                  : ""}
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
                <CardTitle>Company Identity &amp; Locale</CardTitle>
              </CardHeader>
              <CardContent className="text-sm">
                <div className="flex items-center gap-3 pb-4">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-primary-border bg-primary-subtle text-sm font-semibold uppercase text-primary">
                    {companyName.slice(0, 2)}
                  </span>
                  <div className="min-w-0">
                    <p className="truncate font-semibold text-foreground">{companyName}</p>
                    <p className="truncate font-mono text-xs text-foreground-muted">
                      {profile?.id ?? session?.companyId ?? "—"}
                    </p>
                  </div>
                  <Badge variant="secondary" className="ml-auto shrink-0 uppercase">
                    {profile?.status ?? "—"}
                  </Badge>
                </div>
                <div className="divide-y divide-border border-t border-border">
                  <DetailRow label="Country">{profile?.country_code ?? "—"}</DetailRow>
                  <DetailRow label="Currency">{profile?.currency ?? "—"}</DetailRow>
                  <DetailRow label="Timezone">{profile?.timezone ?? "—"}</DetailRow>
                  <DetailRow label="Date format">
                    {profile?.locale?.date_format ?? "—"}
                  </DetailRow>
                </div>
                <div className="mt-4 flex flex-col items-start gap-2 border-t border-border pt-3 text-xs text-foreground-muted sm:flex-row sm:items-center sm:justify-between">
                  <span className="min-w-0">Manage registration, address, and fiscal year settings.</span>
                  <Link
                    href="/app/company"
                    className="shrink-0 font-medium text-primary hover:underline"
                  >
                    Edit profile →
                  </Link>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      ) : null}
    </div>
  );
}
