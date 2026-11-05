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
import type { OvertimeRecord } from "@/lib/overtime/types";

interface OvertimeReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  record: OvertimeRecord | null;
  action: "approve" | "reject";
  onDone: (record: OvertimeRecord) => void;
}

/** `POST /v1/overtime/{id}/approve|reject` (architecture §14). Backend enforces self-approval
 * blocking and stage/approver-identity matching (403) — this dialog only surfaces those as
 * messages, it does not re-implement the check. */
export function OvertimeReviewDialog({
  open,
  onOpenChange,
  record,
  action,
  onDone,
}: OvertimeReviewDialogProps) {
  const { toast } = useToast();
  const [comment, setComment] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [minutes, setMinutes] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reset() {
    setComment("");
    setRejectionReason("");
    setMinutes(null);
    setFormError(null);
  }

  const detected = record?.minutes_detected ?? 0;
  const canEditMinutes =
    action === "approve" &&
    record !== null &&
    !(record.approval_chain === "MANAGER_THEN_HR" && record.approval_stage === "MANAGER");
  const minutesText = minutes ?? String(detected);
  const minutesChanged = canEditMinutes && minutesText.trim() !== String(detected);

  async function handleConfirm() {
    if (!record) return;
    if (minutesChanged) {
      const entered = Number(minutesText);
      if (!Number.isInteger(entered) || entered < 1 || entered > detected) {
        setFormError(`Enter whole minutes from 1 to ${detected}. To pay nothing, reject instead.`);
        return;
      }
      if (!comment.trim()) {
        setFormError("Add a comment explaining why the minutes were changed.");
        return;
      }
    }
    setSaving(true);
    setFormError(null);
    try {
      const updated = await apiClient.post<OvertimeRecord>(
        `/overtime/${record.id}/${action}`,
        action === "approve"
          ? {
              reviewer_comment: comment.trim() || undefined,
              minutes_approved: minutesChanged ? Number(minutesText) : undefined,
            }
          : {
              reviewer_comment: comment.trim() || undefined,
              rejection_reason: rejectionReason.trim() || undefined,
            },
        { ifMatch: String(record.version) },
      );
      onDone(updated);
      onOpenChange(false);
      reset();
      toast({
        title: action === "approve" ? "Overtime approved" : "Overtime rejected",
        variant: "success",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setFormError(
          err.code === "OVERTIME_SELF_APPROVAL_NOT_ALLOWED"
            ? "You cannot approve or reject your own overtime record."
            : err.code === "OVERTIME_APPROVER_MISMATCH"
              ? "You are not the resolved approver for this record's current stage."
              : describeApiError(err),
        );
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        setFormError(
          err.code === "OVERTIME_INVALID_TRANSITION"
            ? "This record has already left the pending state and can no longer be reviewed."
            : "This record has already moved on (approved or rejected by someone else). " +
                "Refresh to see its current state.",
        );
        return;
      }
      if (err instanceof ApiError && err.status === 404) {
        setFormError("This overtime record was not found. It may have been removed.");
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
          <DialogTitle>{action === "approve" ? "Approve overtime" : "Reject overtime"}</DialogTitle>
          {action === "approve" ? (
            <DialogDescription>
              {canEditMinutes
                ? "Approving pays these overtime minutes for this day."
                : "Approving passes this overtime to HR for the final decision."}
            </DialogDescription>
          ) : (
            <DialogDescription>
              Rejecting clears the approved overtime minutes for this day.
            </DialogDescription>
          )}
        </DialogHeader>
        <div className="space-y-4">
          {canEditMinutes ? (
            <FormField
              id="ot-review-minutes"
              label="Minutes to approve"
              description={`${detected} detected. You can approve fewer, not more.`}
            >
              <Input
                type="number"
                min={1}
                max={detected}
                value={minutesText}
                onChange={(e) => setMinutes(e.target.value)}
              />
            </FormField>
          ) : null}
          <FormField
            id="ot-review-comment"
            label="Comment"
            description={
              minutesChanged
                ? "Required when you change the minutes. Visible to the employee."
                : "Optional, visible to the employee."
            }
          >
            <Input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
          </FormField>
          {action === "reject" ? (
            <FormField id="ot-review-rejection-reason" label="Rejection reason">
              <Input
                value={rejectionReason}
                onChange={(e) => setRejectionReason(e.target.value)}
                maxLength={2000}
              />
            </FormField>
          ) : null}
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
            variant={action === "reject" ? "destructive" : "default"}
            onClick={() => void handleConfirm()}
            disabled={saving}
          >
            {saving ? "Saving…" : action === "approve" ? "Approve" : "Reject"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
