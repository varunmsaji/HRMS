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
import { describeApiError } from "@/lib/api/errors";
import type { AttendanceDay } from "@/lib/attendance/types";

interface KeepLeaveDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  day: AttendanceDay;
  onDone: (day: AttendanceDay) => void;
}

/** `POST /v1/attendance/days/{id}/work-on-leave/keep-leave` (`ATTENDANCE.RECOMPUTE`, BUS-012) —
 * HR confirms an approved full-day leave stands over punches on the same day. The other way to
 * resolve the conflict is cancelling the leave, which happens in Leave, not here. */
export function KeepLeaveDialog({ open, onOpenChange, day, onDone }: KeepLeaveDialogProps) {
  const { toast } = useToast();
  const [reason, setReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit() {
    if (!reason.trim()) {
      setFormError("A reason is required.");
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      const updated = await apiClient.post<AttendanceDay>(
        `/attendance/days/${day.id}/work-on-leave/keep-leave`,
        { reason: reason.trim() },
      );
      onDone(updated);
      onOpenChange(false);
      setReason("");
      toast({ title: "Leave kept for this day", variant: "success" });
    } catch (err) {
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
        if (!next) {
          setReason("");
          setFormError(null);
        }
        onOpenChange(next);
      }}
    >
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>Keep the leave for this day?</DialogTitle>
          <DialogDescription>
            The employee punched in on a day of approved full-day leave. Keeping the leave means the
            day stays paid as leave and the punches are ignored. To pay the day as worked instead,
            cancel the leave application — the day then recalculates from its punches.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <FormField id="keep-leave-reason" label="Reason" description="Required.">
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
          <Button type="button" onClick={() => void handleSubmit()} disabled={saving}>
            {saving ? "Saving…" : "Keep leave"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
