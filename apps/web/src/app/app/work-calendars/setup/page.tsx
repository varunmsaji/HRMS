"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ErrorState } from "@/components/common/error-state";
import { FormField } from "@/components/common/form-field";
import { LoadingState } from "@/components/common/loading-state";
import { PageHeader } from "@/components/common/page-header";
import { useToast } from "@/components/common/toast";
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
import { DayGrid, DayGridLegend } from "@/components/work-calendar/day-grid";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { HolidayCalendar } from "@/lib/holiday-calendar/types";
import type {
  WorkCalendarSetupConfirmed,
  WorkCalendarSetupPreview,
  WorkCalendarSetupStatus,
} from "@/lib/work-calendar/types";

const WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function todayIso(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${now.getFullYear()}-${month}-${day}`;
}

export default function WorkCalendarSetupPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("ORG.CALENDAR.MANAGE");

  const [status, setStatus] = useState<WorkCalendarSetupStatus | null>(null);
  const [holidayCalendars, setHolidayCalendars] = useState<HolidayCalendar[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  // Editable proposal. Seeded from the unconfirmed suggestion; none of this is saved.
  const [offDays, setOffDays] = useState<number[]>([]);
  const [holidayIds, setHolidayIds] = useState<string[]>([]);
  const [effectiveFrom, setEffectiveFrom] = useState(todayIso());
  const [name, setName] = useState("Default work calendar");

  const [preview, setPreview] = useState<WorkCalendarSetupPreview | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);
  // Set when the proposal is edited after a preview: the preview no longer describes it.
  const [previewStale, setPreviewStale] = useState(false);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [acknowledged, setAcknowledged] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [confirmed, setConfirmed] = useState<WorkCalendarSetupConfirmed | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [statusData, holidayData] = await Promise.all([
        apiClient.get<WorkCalendarSetupStatus>("/work-calendar-setup"),
        apiClient.get<HolidayCalendar[]>("/holiday-calendars"),
      ]);
      setStatus(statusData);
      setHolidayCalendars(holidayData.filter((c) => c.is_active));
      if (statusData.suggestion) setOffDays(statusData.suggestion.weekly_off_weekdays);
    } catch (err) {
      setStatus(null);
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

  function edited() {
    if (preview) setPreviewStale(true);
  }

  function toggleOffDay(day: number) {
    setOffDays((current) =>
      current.includes(day) ? current.filter((d) => d !== day) : [...current, day].sort(),
    );
    edited();
  }

  function toggleHoliday(id: string) {
    setHolidayIds((current) =>
      current.includes(id) ? current.filter((x) => x !== id) : [...current, id],
    );
    edited();
  }

  const proposal = {
    weekly_off_weekdays: offDays,
    holiday_calendar_ids: holidayIds,
    effective_from: effectiveFrom,
  };
  const proposalValid = effectiveFrom !== "" && offDays.length < 7 && name.trim() !== "";

  async function handlePreview() {
    setPreviewing(true);
    setPreviewError(null);
    try {
      setPreview(
        await apiClient.post<WorkCalendarSetupPreview>("/work-calendar-setup/preview", proposal),
      );
      setPreviewStale(false);
    } catch (err) {
      setPreviewError(describeApiError(err));
    } finally {
      setPreviewing(false);
    }
  }

  async function handleConfirm() {
    setConfirming(true);
    try {
      const result = await apiClient.post<WorkCalendarSetupConfirmed>(
        "/work-calendar-setup/confirm",
        { ...proposal, name: name.trim(), confirm: true },
      );
      setConfirmed(result);
      setConfirmOpen(false);
      toast({ title: "Work calendar activated", variant: "success" });
      await load();
    } catch (err) {
      setConfirmOpen(false);
      if (err instanceof ApiError && err.code === "WORK_CALENDAR_ALREADY_CONFIGURED") {
        toast({
          title: "A calendar is already active",
          description: "Someone else activated a calendar first. Reloading the current status.",
          variant: "danger",
        });
        await load();
        return;
      }
      toast({
        title: "Could not activate the work calendar",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/app/work-calendars"
          className="text-sm text-foreground-secondary hover:underline"
        >
          ← Work Calendars
        </Link>
      </div>

      <PageHeader
        title="Work calendar setup"
        description="Review a suggested working week, check the resulting calendar, then activate it."
      />

      {loading ? (
        <Card>
          <CardContent className="pt-6">
            <LoadingState label="Loading setup status…" />
          </CardContent>
        </Card>
      ) : null}

      {error && !loading ? (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to manage work calendars."
                  : error.message
              }
              onRetry={error.status === 403 ? undefined : () => void load()}
            />
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && status?.state === "CONFIGURED" ? (
        <Card>
          <CardContent className="space-y-3 pt-6">
            <Badge variant="secondary">Configured</Badge>
            <p className="text-sm text-foreground">
              {confirmed
                ? "The work calendar has been activated."
                : "A company-wide work calendar is already active."}
              {status.company_assignment
                ? ` It applies from ${status.company_assignment.effective_from}.`
                : ""}
            </p>
            {status.company_assignment ? (
              <Link
                href={`/app/work-calendars/${status.company_assignment.work_calendar_id}`}
                className="text-sm underline"
              >
                View the calendar
              </Link>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      {!loading && !error && status?.state === "SETUP_REQUIRED" ? (
        <>
          <div
            className="rounded-md border border-warning/30 bg-warning/5 p-4"
            role="status"
          >
            <p className="text-sm font-medium text-foreground">Work calendar setup required</p>
            <p className="mt-1 text-sm text-foreground-muted">
              {status.suggestion?.notice ??
                "No work calendar is active. Leave and attendance cannot classify days until one is confirmed."}
            </p>
            <p className="mt-1 text-sm text-foreground-muted">
              The weekday settings on the company profile are not used for this. Nothing below is
              saved until you confirm.
            </p>
          </div>

          <Card>
            <CardContent className="space-y-5 pt-6">
              <div className="flex items-center gap-2">
                <h3 className="text-sm font-medium text-foreground">Proposed configuration</h3>
                <Badge variant="outline">Unconfirmed suggestion</Badge>
              </div>

              <fieldset>
                <legend className="text-sm font-medium text-foreground">Weekly offs</legend>
                <p className="mt-0.5 text-xs text-foreground-muted">
                  Checked days are non-working every week. Unchecked days are working days.
                </p>
                <div className="mt-2 flex flex-wrap gap-4">
                  {WEEKDAYS.map((label, index) => (
                    <label key={label} className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={offDays.includes(index)}
                        onChange={() => toggleOffDay(index)}
                        disabled={!canManage}
                      />
                      {label}
                    </label>
                  ))}
                </div>
              </fieldset>

              <fieldset>
                <legend className="text-sm font-medium text-foreground">Holiday calendars</legend>
                <p className="mt-0.5 text-xs text-foreground-muted">
                  Public holidays have not been added automatically. Create your holiday calendar
                  under{" "}
                  <Link href="/app/holiday-calendars" className="underline">
                    Holiday Calendars
                  </Link>{" "}
                  and link it here.
                </p>
                {holidayCalendars.length === 0 ? (
                  <p className="mt-2 text-sm text-foreground-muted">
                    No active holiday calendars exist yet. You can still activate a working week
                    now and link holidays later.
                  </p>
                ) : (
                  <div className="mt-2 flex flex-col gap-2">
                    {holidayCalendars.map((calendar) => (
                      <label key={calendar.id} className="flex items-center gap-2 text-sm">
                        <input
                          type="checkbox"
                          checked={holidayIds.includes(calendar.id)}
                          onChange={() => toggleHoliday(calendar.id)}
                          disabled={!canManage}
                        />
                        {calendar.name}
                      </label>
                    ))}
                  </div>
                )}
              </fieldset>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <FormField id="setup-name" label="Calendar name">
                  <Input
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    maxLength={150}
                    disabled={!canManage}
                  />
                </FormField>
                <FormField id="setup-effective-from" label="Effective from">
                  <Input
                    type="date"
                    value={effectiveFrom}
                    onChange={(e) => {
                      setEffectiveFrom(e.target.value);
                      edited();
                    }}
                    disabled={!canManage}
                  />
                </FormField>
              </div>

              {canManage ? (
                <div className="flex flex-wrap gap-2">
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => void handlePreview()}
                    disabled={!proposalValid || previewing}
                  >
                    {previewing ? "Previewing…" : "Preview calendar"}
                  </Button>
                  <Button
                    type="button"
                    onClick={() => {
                      setAcknowledged(false);
                      setConfirmOpen(true);
                    }}
                    disabled={!proposalValid || !preview || previewStale}
                  >
                    Review and activate
                  </Button>
                </div>
              ) : (
                <p className="text-sm text-foreground-muted">
                  You can view this suggestion but need calendar management permission to
                  activate it.
                </p>
              )}
              {previewStale ? (
                <p className="text-sm text-warning" role="alert">
                  The proposal changed after the last preview. Preview again before activating.
                </p>
              ) : null}
              {previewError ? <p className="text-sm text-danger">{previewError}</p> : null}
            </CardContent>
          </Card>

          {preview ? (
            <Card>
              <CardContent className="space-y-4 pt-6">
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="text-sm font-medium text-foreground">Preview</h3>
                  <Badge variant="outline">Not saved</Badge>
                </div>
                <p className="text-xs text-foreground-muted">
                  {preview.notice} Showing {preview.range_from} to {preview.range_to}:{" "}
                  {preview.working_day_count} working day
                  {preview.working_day_count === 1 ? "" : "s"},{" "}
                  {preview.non_working_day_count} non-working.
                </p>
                {preview.warnings.length > 0 ? (
                  <ul className="list-disc space-y-1 pl-5 text-sm text-foreground" role="status">
                    {preview.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                ) : null}
                <DayGridLegend />
                <DayGrid days={preview.days} />
              </CardContent>
            </Card>
          ) : null}
        </>
      ) : null}

      <Dialog open={confirmOpen} onOpenChange={(open) => (!confirming ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Activate this work calendar?</DialogTitle>
            <DialogDescription>
              From {effectiveFrom}, leave and attendance will classify days using this working
              week and the linked holiday calendars. Existing approved leave records are not
              changed, and locked attendance periods and closed payroll are not recalculated.
            </DialogDescription>
          </DialogHeader>
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              className="mt-1"
              checked={acknowledged}
              onChange={(e) => setAcknowledged(e.target.checked)}
            />
            I have reviewed the preview and want to activate this calendar. Public holidays are
            only included if I linked a holiday calendar.
          </label>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setConfirmOpen(false)}
              disabled={confirming}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleConfirm()}
              disabled={!acknowledged || confirming}
            >
              {confirming ? "Activating…" : "Activate calendar"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
