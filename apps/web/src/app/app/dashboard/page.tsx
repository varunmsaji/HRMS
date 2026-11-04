"use client";

import { ListChecks } from "lucide-react";
import Link from "next/link";
import { useEffect } from "react";

import { EmployeeDashboard } from "@/components/dashboard/employee-dashboard";
import { DashboardOverview } from "@/components/dashboard/dashboard-overview";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { WelcomeSetupDialog } from "@/components/company/welcome-setup-dialog";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { useApiResource } from "@/hooks/use-api-resource";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { businessToday } from "@/lib/attendance/format";
import { rememberCompanyDateFormat } from "@/lib/dates/use-company-date";
import type { CompanyDashboardSummary, CompanyProfile } from "@/lib/company/types";

/** People with an employee record but no company-dashboard permission get their own workday view. */
export default function DashboardPage() {
  const { user } = useAuth();
  const { can } = usePermissions();
  if (user?.employee_id && !can("DASHBOARD.COMPANY.VIEW")) {
    return (
      <EmployeeDashboard
        employeeId={user.employee_id}
        today={businessToday(user.company_timezone ?? "Asia/Kolkata")}
        timezone={user.company_timezone ?? "Asia/Kolkata"}
      />
    );
  }
  return <CompanyDashboard />;
}

function CompanyDashboard() {
  const { session, user } = useAuth();
  const timezone = user?.company_timezone ?? "Asia/Kolkata";

  const {
    data: dashboard,
    loading: dashboardLoading,
    error: dashboardError,
    retry: retryDashboard,
  } = useApiResource<CompanyDashboardSummary>("/dashboards/company");
  const {
    data: profile,
    loading: profileLoading,
    error: profileError,
    retry: retryProfile,
  } = useApiResource<CompanyProfile>("/companies/current");

  useEffect(() => {
    if (profile?.locale?.date_format) rememberCompanyDateFormat(profile.locale.date_format);
  }, [profile?.locale?.date_format]);

  const loading = dashboardLoading || profileLoading;
  const error = dashboardError ?? profileError;
  const setupIncomplete = dashboard?.setup_progress.status !== "COMPLETE";
  const companyName =
    profile?.name ??
    session?.companies.find((c) => c.id === session.companyId)?.name ??
    "your organisation";

  return (
    <div className="space-y-6">
      <section aria-label="Welcome">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">Dashboard</h1>
        <p className="mt-1.5 text-sm text-foreground-secondary">
          Here&apos;s what&apos;s happening in {companyName} today.
        </p>
      </section>

      <WelcomeSetupDialog companyName={companyName} />

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
            retryProfile();
          }}
        />
      ) : null}

      {!loading && !error && dashboard ? (
        <>
          {setupIncomplete ? (
            <div className="flex flex-col gap-4 rounded-2xl border border-primary-border bg-primary-subtle/50 p-4 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md border border-primary-border bg-surface text-primary">
                  <ListChecks className="h-4 w-4" aria-hidden="true" />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-foreground">Finish setting up {companyName}</p>
                  <p className="mt-0.5 text-xs text-foreground-secondary">
                    {dashboard.setup_progress.steps_completed} of {dashboard.setup_progress.steps_total}{" "}
                    steps complete
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
          ) : null}

          <DashboardOverview today={businessToday(timezone)} />
        </>
      ) : null}
    </div>
  );
}
