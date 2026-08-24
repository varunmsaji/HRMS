"use client";

import { useState } from "react";

import { useToast } from "@/components/common/toast";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import {
  ATTENDANCE_PERIOD_BLOCKING_REASON_LABELS,
  type AttendancePeriod,
  type AttendancePeriodBlockingReason,
} from "@/lib/attendance-period/types";

interface FinalizePeriodDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  period: AttendancePeriod | null;
  onDone: (period: AttendancePeriod) => void;
}

/** `POST /v1/attendance-periods/{id}/finalize` (architecture §4.2/§5, decision log WD-30).
 * Backend always re-validates fresh and fails closed — this dialog does not pre-check; it
 * attempts finalize directly and, on `ATTENDANCE_FINALIZATION_BLOCKED`, renders the typed
 * blocking reasons the 409 response carries so the caller sees exactly what to fix, without a
 * second round trip. */
export function FinalizePeriodDialog({
  open,
  onOpenChange,
  period,
  onDone,
}: FinalizePeriodDialogProps) {
  const { toast } = useToast();
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [reasons, setReasons] = useState<AttendancePeriodBlockingReason[] | null>(null);

  function reset() {
    setFormError(null);
    setReasons(null);
  }

  async function handleFinalize() {
    if (!period) return;
    setSaving(true);
    setFormError(null);
    setReasons(null);
    try {
      const updated = await apiClient.post<AttendancePeriod>(
        `/attendance-periods/${period.id}/finalize`,
        {},
        { ifMatch: String(period.version) },
      );
      onDone(updated);
      onOpenChange(false);
      reset();
      toast({ title: "Period finalized and locked", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.code === "ATTENDANCE_FINALIZATION_BLOCKED") {
        const context = err.details[0]?.context as { reasons?: AttendancePeriodBlockingReason[] } | undefined;
        setReasons(context?.reasons ?? []);
        setFormError("This period is not ready to finalize.");
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        setFormError(
          "This period has already been changed by another request. Refresh to see its current state.",
        );
        return;
      }
      setFormError(describeApiError(err));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (saving) return;
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Finalize and lock this period</DialogTitle>
          <DialogDescription>
            {period ? `${period.period_start} to ${period.period_end}. ` : ""}
            Once finalized, attendance in this range becomes immutable — punches, roster changes,
            regularizations, and overtime approvals for these dates will all be refused until the
            period is reopened.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {formError ? (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          ) : null}
          {reasons && reasons.length > 0 ? (
            <ul className="space-y-2 rounded-md border border-border bg-surface-secondary p-3 text-sm">
              {reasons.map((reason) => (
                <li key={reason.code}>
                  <p className="font-medium text-foreground">
                    {ATTENDANCE_PERIOD_BLOCKING_REASON_LABELS[reason.code] ?? reason.code}
                    {" — "}
                    {reason.count}
                  </p>
                  <p className="text-foreground-secondary">{reason.message}</p>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" onClick={() => void handleFinalize()} disabled={saving}>
            {saving ? "Finalizing…" : "Finalize & lock"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
