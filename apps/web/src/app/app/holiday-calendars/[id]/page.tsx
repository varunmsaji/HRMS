"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { HolidayCalendarForm } from "@/components/holiday-calendar/holiday-calendar-form";
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
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { FormField } from "@/components/common/form-field";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import { usePermissions } from "@/lib/auth/use-permissions";
import type { Holiday, HolidayCalendar } from "@/lib/holiday-calendar/types";
import { HOLIDAY_TYPES } from "@/lib/holiday-calendar/types";
import {
  buildUpdatePatch,
  holidayCalendarToFormValues,
  validateHolidayCalendarForm,
  type HolidayCalendarFormErrors,
  type HolidayCalendarFormValues,
} from "@/lib/holiday-calendar/validate-holiday-calendar";
import {
  EMPTY_HOLIDAY_FORM_VALUES,
  buildHolidayCreatePayload,
  buildHolidayUpdatePayload,
  holidayToFormValues,
  validateHolidayForm,
  type HolidayFormErrors,
  type HolidayFormValues,
} from "@/lib/holiday-calendar/validate-holiday";

export default function HolidayCalendarDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();
  const { can } = usePermissions();
  const canManage = can("ORG.HOLIDAY.MANAGE");

  const [calendar, setCalendar] = useState<HolidayCalendar | null>(null);
  const [holidays, setHolidays] = useState<Holiday[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<HolidayCalendarFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<HolidayCalendarFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const [addHolidayOpen, setAddHolidayOpen] = useState(false);
  const [holidayValues, setHolidayValues] = useState<HolidayFormValues>(EMPTY_HOLIDAY_FORM_VALUES);
  const [holidayErrors, setHolidayErrors] = useState<HolidayFormErrors>({});
  const [savingHoliday, setSavingHoliday] = useState(false);

  const [editingHoliday, setEditingHoliday] = useState<Holiday | null>(null);
  const [editHolidayValues, setEditHolidayValues] =
    useState<HolidayFormValues>(EMPTY_HOLIDAY_FORM_VALUES);
  const [editHolidayErrors, setEditHolidayErrors] = useState<HolidayFormErrors>({});
  const [savingEditHoliday, setSavingEditHoliday] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [calendarData, holidayData] = await Promise.all([
        apiClient.get<HolidayCalendar>(`/holiday-calendars/${params.id}`),
        apiClient.get<Holiday[]>(`/holiday-calendars/${params.id}/holidays`),
      ]);
      setCalendar(calendarData);
      setHolidays(holidayData);
      return calendarData;
    } catch (err) {
      setCalendar(null);
      setHolidays(null);
      setError(
        err instanceof ApiError
          ? err
          : new ApiError({ status: 0, code: "UNKNOWN_ERROR", message: "Something went wrong." }),
      );
      return null;
    } finally {
      setLoading(false);
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  function startEditing() {
    if (!calendar) return;
    setFormValues(holidayCalendarToFormValues(calendar));
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
    const clientErrors = validateHolidayCalendarForm(formValues);
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

    setSaving(true);
    setFormErrors({});
    setStaleMessage(null);
    try {
      const updated = await apiClient.patch<HolidayCalendar>(
        `/holiday-calendars/${calendar.id}`,
        patch,
        { ifMatch: String(calendar.version) },
      );
      setCalendar(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Holiday calendar saved", variant: "success" });
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
        if (err.status === 409) {
          setFormErrors({ code: "A calendar with this code already exists." });
          return;
        }
      }
      toast({
        title: "Could not save holiday calendar",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await load();
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
        const updated = await apiClient.delete<HolidayCalendar>(
          `/holiday-calendars/${calendar.id}`,
          { ifMatch: String(calendar.version) },
        );
        setCalendar(updated);
        toast({ title: "Holiday calendar deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<HolidayCalendar>(
          `/holiday-calendars/${calendar.id}`,
          { is_active: true },
          { ifMatch: String(calendar.version) },
        );
        setCalendar(updated);
        toast({ title: "Holiday calendar reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      toast({
        title: "Could not update status",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  function openAddHoliday() {
    setHolidayValues(EMPTY_HOLIDAY_FORM_VALUES);
    setHolidayErrors({});
    setAddHolidayOpen(true);
  }

  async function handleAddHoliday() {
    const clientErrors = validateHolidayForm(holidayValues);
    if (Object.keys(clientErrors).length > 0) {
      setHolidayErrors(clientErrors);
      return;
    }
    setSavingHoliday(true);
    setHolidayErrors({});
    try {
      await apiClient.post<Holiday>(
        `/holiday-calendars/${params.id}/holidays`,
        buildHolidayCreatePayload(holidayValues),
      );
      setAddHolidayOpen(false);
      toast({ title: "Holiday added", variant: "success" });
      const data = await apiClient.get<Holiday[]>(`/holiday-calendars/${params.id}/holidays`);
      setHolidays(data);
    } catch (err) {
      if (err instanceof ApiError && err.status === 422) {
        setHolidayErrors({
          date: getFieldError(err.details, "date"),
          name: getFieldError(err.details, "name"),
        });
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        setHolidayErrors({ date: "This calendar already has an active holiday on this date." });
        return;
      }
      toast({
        title: "Could not add holiday",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSavingHoliday(false);
    }
  }

  function openEditHoliday(holiday: Holiday) {
    setEditingHoliday(holiday);
    setEditHolidayValues(holidayToFormValues(holiday));
    setEditHolidayErrors({});
  }

  async function handleEditHoliday() {
    if (!editingHoliday) return;
    const clientErrors = validateHolidayForm(editHolidayValues);
    if (Object.keys(clientErrors).length > 0) {
      setEditHolidayErrors(clientErrors);
      return;
    }
    const patch = buildHolidayUpdatePayload(editHolidayValues, editingHoliday);
    if (Object.keys(patch).length === 0) {
      setEditingHoliday(null);
      toast({ title: "No changes to save" });
      return;
    }
    setSavingEditHoliday(true);
    setEditHolidayErrors({});
    try {
      const updated = await apiClient.patch<Holiday>(`/holidays/${editingHoliday.id}`, patch, {
        ifMatch: String(editingHoliday.version),
      });
      setHolidays((prev) => (prev ? prev.map((h) => (h.id === updated.id ? updated : h)) : prev));
      setEditingHoliday(null);
      toast({ title: "Holiday saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && err.code === "STALE_RESOURCE") {
        setEditHolidayErrors({});
        toast({
          title: "This holiday was changed by someone else",
          description: "Close the dialog and reopen it to see the latest version.",
          variant: "danger",
        });
        return;
      }
      if (err instanceof ApiError && err.status === 422) {
        setEditHolidayErrors({ name: getFieldError(err.details, "name") });
        return;
      }
      toast({
        title: "Could not save holiday",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSavingEditHoliday(false);
    }
  }

  async function toggleHolidayActive(holiday: Holiday) {
    try {
      const updated = await apiClient.patch<Holiday>(
        `/holidays/${holiday.id}`,
        { is_active: !holiday.is_active },
        { ifMatch: String(holiday.version) },
      );
      setHolidays((prev) => (prev ? prev.map((h) => (h.id === updated.id ? updated : h)) : prev));
    } catch (err) {
      toast({
        title: "Could not update holiday",
        description: describeApiError(err),
        variant: "danger",
      });
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link
          href="/app/holiday-calendars"
          className="text-sm text-foreground-secondary hover:underline"
        >
          ← Holiday Calendars
        </Link>
      </div>

      <PageHeader
        title={calendar?.name ?? "Holiday Calendar"}
        description="Holiday dates in this reusable calendar."
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

      <Card>
        <CardContent className="pt-6">
          {loading ? <LoadingState label="Loading holiday calendar…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this calendar."
                  : error.status === 404
                    ? "This holiday calendar could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void load()}
            />
          ) : null}

          {staleMessage ? (
            <div className="mb-4 rounded-md border border-warning/30 bg-warning/5 p-4" role="alert">
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

          {!loading && !error && calendar && editing && formValues ? (
            <div className="space-y-6">
              <HolidayCalendarForm values={formValues} errors={formErrors} onChange={setFormValues} />
              <div className="flex flex-wrap gap-2">
                <Button type="button" onClick={() => void handleSave()} disabled={saving}>
                  {saving ? "Saving…" : "Save changes"}
                </Button>
                <Button type="button" variant="outline" onClick={cancelEditing} disabled={saving}>
                  Cancel
                </Button>
              </div>
            </div>
          ) : null}

          {!loading && !error && calendar && !editing ? (
            <div className="space-y-3">
              <Badge variant={calendar.is_active ? "secondary" : "outline"}>
                {calendar.is_active ? "Active" : "Inactive"}
              </Badge>
              <dl className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    Kind
                  </dt>
                  <dd className="mt-0.5 text-sm text-foreground">{calendar.kind}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    State code
                  </dt>
                  <dd className="mt-0.5 text-sm text-foreground">
                    {calendar.state_code ?? "Not configured"}
                  </dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">
                    Holidays
                  </dt>
                  <dd className="mt-0.5 text-sm text-foreground">{holidays?.length ?? 0}</dd>
                </div>
              </dl>
            </div>
          ) : null}
        </CardContent>
      </Card>

      {!loading && !error && calendar ? (
        <Card>
          <CardContent className="pt-6">
            <div className="flex items-center justify-between">
              <h3 className="text-sm font-medium text-foreground">Holidays</h3>
              {canManage ? (
                <Button type="button" size="sm" onClick={openAddHoliday}>
                  Add Holiday
                </Button>
              ) : null}
            </div>

            {holidays && holidays.length === 0 ? (
              <p className="mt-4 text-sm text-foreground-muted">
                No holidays have been added to this calendar yet.
              </p>
            ) : null}

            {holidays && holidays.length > 0 ? (
              <ul className="mt-4 divide-y divide-border">
                {holidays
                  .slice()
                  .sort((a, b) => a.date.localeCompare(b.date))
                  .map((holiday) => (
                    <li
                      key={holiday.id}
                      className="flex items-center justify-between gap-4 py-3 first:pt-0 last:pb-0"
                    >
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          {holiday.name}
                          <span className="ml-2 text-xs text-foreground-muted">
                            {holiday.holiday_type.replace("_", " ")}
                          </span>
                        </p>
                        <p className="mt-0.5 text-xs text-foreground-muted">{holiday.date}</p>
                      </div>
                      <div className="flex items-center gap-2">
                        <Badge variant={holiday.is_active ? "secondary" : "outline"}>
                          {holiday.is_active ? "Active" : "Inactive"}
                        </Badge>
                        {canManage ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => openEditHoliday(holiday)}
                          >
                            Edit
                          </Button>
                        ) : null}
                        {canManage ? (
                          <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            onClick={() => void toggleHolidayActive(holiday)}
                          >
                            {holiday.is_active ? "Deactivate" : "Reactivate"}
                          </Button>
                        ) : null}
                      </div>
                    </li>
                  ))}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      ) : null}

      <Dialog
        open={confirmOpen}
        onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {calendar?.is_active ? "Deactivate holiday calendar?" : "Reactivate holiday calendar?"}
            </DialogTitle>
            <DialogDescription>
              {calendar?.is_active
                ? "This calendar will no longer be assignable to new work calendars. You can reactivate it later."
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
        open={addHolidayOpen}
        onOpenChange={(open) => (!savingHoliday ? setAddHolidayOpen(open) : null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Add Holiday</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField id="holiday-date" label="Date" required error={holidayErrors.date}>
                <Input
                  type="date"
                  value={holidayValues.date}
                  onChange={(e) => setHolidayValues({ ...holidayValues, date: e.target.value })}
                />
              </FormField>
              <FormField id="holiday-name" label="Name" required error={holidayErrors.name}>
                <Input
                  value={holidayValues.name}
                  onChange={(e) => setHolidayValues({ ...holidayValues, name: e.target.value })}
                />
              </FormField>
              <FormField id="holiday-type" label="Type">
                <NativeSelect
                  value={holidayValues.holidayType}
                  onChange={(e) =>
                    setHolidayValues({
                      ...holidayValues,
                      holidayType: e.target.value as HolidayFormValues["holidayType"],
                    })
                  }
                >
                  {HOLIDAY_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type.replace("_", " ")}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
              <FormField id="holiday-region-note" label="Region note">
                <Input
                  value={holidayValues.regionNote}
                  onChange={(e) =>
                    setHolidayValues({ ...holidayValues, regionNote: e.target.value })
                  }
                />
              </FormField>
            </div>
            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="rounded border-border"
                  checked={holidayValues.isPaid}
                  onChange={(e) =>
                    setHolidayValues({ ...holidayValues, isPaid: e.target.checked })
                  }
                />
                Paid
              </label>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="rounded border-border"
                  checked={holidayValues.isWorking}
                  onChange={(e) =>
                    setHolidayValues({ ...holidayValues, isWorking: e.target.checked })
                  }
                />
                Working holiday (operations continue)
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setAddHolidayOpen(false)}
              disabled={savingHoliday}
            >
              Cancel
            </Button>
            <Button type="button" onClick={() => void handleAddHoliday()} disabled={savingHoliday}>
              {savingHoliday ? "Adding…" : "Add holiday"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        open={editingHoliday !== null}
        onOpenChange={(open) => (!savingEditHoliday && !open ? setEditingHoliday(null) : null)}
      >
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Edit Holiday</DialogTitle>
            <DialogDescription>
              The date can&apos;t be changed here — deactivate this holiday and add a new one on
              the correct date instead.
            </DialogDescription>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-4 overflow-y-auto pr-1">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <FormField id="edit-holiday-date" label="Date">
                <Input type="date" value={editHolidayValues.date} disabled />
              </FormField>
              <FormField id="edit-holiday-name" label="Name" required error={editHolidayErrors.name}>
                <Input
                  value={editHolidayValues.name}
                  onChange={(e) =>
                    setEditHolidayValues({ ...editHolidayValues, name: e.target.value })
                  }
                />
              </FormField>
              <FormField id="edit-holiday-type" label="Type">
                <NativeSelect
                  value={editHolidayValues.holidayType}
                  onChange={(e) =>
                    setEditHolidayValues({
                      ...editHolidayValues,
                      holidayType: e.target.value as HolidayFormValues["holidayType"],
                    })
                  }
                >
                  {HOLIDAY_TYPES.map((type) => (
                    <option key={type} value={type}>
                      {type.replace("_", " ")}
                    </option>
                  ))}
                </NativeSelect>
              </FormField>
              <FormField id="edit-holiday-region-note" label="Region note">
                <Input
                  value={editHolidayValues.regionNote}
                  onChange={(e) =>
                    setEditHolidayValues({ ...editHolidayValues, regionNote: e.target.value })
                  }
                />
              </FormField>
            </div>
            <div className="flex flex-wrap gap-4">
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="rounded border-border"
                  checked={editHolidayValues.isPaid}
                  onChange={(e) =>
                    setEditHolidayValues({ ...editHolidayValues, isPaid: e.target.checked })
                  }
                />
                Paid
              </label>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input
                  type="checkbox"
                  className="rounded border-border"
                  checked={editHolidayValues.isWorking}
                  onChange={(e) =>
                    setEditHolidayValues({ ...editHolidayValues, isWorking: e.target.checked })
                  }
                />
                Working holiday (operations continue)
              </label>
            </div>
          </div>
          <DialogFooter>
            <Button
              type="button"
              variant="outline"
              onClick={() => setEditingHoliday(null)}
              disabled={savingEditHoliday}
            >
              Cancel
            </Button>
            <Button
              type="button"
              onClick={() => void handleEditHoliday()}
              disabled={savingEditHoliday}
            >
              {savingEditHoliday ? "Saving…" : "Save changes"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
