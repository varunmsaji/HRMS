"use client";

import { useRef, useState } from "react";

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

/** Statuses the server accepts for cancel (mirrors `ONBOARDING_CASE_CANCELLABLE_STATUSES`). */
export const ONBOARDING_CANCELLABLE_STATUSES = [
  "DRAFT",
  "INVITED",
  "IN_PROGRESS",
  "SUBMITTED",
  "UNDER_REVIEW",
  "VERIFIED",
  "CHANGES_REQUESTED",
];

export const CANCEL_REASON_MAX_LENGTH = 500;

interface CancelOnboardingDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  caseId: string;
  candidateName: string;
  hasLiveLink: boolean;
  onCancelled: () => void;
}

/** `POST /onboarding-cases/{id}/cancel`. Needs an explicit confirmation click; the reason is
 * optional and recorded in the audit trail only (the candidate is not emailed). */
export function CancelOnboardingDialog({
  open,
  onOpenChange,
  caseId,
  candidateName,
  hasLiveLink,
  onCancelled,
}: CancelOnboardingDialogProps) {
  const { toast } = useToast();
  const [reason, setReason] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const lockRef = useRef(false);

  async function handleCancel() {
    if (lockRef.current) return; // double-click guard
    lockRef.current = true;
    setSaving(true);
    setError(null);
    try {
      await apiClient.post(`/onboarding-cases/${caseId}/cancel`, {
        reason: reason.trim() || null,
      });
      toast({ title: "Onboarding cancelled", variant: "success" });
      setReason("");
      onOpenChange(false);
      onCancelled();
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to cancel onboarding", variant: "danger" });
        onOpenChange(false);
        return;
      }
      if (err instanceof ApiError && err.status === 409) {
        setError("This onboarding case can no longer be cancelled. Refresh to see its latest status.");
        return;
      }
      setError(describeApiError(err));
    } finally {
      lockRef.current = false;
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Cancel onboarding for {candidateName || "this candidate"}?</DialogTitle>
          <DialogDescription>
            The case is closed and cannot be reopened.
            {hasLiveLink ? " Their onboarding link stops working immediately." : ""} The candidate is
            not emailed, and the case and its history stay on record. You can start a new onboarding
            for the same email afterwards.
          </DialogDescription>
        </DialogHeader>
        <FormField id="cancelReason" label="Reason (optional, kept in the audit trail)">
          <Input
            value={reason}
            maxLength={CANCEL_REASON_MAX_LENGTH}
            onChange={(e) => setReason(e.target.value)}
          />
        </FormField>
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Keep onboarding
          </Button>
          <Button type="button" variant="destructive" onClick={() => void handleCancel()} disabled={saving}>
            {saving ? "Cancelling…" : "Cancel onboarding"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
