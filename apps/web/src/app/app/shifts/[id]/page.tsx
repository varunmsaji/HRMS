"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { ShiftForm } from "@/components/shift/shift-form";
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
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError, getFieldError } from "@/lib/api/errors";
import type { Shift } from "@/lib/shift/types";
import {
  buildUpdatePatch,
  shiftToFormValues,
  validateShiftForm,
  type ShiftFormErrors,
  type ShiftFormValues,
} from "@/lib/shift/validate-shift";

function DetailField({ label, value }: { label: string; value: string | null | undefined }) {
  const display = value && value.trim() ? value : "Not configured";
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-foreground-muted">{label}</dt>
      <dd className={`mt-0.5 text-sm ${value && value.trim() ? "text-foreground" : "text-foreground-muted"}`}>
        {display}
      </dd>
    </div>
  );
}

export default function ShiftDetailPage() {
  const params = useParams<{ id: string }>();
  const { toast } = useToast();

  const [shift, setShift] = useState<Shift | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<ApiError | null>(null);

  const [editing, setEditing] = useState(false);
  const [formValues, setFormValues] = useState<ShiftFormValues | null>(null);
  const [formErrors, setFormErrors] = useState<ShiftFormErrors>({});
  const [saving, setSaving] = useState(false);
  const [staleMessage, setStaleMessage] = useState<string | null>(null);

  const [confirmOpen, setConfirmOpen] = useState(false);
  const [statusChanging, setStatusChanging] = useState(false);

  const loadShift = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiClient.get<Shift>(`/shifts/${params.id}`);
      setShift(data);
      return data;
    } catch (err) {
      setShift(null);
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
    void loadShift();
  }, [loadShift]);

  function startEditing() {
    if (!shift) return;
    setFormValues(shiftToFormValues(shift));
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
    if (!shift || !formValues) return;

    const clientErrors = validateShiftForm(formValues);
    if (Object.keys(clientErrors).length > 0) {
      setFormErrors(clientErrors);
      return;
    }

    const patch = buildUpdatePatch(formValues, shift);
    if (Object.keys(patch).length === 0) {
      setEditing(false);
      setFormValues(null);
      toast({ title: "No changes to save", variant: "default" });
      return;
    }

    setSaving(true);
    setFormErrors({});
    setStaleMessage(null);
    try {
      const updated = await apiClient.patch<Shift>(`/shifts/${shift.id}`, patch, {
        ifMatch: String(shift.version),
      });
      setShift(updated);
      setEditing(false);
      setFormValues(null);
      toast({ title: "Shift saved", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError) {
        if (err.status === 409 && err.code === "STALE_RESOURCE") {
          setStaleMessage("This shift was changed by someone else.");
          return;
        }
        if (err.status === 422) {
          setFormErrors({
            name: getFieldError(err.details, "name"),
            startTime: getFieldError(err.details, "start_time"),
            endTime:
              getFieldError(err.details, "end_time") ??
              (err.code === "INVALID_SHIFT_TIME_RANGE"
                ? "End time must be after start time unless this is a cross-midnight shift."
                : undefined),
            minHoursFullDay:
              err.code === "INVALID_SHIFT_HOURS_RANGE"
                ? "Min hours for full day must be greater than the half-day threshold."
                : undefined,
          });
          return;
        }
        if (err.status === 403) {
          setError(err);
          setEditing(false);
          return;
        }
      }
      toast({
        title: "Could not save shift",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setSaving(false);
    }
  }

  async function reloadLatest() {
    const latest = await loadShift();
    if (latest) {
      setEditing(false);
      setFormValues(null);
      setStaleMessage(null);
      toast({ title: "Shift reloaded", variant: "success" });
    }
  }

  async function handleToggleStatus() {
    if (!shift) return;
    setStatusChanging(true);
    try {
      if (shift.is_active) {
        const updated = await apiClient.delete<Shift>(`/shifts/${shift.id}`, {
          ifMatch: String(shift.version),
        });
        setShift(updated);
        toast({ title: "Shift deactivated", variant: "success" });
      } else {
        const updated = await apiClient.patch<Shift>(
          `/shifts/${shift.id}`,
          { is_active: true },
          { ifMatch: String(shift.version) },
        );
        setShift(updated);
        toast({ title: "Shift reactivated", variant: "success" });
      }
      setConfirmOpen(false);
    } catch (err) {
      toast({
        title: "Could not update shift status",
        description: describeApiError(err),
        variant: "danger",
      });
    } finally {
      setStatusChanging(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/app/shifts" className="text-sm text-foreground-secondary hover:underline">
          ← Shifts
        </Link>
      </div>

      <PageHeader
        title={shift?.name ?? "Shift"}
        description="Timings, breaks, and grace period details for this shift."
        actions={
          shift && !editing ? (
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" onClick={() => setConfirmOpen(true)}>
                {shift.is_active ? "Deactivate" : "Reactivate"}
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
          {loading ? <LoadingState label="Loading shift…" /> : null}

          {error && !loading ? (
            <ErrorState
              message={
                error.status === 403
                  ? "You do not have permission to view this shift."
                  : error.status === 404
                    ? "This shift could not be found."
                    : error.message
              }
              onRetry={error.status === 404 ? undefined : () => void loadShift()}
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

          {!loading && !error && shift && editing && formValues ? (
            <div className="space-y-6">
              <ShiftForm values={formValues} errors={formErrors} onChange={setFormValues} />
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

          {!loading && !error && shift && !editing ? (
            <div className="space-y-8">
              <div>
                <Badge variant={shift.is_active ? "secondary" : "outline"}>
                  {shift.is_active ? "Active" : "Inactive"}
                </Badge>
              </div>
              <section>
                <h3 className="text-sm font-medium text-foreground">Identity</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Shift name" value={shift.name} />
                  <DetailField label="Shift code" value={shift.code} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Timings</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Start time" value={shift.start_time} />
                  <DetailField label="End time" value={shift.end_time} />
                  <DetailField label="Crosses midnight" value={shift.is_cross_midnight ? "Yes" : "No"} />
                  <DetailField label="Night shift" value={shift.is_night_shift ? "Yes" : "No"} />
                  <DetailField label="Overtime eligible" value={shift.is_ot_eligible ? "Yes" : "No"} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Breaks &amp; grace</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField label="Paid break" value={`${shift.break_minutes_paid} minutes`} />
                  <DetailField label="Unpaid break" value={`${shift.break_minutes_unpaid} minutes`} />
                  <DetailField label="Grace in" value={`${shift.grace_in_minutes} minutes`} />
                  <DetailField label="Grace out" value={`${shift.grace_out_minutes} minutes`} />
                </dl>
              </section>
              <section>
                <h3 className="text-sm font-medium text-foreground">Full-day / half-day hours</h3>
                <dl className="mt-3 grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <DetailField
                    label="Half-day threshold"
                    value={
                      shift.half_day_threshold_hours === null
                        ? null
                        : `${shift.half_day_threshold_hours} hours`
                    }
                  />
                  <DetailField
                    label="Min hours for full day"
                    value={shift.min_hours_full_day === null ? null : `${shift.min_hours_full_day} hours`}
                  />
                </dl>
              </section>
            </div>
          ) : null}
        </CardContent>
      </Card>

      <Dialog open={confirmOpen} onOpenChange={(open) => (!statusChanging ? setConfirmOpen(open) : null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{shift?.is_active ? "Deactivate shift?" : "Reactivate shift?"}</DialogTitle>
            <DialogDescription>
              {shift?.is_active
                ? "This shift will no longer be available for new activity. You can reactivate it later."
                : "This shift will become available for use again."}
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
              variant={shift?.is_active ? "destructive" : "default"}
              onClick={() => void handleToggleStatus()}
              disabled={statusChanging}
            >
              {statusChanging ? "Saving…" : shift?.is_active ? "Deactivate" : "Reactivate"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
