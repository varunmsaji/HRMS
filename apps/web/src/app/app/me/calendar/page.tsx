"use client";

import { CalendarDays, ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import {
  EmployeeCalendarLegend,
  EmployeeCalendarMonth,
  summariseMonth,
} from "@/components/employee-calendar/employee-calendar-view";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { businessToday } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import {
  formatMonthLabel,
  gridRangeForMonth,
  monthKeyOf,
  shiftMonth,
} from "@/lib/employee-calendar/month";
import type { EmployeeCalendar } from "@/lib/employee-calendar/types";

/** The signed-in employee's own read-only calendar. The server resolves who the employee is from
 * the session; nothing here sends an employee or company id. */
export default function MyCalendarPage() {
  const { user } = useAuth();
  const timezone = user?.company_timezone ?? "Asia/Kolkata";
  const today = businessToday(timezone);
  const hasEmployee = Boolean(user?.employee_id);

  const [month, setMonth] = useState(() => monthKeyOf(today));
  const [reloadToken, setReloadToken] = useState(0);
  // The outcome is stored with the request it answers, so "loading" is derived (no answer yet for
  // the current month/retry) instead of being set synchronously inside the effect.
  const requestKey = `${month}#${reloadToken}`;
  const [outcome, setOutcome] = useState<{
    key: string;
    calendar: EmployeeCalendar | null;
    error: ApiError | null;
  } | null>(null);

  const retry = useCallback(() => setReloadToken((n) => n + 1), []);

  useEffect(() => {
    if (!hasEmployee) return;
    let cancelled = false;
    const { from, to } = gridRangeForMonth(month);
    apiClient
      .get<EmployeeCalendar>(`/employee-calendar/me?from=${from}&to=${to}`)
      .then((data) => {
        if (!cancelled) setOutcome({ key: requestKey, calendar: data, error: null });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setOutcome({
          key: requestKey,
          calendar: null,
          error:
            err instanceof ApiError
              ? err
              : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        });
      });
    return () => {
      cancelled = true;
    };
  }, [month, hasEmployee, requestKey]);

  const answered = outcome !== null && outcome.key === requestKey;
  const loading = hasEmployee && !answered;
  const calendar = answered ? outcome.calendar : null;
  const error = answered ? outcome.error : null;

  const summary = calendar ? summariseMonth(calendar, month) : null;

  return (
    <div className="space-y-4">
      <PageHeader
        title="My Calendar"
        description="Your working days, weekly offs, holidays and leave. This view is read-only."
        actions={
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMonth((m) => shiftMonth(m, -1))}
              aria-label="Previous month"
            >
              <ChevronLeft className="h-4 w-4" aria-hidden="true" />
            </Button>
            <h2 className="min-w-32 text-center text-sm font-semibold text-foreground" aria-live="polite">
              {formatMonthLabel(month)}
            </h2>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMonth((m) => shiftMonth(m, 1))}
              aria-label="Next month"
            >
              <ChevronRight className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setMonth(monthKeyOf(today))}
              disabled={month === monthKeyOf(today)}
            >
              This month
            </Button>
          </div>
        }
      />

      {!hasEmployee ? (
        <EmptyState
          icon={CalendarDays}
          title="No employee record"
          description="Your account is not linked to an employee record, so there is no personal calendar to show."
        />
      ) : loading ? (
        <LoadingState label="Loading your calendar…" />
      ) : error ? (
        <ErrorState message={describeApiError(error)} onRetry={retry} />
      ) : calendar && calendar.configuration === "INCOMPLETE" ? (
        <EmptyState
          icon={CalendarDays}
          title="Your work calendar is not set up yet"
          description="No work calendar applies to you for this month. Please contact HR; until then, working days and holidays cannot be shown."
        />
      ) : calendar ? (
        <Card>
          <CardContent className="space-y-4 p-4">
            {calendar.configuration === "PARTIAL" ? (
              <p role="status" className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-foreground">
                A work calendar applies to you only for part of this month. Dates marked “Not set up”
                have no calendar yet.
              </p>
            ) : null}
            {summary ? (
              <p className="text-sm text-foreground-secondary" data-testid="month-summary">
                {summary.working} working {summary.working === 1 ? "day" : "days"} · {summary.nonWorking}{" "}
                non-working · {summary.approvedLeaveDays} approved leave{" "}
                {summary.approvedLeaveDays === 1 ? "day" : "days"} · {summary.pendingLeaveDays} pending
                leave {summary.pendingLeaveDays === 1 ? "day" : "days"}
              </p>
            ) : null}
            {!calendar.leave_included ? (
              <p className="text-xs text-foreground-muted">Leave is not shown for your account.</p>
            ) : null}
            <EmployeeCalendarLegend />
            <EmployeeCalendarMonth calendar={calendar} month={month} today={today} />
          </CardContent>
        </Card>
      ) : null}
    </div>
  );
}
