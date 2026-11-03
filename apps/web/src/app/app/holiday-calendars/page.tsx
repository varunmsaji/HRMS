"use client";

import { CalendarDays, Plus } from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { HolidayCalendarForm } from "@/components/holiday-calendar/holiday-calendar-form";
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
} from "@/components/ui/table";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { HolidayCalendar } from "@/lib/holiday-calendar/types";
import {
  EMPTY_HOLIDAY_CALENDAR_FORM_VALUES,
  buildCreatePayload,
  validateHolidayCalendarForm,
  type HolidayCalendarFormErrors,
  type HolidayCalendarFormValues,
} from "@/lib/holiday-calendar/validate-holiday-calendar";

export default function HolidayCalendarsPage() {
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("ORG.HOLIDAY.MANAGE");

  const [calendars, setCalendars] = useState<HolidayCalendar[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [createOpen, setCreateOpen] = useState(false);
  const [formValues, setFormValues] = useState<HolidayCalendarFormValues>(
    EMPTY_HOLIDAY_CALENDAR_FORM_VALUES,
  );
  const [formErrors, setFormErrors] = useState<HolidayCalendarFormErrors>({});
  const [saving, setSaving] = useState(false);

  const loadCalendars = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<HolidayCalendar[]>("/holiday-calendars");
      setCalendars(data);
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
    void loadCalendars();
  }, [loadCalendars]);

  function openCreate() {
    setFormValues(EMPTY_HOLIDAY_CALENDAR_FORM_VALUES);
    setFormErrors({});
    setCreateOpen(true);
  }

  async function handleCreate() {
    const clientErrors = validateHolidayCalendarForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    setSaving(true);
    setFormErrors({});
    try {
      await apiClient.post<HolidayCalendar>("/holiday-calendars", buildCreatePayload(formValues));
      setCreateOpen(false);
      toast({ title: "Holiday calendar added", variant: "success" });
      await loadCalendars();
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setFormErrors({ name: getFieldError(err.details, "name") });
        return;
      }
      if (err instanceof ApiError && err.status === 403) {
        setCreateOpen(false);
        toast({ title: "You don't have permission to add holiday calendars", variant: "danger" });
        return;
      }
      toast({
        title: "Could not add holiday calendar",
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
        title="Holiday Calendars"
        description="Reusable holiday date collections — e.g. India National, Kerala Office, Company FY26."
        actions={
          canManage && calendars && calendars.length > 0 ? (
            <Button type="button" onClick={openCreate}>
              <Plus className="h-4 w-4" aria-hidden="true" />
              Add Holiday Calendar
            </Button>
          ) : null
        }
      />

      <TableContainer>
        {loading ? <LoadingState label="Loading holiday calendars…" /> : null}

        {error && !loading ? (
          <div className="p-6">
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view holiday calendars."
                  : error.message
              }
              onRetry={() => void loadCalendars()}
            />
          </div>
        ) : null}

        {!loading && !error && calendars && calendars.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon={CalendarDays}
              title="No holiday calendars have been configured yet."
              description="Add a reusable holiday date collection, e.g. India National or Kerala Office."
              action={
                canManage ? (
                  <Button type="button" onClick={openCreate}>
                    Add Holiday Calendar
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
                <TableHead>Scope / State</TableHead>
                <TableHead>Status</TableHead>
                <TableHead align="right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {calendars.map((calendar) => (
                <TableRow key={calendar.id}>
                  <TableCell>
                    <Link
                      href={`/app/holiday-calendars/${calendar.id}`}
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
                    {calendar.kind}
                    {calendar.state_code ? ` · ${calendar.state_code}` : ""}
                  </TableCell>
                  <TableCell>
                    <Badge variant={calendar.is_active ? "secondary" : "outline"}>
                      {calendar.is_active ? "Active" : "Inactive"}
                    </Badge>
                  </TableCell>
                  <TableCell align="right">
                    <Link
                      href={`/app/holiday-calendars/${calendar.id}`}
                      className="text-xs font-medium text-primary hover:underline"
                    >
                      Manage holidays
                    </Link>
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
            <DialogTitle>Add Holiday Calendar</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] overflow-y-auto pr-1">
            <HolidayCalendarForm
              values={formValues}
              errors={formErrors}
              onChange={setFormValues}
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
