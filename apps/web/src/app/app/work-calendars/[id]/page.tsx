"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { DayGrid, DayGridLegend } from "@/components/work-calendar/day-grid";
import { WorkCalendarForm } from "@/components/work-calendar/work-calendar-form";
import { CompanyDate } from "@/components/common/company-date";
import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { PolicyFollowersPanel } from "@/components/policy-assignment/policy-followers-panel";
import { PaginationControls } from "@/components/common/pagination-controls";
import { useToast } from "@/components/common/toast";
import { TabBar } from "@/components/ui/tab-bar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { describeDeactivationBlocked } from "@/lib/work-calendar/deactivation";
import { ChangeImpactDialog } from "@/components/work-calendar/change-impact-dialog";
import type { ProposedChange } from "@/lib/work-calendar/change-impact";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { PaginationMeta } from "@/lib/api/types";
import { businessToday, formatDateTime } from "@/lib/attendance/format";
import { useAuth } from "@/lib/auth/auth-context";
import { usePermissions } from "@/lib/auth/use-permissions";
import { useInitialTab } from "@/lib/use-initial-tab";
import type { HolidayCalendar } from "@/lib/holiday-calendar/types";
import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";
import type {
  CalendarException,
  DayType,
  WorkCalendar,
  WorkCalendarDays,
} from "@/lib/work-calendar/types";
import { DAY_TYPE_LABELS, EXCEPTION_TYPES } from "@/lib/work-calendar/types";
import {
  EMPTY_CALENDAR_EXCEPTION_FORM_VALUES,
  buildCalendarExceptionCreatePayload,
  validateCalendarExceptionForm,
  type CalendarExceptionFormErrors,
  type CalendarExceptionFormValues,
} from "@/lib/work-calendar/validate-calendar-exception";
import {
  buildUpdatePatch,
  validateWorkCalendarForm,
  workCalendarToFormValues,
  type WorkCalendarFormErrors,
  type WorkCalendarFormValues,
} from "@/lib/work-calendar/validate-work-calendar";

type TabKey = "overview" | "calendar" | "exceptions" | "followers" | "day-type";
const TABS: Array<{ key: TabKey; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "calendar", label: "Calendar" },
  { key: "exceptions", label: "Exceptions" },
  { key: "followers", label: "Who follows this" },
  { key: "day-type", label: "Day-type lookup" },
];

