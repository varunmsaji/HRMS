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
import type { LeaveApplication } from "@/lib/leave-application/types";

interface LeaveApplicationReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  application: LeaveApplication | null;
  /** `approve` clears the current stage — for `MANAGER_THEN_HR` a manager's approval only moves
   * the application to the `HR` stage; only the final stage debits the ledger and syncs
   * `LeaveDayProjection` (LD-12). */
  action: "approve" | "reject";
  onDone: (application: LeaveApplication) => void;
}

/** `POST /v1/leave-applications/{id}/approve|reject`. Backend enforces self-approval blocking,
 * stage/approver-identity matching (403), and — on approve — that every day's attendance period
 * is still open before debiting anything (LD-12, all-or-nothing). This dialog only surfaces those
 * as messages, it does not re-implement the checks. */
export function LeaveApplicationReviewDialog({
  open,
  onOpenChange,
  application,
  action,
  onDone,
}: LeaveApplicationReviewDialogProps) {
  const { toast } = useToast();
  const [comment, setComment] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function reset() {
    setComment("");
    setRejectionReason("");
    setFormError(null);
  }

  async function handleConfirm() {
    if (!application) return;
    setSaving(true);
    setFormError(null);
    try {
      const updated = await apiClient.post<LeaveApplication>(
        `/leave-applications/${application.id}/${action}`,
        action === "approve"
          ? { reviewer_comment: comment.trim() || undefined }
          : {
              reviewer_comment: comment.trim() || undefined,
              rejection_reason: rejectionReason.trim() || undefined,
            },
        { ifMatch: String(application.version) },
      );
      onDone(updated);
      onOpenChange(false);
      reset();
      toast({
        title: action === "approve" ? "Leave application approved" : "Leave application rejected",
        variant: "success",
      });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        setFormError(
          err.code === "LEAVE_APPLICATION_SELF_APPROVAL_NOT_ALLOWED"
            ? "You cannot approve or reject your own application."
            : err.code === "LEAVE_APPLICATION_APPROVER_MISMATCH"
              ? "You are not the resolved approver for this application's current stage."
              : describeApiError(err),
        );
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        setFormError(
          "This application has already moved on (approved, rejected, or cancelled by someone " +
            "else), or one of its dates falls in an attendance period that's now closed. Refresh " +
            "to see its current state.",
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
          <DialogTitle>
            {action === "approve" ? "Approve leave application" : "Reject leave application"}
          </DialogTitle>
          {action === "approve" ? (
            <DialogDescription>
              Approving debits the employee's balance and marks each covered date as leave for
              attendance purposes. If this is a `MANAGER_THEN_HR` chain and you're the manager,
              this only forwards it to HR — nothing is debited yet.
            </DialogDescription>
          ) : (
            <DialogDescription>No balance or attendance change is made when an application is rejected.</DialogDescription>
          )}
        </DialogHeader>
        <div className="space-y-4">
          <FormField id="leave-review-comment" label="Comment" description="Optional, visible to the employee.">
            <Input value={comment} onChange={(e) => setComment(e.target.value)} maxLength={2000} />
          </FormField>
          {action === "reject" ? (
            <FormField id="leave-review-rejection-reason" label="Rejection reason">
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
