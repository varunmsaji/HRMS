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
import { useEffect, type ComponentType, type ReactNode } from "react";

import { PendingApprovals } from "@/components/dashboard/pending-approvals";
import { QuickActions } from "@/components/dashboard/quick-actions";
import { WorkforceSection } from "@/components/dashboard/workforce-overview";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useApiResource } from "@/hooks/use-api-resource";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { businessToday } from "@/lib/attendance/format";
import { formatCompanyDateInZone } from "@/lib/dates/company-date";
import { rememberCompanyDateFormat } from "@/lib/dates/use-company-date";
import { cn } from "@/lib/utils";
import type {
  CompanyDashboardSummary,
  CompanyProfile,
  SubscriptionSummary,
} from "@/lib/company/types";

type Tone = "primary" | "neutral";

const TONE_CLASSES: Record<Tone, string> = {
  primary: "bg-primary-subtle text-primary border-primary-border",
  neutral: "bg-surface-secondary text-foreground-secondary border-border",
};

function SummaryMetric({
  label,
  value,
  hint,
  icon: Icon,
  tone = "neutral",
  children,
}: {
  label: string;
  value: string;
  hint?: string;
  icon: ComponentType<{ className?: string }>;
  tone?: Tone;
  children?: ReactNode;
}) {
  return (
    <div className="flex flex-col justify-between rounded-lg border border-border bg-surface p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-xs font-medium text-foreground-secondary">{label}</p>
        <span
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-md border",
            TONE_CLASSES[tone],
          )}
        >
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
      </div>
      <div className="mt-3">
        <p className="text-2xl font-semibold tracking-tight tabular-nums text-foreground">
          {value}
        </p>
        {hint ? <p className="mt-1 text-xs text-foreground-muted">{hint}</p> : null}
        {children}
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

function describeCountry(code: string | null | undefined): string | null {
  if (!code) return null;
  try {
    return new Intl.DisplayNames(["en"], { type: "region" }).of(code) ?? null;
  } catch {
    return null;
  }
}

function monthName(month: number | undefined): string | null {
  if (!month || month < 1 || month > 12) return null;
  return new Intl.DateTimeFormat("en-GB", { month: "long", timeZone: "UTC" }).format(
    new Date(Date.UTC(2000, month - 1, 1)),
  );
}

function localTime(timeZone: string | null | undefined): string | null {
  if (!timeZone) return null;
  try {
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      hourCycle: "h23",
      timeZone,
    }).format(new Date());
  } catch {
    return null;
  }
}

function greeting(timeZone: string | null | undefined): string {
  let hour = new Date().getHours();
  try {
    if (timeZone) {
      hour = Number(
        new Intl.DateTimeFormat("en-GB", { hour: "numeric", hourCycle: "h23", timeZone }).format(
          new Date(),
        ),
      );
    }
  } catch {
    // Unknown timezone string: fall back to the browser's local hour.
  }
  if (hour < 12) return "Good morning";
  if (hour < 17) return "Good afternoon";
  return "Good evening";
}