export default function WorkCalendarDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { user } = useAuth();
  const { can } = usePermissions();
  const [impact, setImpact] = useState<{
    change: ProposedChange;
    title: string;
    onDone: () => void | Promise<void>;
  } | null>(null);

  const canManage = can("ORG.CALENDAR.MANAGE");

  const [tab, setTab] = useState<TabKey>("overview");
  useInitialTab(TABS, setTab);
  const today = businessToday(user?.company_timezone ?? "Asia/Kolkata");

  const [calendar, setCalendar] = useState<WorkCalendar | null>(null);
  const [holidayCalendars, setHolidayCalendars] = useState<HolidayCalendar[]>([]);
  const [weeklyOffPatterns, setWeeklyOffPatterns] = useState<WeeklyOffPattern[]>([]);
  const [exceptions, setExceptions] = useState<CalendarException[] | null>(null);
  const [exceptionsPagination, setExceptionsPagination] = useState<PaginationMeta | null>(null);
  const [exceptionsPage, setExceptionsPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<WorkCalendarFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<WorkCalendarFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const [addExceptionOpen, setAddExceptionOpen] = useState(false);
  const [exceptionValues, setExceptionValues] = useState<CalendarExceptionFormValues>(
    EMPTY_CALENDAR_EXCEPTION_FORM_VALUES,
  );
  const [exceptionErrors, setExceptionErrors] = useState<CalendarExceptionFormErrors>({});
  const [savingException, setSavingException] = useState(false);

  // Month view: `monthStart` is the first of the displayed month (UTC date parts only).
  const [monthStart, setMonthStart] = useState(() => {
    const now = new Date();
    return new Date(Date.UTC(now.getFullYear(), now.getMonth(), 1));
  });
  const [monthDays, setMonthDays] = useState<WorkCalendarDays | null>(null);
  const [monthLoading, setMonthLoading] = useState(false);
  const [monthError, setMonthError] = useState<ApiError | null>(null);

  const [lookupDate, setLookupDate] = useState("");
  const [lookupResult, setLookupResult] = useState<DayType | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupLoading, setLookupLoading] = useState(false);

  const load = useCallback(
    async (targetExceptionsPage: number) => {
      setLoading(true);
      setError(null);
      try {
        const [calendarData, holidayCalendarData, patternData, exceptionResult] = await Promise.all([
          apiClient.get<WorkCalendar>(`/work-calendars/${params.id}`),
          apiClient.get<HolidayCalendar[]>("/holiday-calendars"),
          apiClient.get<WeeklyOffPattern[]>("/weekly-off-patterns"),
          apiClient.getList<CalendarException>(`/work-calendars/${params.id}/exceptions`, {
            page: targetExceptionsPage,
          }),
        ]);
        setCalendar(calendarData);
        setHolidayCalendars(holidayCalendarData);
        setWeeklyOffPatterns(patternData);
        setExceptions(exceptionResult.data);
        setExceptionsPagination(exceptionResult.pagination);
        return calendarData;
      } catch (err) {
        setCalendar(null);
        setError(
          err instanceof ApiError
            ? err
            : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
        );
        return null;
      } finally {
        setLoading(false);
      }
    },
    [params.id],
  );

  useEffect(() => {
    void load(exceptionsPage);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exceptionsPage]);

  const loadMonth = useCallback(async () => {
    setMonthLoading(true);
    setMonthError(null);
    try {
      // Whole Monday-first weeks around the month: at most 42 days, well inside the API's
      // 100-day limit, in a single request.
      const monthEnd = new Date(Date.UTC(monthStart.getUTCFullYear(), monthStart.getUTCMonth() + 1, 0));
      const from = new Date(monthStart.getTime() - ((monthStart.getUTCDay() + 6) % 7) * 86_400_000);
      const to = new Date(monthEnd.getTime() + (6 - ((monthEnd.getUTCDay() + 6) % 7)) * 86_400_000);
      const iso = (d: Date) => d.toISOString().slice(0, 10);
      setMonthDays(
        await apiClient.get<WorkCalendarDays>(
          `/work-calendars/${params.id}/days?from=${iso(from)}&to=${iso(to)}`,
        ),
      );
    } catch (err) {
      setMonthDays(null);
      setMonthError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
    } finally {
      setMonthLoading(false);
    }
  }, [monthStart, params.id]);

  useEffect(() => {
    if (tab === "calendar") void loadMonth();
  }, [tab, loadMonth]);

  function shiftMonth(delta: number) {
    setMonthStart(
      (current) => new Date(Date.UTC(current.getUTCFullYear(), current.getUTCMonth() + delta, 1)),
    );
  }

  function startEditing() {
    if (!calendar) return;
    setFormValues(workCalendarToFormValues(calendar));
    setFormErrors({});
    setStaleMessage(null);
    setEditing(true);
  }

  function cancelEditing() {
    setEditing(false);
    setFormValues(null);
    setFormErrors({});
    setStaleMessage(null);
  }

  async function handleSave() {
    if (!calendar || !formValues) return;
    const clientErrors = validateWorkCalendarForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }
    const patch = buildUpdatePatch(formValues, calendar);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      setFormValues(null);
      toast({ title: "No changes to save" });
      return;
    }

    const affectsResolution = [
      "holiday_calendar_ids",
      "weekly_off_pattern_id",
      "restricted_holidays_are_off_by_default",
    ].some((key) => key in patch);
    if (affectsResolution) {
      // Changes what days mean for employees: review the impact before anything is saved.
      setFormErrors({});
      setStaleMessage(null);
      setImpact({
        change: {
          change_type: "WORK_CALENDAR_UPDATE",
          work_calendar_id: calendar.id,
          expected_version: calendar.version,
          patch: patch as Record<string, unknown>,
        },
        title: "Save work calendar",
        onDone: async () => {
          setEditing(false);
          setFormValues(null);
          toast({ title: "Work calendar saved", variant: "success" });
          await load(exceptionsPage);
        },
      });
      return;
    }

    setSaving(true);
    setFormErrors({});
    setStaleMessage(null);
    try {
      const updated = await apiClient.patch<WorkCalendar>(`/work-calendars/${calendar.id}`, patch, {
        ifMatch: String(calendar.version),
      });
      setCalendar(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Work calendar saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This calendar was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({ name: getFieldError(err.details, "name") });
          return;
        }
      }
      toast({
        title: "Could not save work calendar",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await load(exceptionsPage);
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!calendar) return;
    setStatusChanging(true);
    try {
      if (calendar.is_active) {
        const updated = await apiClient.delete<WorkCalendar>(`/work-calendars/${calendar.id}`, {
          ifMatch: String(calendar.version),
        });
        setCalendar(updated);
        toast({ title: "Work calendar deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<WorkCalendar>(
          `/work-calendars/${calendar.id}`,
          { is_active: true },
          { ifMatch: String(calendar.version) },
        );
        setCalendar(updated);
        toast({ title: "Work calendar reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      const blocked = err instanceof ApiError ? describeDeactivationBlocked(err) : null;
      if (blocked) {
        toast({ title: "Cannot deactivate", description: blocked, variant: "danger" });
        setConfirmOpen(false);
        return;
      }
      toast({
        title: "Could not update status",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  function openAddException() {
    setExceptionValues(EMPTY_CALENDAR_EXCEPTION_FORM_VALUES);
    setExceptionErrors({});
    setAddExceptionOpen(true);
  }

  async function handleAddException() {
    const clientErrors = validateCalendarExceptionForm(exceptionValues);
    if (Object.keys(clientErrors).length > 0) {
      setExceptionErrors(clientErrors);
      return;
    }
    setExceptionErrors({});
    setImpact({
      change: {
        change_type: "EXCEPTION_CREATE",
        work_calendar_id: params.id,
        body: buildCalendarExceptionCreatePayload(exceptionValues) as Record<string, unknown>,
      },
      title: "Add exception",
      onDone: async () => {
        setAddExceptionOpen(false);
        toast({ title: "Exception added", variant: "success" });
        await reloadExceptions();
      },
    });
  }

  async function reloadExceptions() {
    // Exceptions are ordered by date, so reload the page being viewed rather than assuming page 1.
    const { data, pagination: meta } = await apiClient.getList<CalendarException>(
      `/work-calendars/${params.id}/exceptions`,
      { page: exceptionsPage },
    );
    setExceptions(data);
    setExceptionsPagination(meta);
  }

  function toggleExceptionActive(exception: CalendarException) {
    setImpact({
      change: {
        change_type: "EXCEPTION_UPDATE",
        exception_id: exception.id,
        expected_version: exception.version,
        patch: { is_active: !exception.is_active },
      },
      title: exception.is_active ? "Deactivate exception" : "Reactivate exception",
      onDone: async () => {
        toast({ title: "Exception updated", variant: "success" });
        await reloadExceptions();
      },
    });
  }

  async function handleLookup() {
    if (!lookupDate) return;
    setLookupLoading(true);
    setLookupError(null);
    setLookupResult(null);
    try {
      const data = await apiClient.get<DayType>(
        `/work-calendars/${params.id}/day-type?date=${lookupDate}`,
      );
      setLookupResult(data);
    } catch (err) {
      setLookupError(describeApiError(err));
    } finally {
      setLookupLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        backHref="/app/work-calendars"
        backLabel="Work Calendars"
        title={calendar?.name ?? "Work Calendar"}
        description="What kind of day it is — composed from holiday calendars, a weekly-off pattern, and dated exceptions."
        actions={
          canManage && calendar && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {calendar.is_active ? "Deactivate" : "Reactivate"}
              </Button>
              <Button type="button" onClick={startEditing}>
                Edit
              </Button>
            </div>
          ) : null
        }
      />

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading work calendar…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this calendar."
                  : error.status === 404
                    ? "This work calendar could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void load(exceptionsPage)}
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && calendar ? (
        <>
          <TabBar tabs={TABS} value={tab} onChange={setTab} label="Work calendar sections" />

          {tab === "overview" ? (
            <Card>
              <CardContent className="pt-6">
                {staleMessage ? (
                  <div
                    className="mb-4 rounded-md border border-warning/30 bg-warning/5 p-4"
                    role="alert"
                  >
                    <p className="text-sm font-medium text-foreground">{staleMessage}</p>
                    <div className="mt-3 flex flex-wrap gap-2">
                      <Button type="button" size="sm" onClick={() => void reloadLatest()}>
                        Reload latest
                      </Button>
                      <Button type="button" size="sm" variant="outline" onClick={cancelEditing}>
                        Cancel current changes
                      </Button>
                    </div>
                  </div>
                ) : null}

                {editing && formValues ? (
                  <div className="space-y-6">
                    <WorkCalendarForm
                      values={formValues}
                      errors={formErrors}
                      onChange={setFormValues}
                      holidayCalendars={holidayCalendars}
                      weeklyOffPatterns={weeklyOffPatterns}
                    />
                    <div className="flex flex-wrap gap-2">
                      <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                        {saving ? "Saving…" : "Save changes"}
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        onClick={cancelEditing}
                        disabled={saving}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <Badge variant={calendar.is_active ? "secondary" : "outline"}>
                      {calendar.is_active ? "Active" : "Inactive"}
                    </Badge>
                    {calendar.description ? (
                      <p className="text-sm text-foreground-muted">{calendar.description}</p>
                    ) : null}
                    <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Holiday calendars
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">
                          {calendar.holiday_calendar_ids.length === 0
                            ? "None"
                            : calendar.holiday_calendar_ids
                                .map(
                                  (id) => holidayCalendars.find((c) => c.id === id)?.name ?? id,
                                )
                                .join(", ")}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Weekly-off pattern
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">
                          {weeklyOffPatterns.find((p) => p.id === calendar.weekly_off_pattern_id)
                            ?.name ?? "Not configured"}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Optional/restricted holidays
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">
                          {calendar.restricted_holidays_are_off_by_default
                            ? "Off by default"
                            : "Working until leave applied"}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                          Last updated
                        </dt>
                        <dd className="mt-0.5 text-sm text-foreground">
                          {user?.company_timezone
                            ? formatDateTime(calendar.updated_at, user.company_timezone)
                            : calendar.updated_at}
                        </dd>
                      </div>
                    </dl>
                  </div>
                )}
              </CardContent>
            </Card>
          ) : null}

          {tab === "calendar" ? (
            <Card>
              <CardContent className="space-y-4 pt-6">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => shiftMonth(-1)}
                      disabled={monthLoading}
                      aria-label="Previous month"
                    >
                      ←
                    </Button>
                    <h3 className="min-w-36 text-center text-sm font-medium text-foreground" aria-live="polite">
                      {monthStart.toLocaleString("en-GB", {
                        month: "long",
                        year: "numeric",
                        timeZone: "UTC",
                      })}
                    </h3>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      onClick={() => shiftMonth(1)}
                      disabled={monthLoading}
                      aria-label="Next month"
                    >
                      →
                    </Button>
                  </div>
                  {!calendar.is_active ? <Badge variant="outline">Inactive calendar</Badge> : null}
                </div>

                <p className="text-xs text-foreground-muted">
                  This is how this work calendar classifies each date. A company-wide default only
                  applies once a calendar is assigned and in effect; check{" "}
                  <Link href="/app/work-calendars/setup" className="underline">
                    guided setup
                  </Link>{" "}
                  for the activation status. Optional and restricted holidays remain working days
                  {calendar.restricted_holidays_are_off_by_default
                    ? " unless this calendar treats them as off (it currently does)."
                    : " (this calendar does not treat them as off)."}
                </p>

                <DayGridLegend />

                {monthLoading ? <LoadingState label="Loading calendar…" /> : null}
                {monthError && !monthLoading ? (
                  <ErrorState
                    message={
                      monthError.status === 403
                        ? "You do not have permission to view this calendar."
                        : monthError.message
                    }
                    onRetry={() => void loadMonth()}
                  />
                ) : null}
                {!monthLoading && !monthError && monthDays ? (
                  monthDays.days.length === 0 ? (
                    <p className="text-sm text-foreground-muted">No data for this date range.</p>
                  ) : (
                    <>
                      <DayGrid days={monthDays.days} highlightMonth={monthStart.getUTCMonth()} />
                      {monthDays.holiday_calendar_ids.length === 0 ? (
                        <p className="text-xs text-foreground-muted">
                          No holiday calendar is linked to this work calendar, so no holidays are
                          shown.
                        </p>
                      ) : null}
                    </>
                  )
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          {tab === "exceptions" ? (
            <Card>
              <CardContent className="pt-6">
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-medium text-foreground">Calendar exceptions</h3>
                  {canManage ? (
                    <Button type="button" size="sm" onClick={openAddException}>
                      Add Exception
                    </Button>
                  ) : null}
                </div>
                {exceptions && exceptions.length === 0 ? (
                  <p className="mt-4 text-sm text-foreground-muted">
                    No one-off exceptions have been added to this calendar yet.
                  </p>
                ) : null}
                {exceptions && exceptions.length > 0 ? (
                  <ul className="mt-4 divide-y divide-border">
                    {exceptions
                      .slice()
                      .sort((a, b) => a.exception_date.localeCompare(b.exception_date))
                      .map((exception) => (
                        <li
                          key={exception.id}
                          className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                        >
                          <div>
                            <p className="text-sm font-medium text-foreground">
                              <CompanyDate value={exception.exception_date} />
                              <span className="ml-2 text-xs text-foreground-muted">
                                {exception.exception_type.replace("_", " ")}
                              </span>
                            </p>
                            {exception.name ? (
                              <p className="mt-0.5 text-xs text-foreground-muted">
                                {exception.name}
                              </p>
                            ) : null}
                            {exception.reason ? (
                              <p className="mt-0.5 text-xs text-foreground-muted">
                                {exception.reason}
                              </p>
                            ) : null}
                          </div>
                          <div className="flex items-center gap-2">
                            <Badge variant={exception.is_active ? "secondary" : "outline"}>
                              {exception.is_active ? "Active" : "Inactive"}
                            </Badge>
                            {canManage ? (
                              <Button
                                type="button"
                                variant="outline"
                                size="sm"
                                onClick={() => void toggleExceptionActive(exception)}
                              >
                                {exception.is_active ? "Deactivate" : "Reactivate"}
                              </Button>
                            ) : null}
                          </div>
                        </li>
                      ))}
                  </ul>
                ) : null}

                {exceptionsPagination ? (
                  <PaginationControls
                    pagination={exceptionsPagination}
                    onPageChange={setExceptionsPage}
                    disabled={loading}
                  />
                ) : null}
              </CardContent>
            </Card>
          ) : null}

          {tab === "followers" ? (
            <PolicyFollowersPanel
              policyKind="WORK_CALENDAR"
              policyId={calendar.id}
              policyName={calendar.name}
              today={today}
              canManage={canManage}
              cannotAssignReason={
                calendar.is_active
                  ? null
                  : "This calendar is inactive, so nobody new can follow it. Reactivate it to assign it."
              }
            />
          ) : null}

          {tab === "day-type" ? (
            <Card>
              <CardContent className="space-y-4 pt-6">
                <h3 className="text-sm font-medium text-foreground">Check a date</h3>
                <div className="flex flex-wrap items-end gap-3">
                  <FormField id="lookup-date" label="Date">
                    <Input
                      type="date"
                      value={lookupDate}
                      onChange={(e) => setLookupDate(e.target.value)}
                    />
                  </FormField>
                  <Button
                    type="button"
                    onClick={() => void handleLookup()}
                    disabled={!lookupDate || lookupLoading}
                  >
                    {lookupLoading ? "Checking…" : "Check"}
                  </Button>
                </div>
                {lookupError ? <p className="text-sm text-danger">{lookupError}</p> : null}
                {lookupResult ? (
                  <div className="rounded-md border border-border p-4">
                    <p className="text-sm font-medium text-foreground">
                      {DAY_TYPE_LABELS[lookupResult.day_type]}
                    </p>
                    {lookupResult.holiday_name ? (
                      <p className="mt-1 text-sm text-foreground-muted">
                        {lookupResult.holiday_name}
                      </p>
                    ) : null}
                    {lookupResult.holiday_on_weekly_off ? (
                      <p className="mt-1 text-xs text-foreground-muted">
                        Holiday lands on a weekly-off day.
                      </p>
                    ) : null}
                    {lookupResult.optional_holiday_name ? (
                      <p className="mt-1 text-xs text-foreground-muted">
                        Optional holiday available: {lookupResult.optional_holiday_name}
                      </p>
                    ) : null}
                    {lookupResult.restricted_holiday_name ? (
                      <p className="mt-1 text-xs text-foreground-muted">
                        Restricted holiday available: {lookupResult.restricted_holiday_name}
                      </p>
                    ) : null}
                  </div>
                ) : null}
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {calendar?.is_active ? "Deactivate work calendar?" : "Reactivate work calendar?"}
            </DialogTitle>
            <DialogDescription>
              {calendar?.is_active
                ? "This calendar will no longer be assignable. Blocked while it has active assignments."
                : "This calendar will become assignable again."}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={statusChanging}
            >
              Cancel
            </Button>
            <Button
              type="button"
              variant={calendar?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : calendar?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={addExceptionOpen}
        onOpenChange={(open) => (!savingException ? setAddExceptionOpen(open) : null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Calendar Exception</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField
                id="exception-date"
                label="Date"
                required
                error={exceptionErrors.exceptionDate}
              >
                <Input
                  type="date"
                  value={exceptionValues.exceptionDate}
                  onChange={(e) =>
                    setExceptionValues({ ...exceptionValues, exceptionDate: e.target.value })
                  }
                />
              </FormField>
              <FormField id="exception-type" label="Type" required>
                <NativeSelect
                  value={exceptionValues.exceptionType}
                  onChange={(e) =>
                    setExceptionValues({
                      ...exceptionValues,
                      exceptionType: e.target
                        .value as CalendarExceptionFormValues["exceptionType"],
                    })
                  }
                >
                  {EXCEPTION_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type.replace("_", " ")}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
              <FormField id="exception-name" label="Name">
                <Input
                  value={exceptionValues.name}
                  onChange={(e) =>
                    setExceptionValues({ ...exceptionValues, name: e.target.value })
                  }
                />
              </FormField>
              <FormField id="exception-reason" label="Reason">
                <Input
                  value={exceptionValues.reason}
                  onChange={(e) =>
                    setExceptionValues({ ...exceptionValues, reason: e.target.value })
                  }
                />
              </FormField>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setAddExceptionOpen(false)}
              disabled={savingException}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleAddException()}
              disabled={savingException}
            >
              {savingException ? "Adding…" : "Add exception"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      <ChangeImpactDialog
        change={impact?.change ?? null}
        title={impact?.title ?? ""}
        onClose={() => setImpact(null)}
        onApplied={() => {
          const done = impact?.onDone;
          setImpact(null);
          void done?.();
        }}
      />
    </div>
  );
}
