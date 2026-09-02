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
import type { OnboardingDocumentWithUrl } from "@/lib/onboarding/types";

interface DocumentRejectDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  caseId: string;
  document: OnboardingDocumentWithUrl | null;
  onDone: (document: OnboardingDocumentWithUrl) => void;
}

/** `POST /onboarding-cases/{caseId}/documents/{id}/review` with `status: "REJECTED"` — the
 * backend requires a non-empty `rejection_reason` for this status (422 otherwise), so this
 * dialog exists only for reject; "Verify" needs no reason and fires directly from the list. */
export function DocumentRejectDialog({
  open,
  onOpenChange,
  caseId,
  document,
  onDone,
}: DocumentRejectDialogProps) {
  const { toast } = useToast();
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleReject() {
    if (!document) return;
    if (!reason.trim()) {
      setError("A rejection reason is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const updated = await apiClient.post<OnboardingDocumentWithUrl>(
        `/onboarding-cases/${caseId}/documents/${document.id}/review`,
        { status: "REJECTED", rejection_reason: reason.trim() },
      );
      onDone({ ...updated, download_url: document.download_url });
      onOpenChange(false);
      setReason("");
      toast({ title: "Document rejected", variant: "success" });
    } catch (err) {
      if (err instanceof ApiError && err.status === 403) {
        toast({ title: "You don't have permission to review this document", variant: "danger" });
        onOpenChange(false);
        return;
      }
      toast({ title: "Could not reject document", description: describeApiError(err), variant: "danger" });
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => (!saving ? onOpenChange(next) : null)}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Reject {document?.original_filename}</DialogTitle>
          <DialogDescription>The candidate will need to upload a replacement.</DialogDescription>
        </DialogHeader>
        <FormField id="rejectionReason" label="Reason" required error={error ?? undefined}>
          <Input value={reason} onChange={(e) => setReason(e.target.value)} />
        </FormField>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)} disabled={saving}>
            Cancel
          </Button>
          <Button type="button" variant="destructive" onClick={() => void handleReject()} disabled={saving}>
            {saving ? "Rejecting…" : "Reject"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
