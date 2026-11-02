"use client";

import { CalendarRange, Plus } from "lucide-react";
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
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
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
        backHref="/app/settings"
        backLabel="Settings"
        title="Work Calendars"
        description="Composes holiday calendars, a weekly-off pattern, and dated exceptions into what kind of day it is."
        actions={
          canManage ? (
            <div className="flex items-center gap-2">
              <Button asChild variant="outline">
                <Link href="/app/work-calendars/setup">Guided setup</Link>
              </Button>
              {calendars && calendars.length > 0 ? (
                <Button type="button" onClick={openCreate}>
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  Add Work Calendar
                </Button>
              ) : null}
            </div>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading work calendars…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view work calendars."
                  : error.message
              }
              onRetry={() => void load()}
            />
          </div>
        ) : null}

        {!loading && !error && calendars && calendars.length === 0 ? (
          <div className="p-6">
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
          </div>
        ) : null}

        {!loading && !error && calendars && calendars.length > 0 ? (
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead>Calendar</TableHead>
                <TableHead>Configuration</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {calendars.map((calendar) => (
                <TableRow key={calendar.id}>
                  <TableCell>
                    <Link
                      href={`/app/work-calendars/${calendar.id}`}
                      className="font-medium text-foreground hover:text-primary hover:underline"
                    >
                      {calendar.name}
                      {calendar.code ? (
                        <span className="ml-1 font-mono text-xs text-foreground-muted">
                          ({calendar.code})
                        </span>
                      ) : null}
                    </Link>
                  </TableCell>
                  <TableCell className="text-xs text-foreground-secondary">
                    {calendar.holiday_calendar_ids.length} holiday calendar
                    {calendar.holiday_calendar_ids.length === 1 ? "" : "s"}
                    {calendar.weekly_off_pattern_id ? " · weekly-off configured" : ""}
                  </TableCell>
                  <TableCell>
                    <Badge variant={calendar.is_active ? "secondary" : "outline"}>
                      {calendar.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <TableRowAction href={`/app/work-calendars/${calendar.id}`}>View calendar</TableRowAction>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : null}
      </TableContainer>

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
