"use client";

import { useState } from "react";

import { FormField } from "@/components/common/form-field";
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
import { Input } from "@/components/ui/input";
import { apiClient } from "@/lib/api/client";
import { ApiError, describeApiError } from "@/lib/api/errors";
import type { AttendancePeriod, AttendancePeriodReopenPayload } from "@/lib/attendance-period/types";

interface ReopenPeriodDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  period: AttendancePeriod | null;
  onDone: (period: AttendancePeriod) => void;
}

/** `POST /v1/attendance-periods/{id}/reopen` (`ATTENDANCE.UNLOCK` — architecture §13.4/§23.2, a
 * materially higher-risk action than finalize, gated by its own permission). Unlocks every
 * `AttendanceDay` in range; does not itself recompute or restore anything. */
export function ReopenPeriodDialog({ open, onOpenChange, period, onDone }: ReopenPeriodDialogProps) {
  const { toast } = useToast();
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reset() {
    setReason("");
    setFormError(null);
  }

  async function handleReopen() {
    if (!period) return;
    if (!reason.trim()) {
      setFormError("A reason is required to reopen a locked period.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const payload: AttendancePeriodReopenPayload = { reason: reason.trim() };
      const updated = await apiClient.post<AttendancePeriod>(
        `/attendance-periods/${period.id}/reopen`,
        payload,
        { ifMatch: String(period.version) },
      );
      onDone(updated);
      onOpenChange(false);
      reset();
      toast({ title: "Period reopened", variant: "success" });
    } catch (err) {
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
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Reopen this locked period</DialogTitle>
          <DialogDescription>
            Unlocks every attendance day in this period so it can be corrected. The period must be
            finalized again afterwards to re-lock it and regenerate the frozen summary.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField id="reopen-reason" label="Reason" description="Required.">
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={1000} />
          </FormField>
          {formError ? (
            <p role="alert" className="text-sm text-danger">
              {formError}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={() => void handleReopen()}
            disabled={saving}
          >
            {saving ? "Reopening…" : "Reopen period"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