export default function CompanyDashboardPage() {
  const { session, user } = useAuth();
  const { can } = usePermissions();
  const timezone = user?.company_timezone ?? "Asia/Kolkata";
  const canSeeAttendance = can("ATTENDANCE.VIEW");
  const canSeePending = can("LEAVE.APPLICATION_APPROVE") || can("ATTENDANCE.REGULARIZATION_APPROVE") ||
    can("ATTENDANCE.OVERTIME_APPROVE") || can("ONBOARDING.REVIEW");
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

  const todayLabel = new Intl.DateTimeFormat("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    ...(profile?.timezone ? { timeZone: profile.timezone } : {}),
  }).format(new Date());

  const hours = profile?.business_hours;
  const localeRows: Array<{ label: string; value: string; note?: string }> = [
    {
      label: "Country",
      value: profile?.country_code ?? "—",
      note: describeCountry(profile?.country_code) ?? undefined,
    },
    { label: "Currency", value: profile?.currency ?? "—" },
    {
      label: "Timezone",
      value: profile?.timezone ?? "—",
      note: localTime(profile?.timezone) ?? undefined,
    },
    { label: "Date format", value: profile?.locale?.date_format ?? "—" },
    ...(monthName(profile?.fiscal_year?.start_month)
      ? [{ label: "Fiscal year starts", value: monthName(profile?.fiscal_year?.start_month) as string }]
      : []),
    ...(hours ? [{ label: "Business hours", value: `${hours.start_time} – ${hours.end_time}` }] : []),
  ];

  const companyName =
    profile?.name ??
    session?.companies.find((c) => c.id === session.companyId)?.name ??
    "Your company";

  return (
    <div className="space-y-6">
      <section aria-label="Welcome" className="border-b border-border pb-6">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
          <div className="min-w-0">
            <p className="text-xs text-foreground-muted">{todayLabel}</p>
            <h1 className="mt-1 text-2xl font-semibold tracking-tight text-foreground">
              {greeting(profile?.timezone)}
            </h1>
            <p className="mt-1.5 max-w-xl text-sm text-foreground-secondary">
              {companyName} — workforce, plan capacity and the workspaces you use most.
            </p>
          </div>
          <div className="flex shrink-0 flex-wrap gap-2">
            <Button asChild size="sm">
              <Link href="/app/employees">
                <Users className="h-4 w-4" aria-hidden="true" />
                Employees
              </Link>
            </Button>
            <Button asChild variant="outline" size="sm" className="bg-surface">
              <Link href={setupHref}>
                {setupIncomplete ? "Continue setup" : "Company profile"}
              </Link>
            </Button>
          </div>
        </div>
      </section>

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
            <div className="flex flex-col gap-4 rounded-xl border border-primary-border bg-primary-subtle/50 p-4 sm:flex-row sm:items-center sm:justify-between">
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

          {canSeeAttendance ? (
            <WorkforceSection today={businessToday(timezone)} timezone={timezone} />
          ) : null}

          {canSeePending ? <PendingApprovals /> : null}

          <section aria-label="Organisation metrics">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <SummaryMetric
                label="Employees"
                value={formatCount(dashboard.employee_count)}
                icon={Users}
                tone="primary"
                hint={
                  subscription?.seat_limit != null && dashboard.employee_count !== null
                    ? `of ${subscription.seat_limit.toLocaleString()} seats used`
                    : subscription?.seat_limit === null
                      ? "Unlimited seats"
                      : undefined
                }
              >
                {subscription?.seat_limit != null && dashboard.employee_count !== null ? (
                  <Progress
                    value={Math.min(dashboard.employee_count, subscription.seat_limit)}
                    max={subscription.seat_limit}
                    className="mt-2.5 w-full"
                  />
                ) : null}
              </SummaryMetric>
              <SummaryMetric
                label="Branches"
                value={formatCount(dashboard.branch_count)}
                icon={Building2}
                tone="neutral"
              />
              <SummaryMetric
                label="Departments"
                value={formatCount(dashboard.department_count)}
                icon={Layers3}
                tone="neutral"
              />
              <SummaryMetric
                label="Plan"
                value={dashboard.subscription?.plan_code ?? "—"}
                hint={dashboard.subscription?.status ?? "No live subscription"}
                icon={CreditCard}
                tone="neutral"
              />
            </div>
          </section>

          <QuickActions />

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
              <CardHeader className="flex-row items-center gap-3 space-y-0">
                {profile?.branding?.logo_url ? (
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={profile.branding.logo_url}
                    alt=""
                    className="h-10 w-10 shrink-0 rounded-md border border-border bg-surface object-contain p-0.5"
                  />
                ) : (
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-foreground text-sm font-semibold uppercase text-surface">
                    {companyName.slice(0, 2)}
                  </span>
                )}
                <div className="min-w-0 flex-1">
                  <CardTitle className="truncate">{companyName}</CardTitle>
                  <p className="truncate text-xs text-foreground-muted">
                    {profile?.legal_name && profile.legal_name !== companyName
                      ? profile.legal_name
                      : "Company profile"}
                  </p>
                </div>
                <Badge variant="secondary" className="shrink-0 uppercase">
                  {profile?.status ?? "—"}
                </Badge>
              </CardHeader>
              <CardContent className="text-sm">
                <div className="divide-y divide-border border-y border-border">
                  {localeRows.map((row) => (
                    <DetailRow key={row.label} label={row.label}>
                      {row.value}
                      {row.note ? (
                        <span className="ml-2 font-normal text-foreground-muted">{row.note}</span>
                      ) : null}
                    </DetailRow>
                  ))}
                </div>
                <div className="mt-3 flex items-center justify-between gap-3 text-xs text-foreground-muted">
                  <span className="min-w-0 truncate font-mono">
                    {profile?.id ?? session?.companyId ?? "—"}
                  </span>
                  <Link
                    href="/app/company"
                    className="shrink-0 font-medium text-primary hover:underline"
                  >
                    Edit profile
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
