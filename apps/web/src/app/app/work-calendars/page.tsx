"use client";

import { CalendarRange } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { WorkCalendarForm } from "@/components/work-calendar/work-calendar-form";
import { EmptyState } from "@/components/common/empty-state";
import { ErrorState } from "@/components/common/error-state";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { HolidayCalendar } from "@/lib/holiday-calendar/types";
import type { WeeklyOffPattern } from "@/lib/weekly-off-pattern/types";
import type { WorkCalendar } from "@/lib/work-calendar/types";
import {
  EMPTY_WORK_CALENDAR_FORM_VALUES,
  buildCreatePayload,
  validateWorkCalendarForm,
  type WorkCalendarFormErrors,
  type WorkCalendarFormValues,
} from "@/lib/work-calendar/validate-work-calendar";

export default function WorkCalendarsPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("ORG.CALENDAR.MANAGE");

  const [calendars, setCalendars] = useState<WorkCalendar[] | null>(null);
  const [holidayCalendars, setHolidayCalendars] = useState<HolidayCalendar[]>([]);
  const [weeklyOffPatterns, setWeeklyOffPatterns] = useState<WeeklyOffPattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<WorkCalendarFormValues>(
    EMPTY_WORK_CALENDAR_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<WorkCalendarFormErrors>({});
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [calendarData, holidayCalendarData, patternData] = await Promise.all([
        apiClient.get<WorkCalendar[]>("/work-calendars"),
        apiClient.get<HolidayCalendar[]>("/holiday-calendars"),
        apiClient.get<WeeklyOffPattern[]>("/weekly-off-patterns"),
      ]);
      setCalendars(calendarData);
      setHolidayCalendars(holidayCalendarData);
      setWeeklyOffPatterns(patternData);
    } catch (err) {
      setCalendars(null);
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
    void load();
  }, [load]);

  function openCreate() {
    setFormValues(EMPTY_WORK_CALENDAR_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateWorkCalendarForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<WorkCalendar>("/work-calendars", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({ title: "Work calendar added", variant: "success" });
      await load();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({ name: getFieldError(err.details, "name") });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add work calendars", variant: "danger" });
        return;
      }
      toast({
        title: "Could not add work calendar",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Work Calendars"
        description="Composes holiday calendars, a weekly-off pattern, and dated exceptions into what kind of day it is."
        actions={
          canManage && calendars && calendars.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              Add Work Calendar
            </Button>
          ) : null
        }
      />

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading work calendars…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view work calendars."
                  : error.message
              }
              onRetry={() => void load()}
            />
          ) : null}

          {!loading && !error && calendars && calendars.length === 0 ? (
            <EmptyState
              icon={CalendarRange}
              title="No work calendars have been configured yet."
              description="Compose holiday calendars and a weekly-off pattern into an assignable work calendar."
              action={
                canManage ? (
                  <Button type="button" onClick={openCreate}>
                    Add Work Calendar
                  </Button>
                ) : undefined
              }
            />
          ) : null}

          {!loading && !error && calendars && calendars.length > 0 ? (
            <ul className="divide-y divide-border">
              {calendars.map((calendar) => (
                <li key={calendar.id} className="py-4 first:pt-0 last:pb-0">
                  <Link
                    href={`/app/work-calendars/${calendar.id}`}
                    className="flex items-center justify-between gap-4 rounded-md px-2 py-1 -mx-2 hover:bg-accent focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                  >
                    <div>
                      <p className="text-sm font-medium text-foreground">
                        {calendar.name}
                        {calendar.code ? (
                          <span className="text-foreground-muted"> ({calendar.code})</span>
                        ) : null}
                      </p>
                      <p className="mt-0.5 text-xs text-foreground-muted">
                        {calendar.holiday_calendar_ids.length} holiday calendar
                        {calendar.holiday_calendar_ids.length === 1 ? "" : "s"}
                        {calendar.weekly_off_pattern_id ? " · weekly-off configured" : ""}
                      </p>
                    </div>
                    <Badge variant={calendar.is_active ? "secondary" : "outline"}>
                      {calendar.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </Link>
                </li>
              ))}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={createOpen} onOpenChange={(open) => (!saving ? setCreateOpen(open) : null)}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Work Calendar</DialogTitle>
          </DialogHeader>
          <div className="max-h-[65vh] overflow-y-auto pr-1">
            <WorkCalendarForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
              holidayCalendars={holidayCalendars}
              weeklyOffPatterns={weeklyOffPatterns}
              idPrefix="create-"
            />
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setCreateOpen(false)}
              disabled={saving}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleCreate()} disabled={saving}>
              {saving ? "Adding…" : "Add calendar"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
